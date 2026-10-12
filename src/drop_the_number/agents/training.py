"""Optional local-only Torch/SB3 training and portable actor export."""

import hashlib
import json
import shutil
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from math import isfinite
from numbers import Real

import torch
from stable_baselines3 import PPO
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import DummyVecEnv
from stable_baselines3.common.callbacks import BaseCallback

from drop_the_number import __version__
from drop_the_number.core import Rules
from drop_the_number.env import DropNumberEnv
from .evaluation import evaluate
from .observation import OBSERVATION_ID, OBSERVATION_SIZES
from .policy import POLICY_SCHEMA, Policy
from .files import atomic_json, replace
from .baselines import GreedyAgent, RandomAgent


def export_actor(model, metadata=None):
    kind = (metadata or {}).get("config", {}).get("observation", OBSERVATION_ID)
    if kind not in OBSERVATION_SIZES or model.observation_space.shape != (OBSERVATION_SIZES[kind],):
        raise ValueError("モデルと書き出し設定の観測形式が一致しません。")
    layers = []
    modules = list(model.policy.mlp_extractor.policy_net)
    for index in range(0, len(modules), 2):
        linear, activation = modules[index:index + 2]
        if not isinstance(linear, torch.nn.Linear) or not isinstance(activation, torch.nn.Tanh):
            raise ValueError("書き出しはLinear/TanhのMLPだけに対応しています。")
        layers.append({"weights": linear.weight.detach().cpu().tolist(),
                       "biases": linear.bias.detach().cpu().tolist(), "activation": "tanh"})
    linear = model.policy.action_net
    layers.append({"weights": linear.weight.detach().cpu().tolist(),
                   "biases": linear.bias.detach().cpu().tolist(), "activation": "linear"})
    data = {"schema": POLICY_SCHEMA, "engine": __version__, "rules": asdict(Rules()),
            "observation": kind, "name": f"PPO / {model.num_timesteps:,}手",
            "metadata": metadata or {}, "layers": layers}
    Policy(data)
    return data


def validate_config(config):
    if config.get("schema") != "drop-number/train-v1" or config.get("algorithm") != "ppo":
        raise ValueError("学習設定の形式・アルゴリズムが不正です。")
    limits = {"timesteps": (1, 100_000_000), "n_envs": (1, 32), "n_steps": (2, 8192),
              "batch_size": (2, 8192), "n_epochs": (1, 100), "checkpoint_steps": (1, 10_000_000),
              "eval_episodes": (1, 1000), "threads": (1, 32), "max_steps": (1, 10000)}
    for key, (low, high) in limits.items():
        if type(config.get(key)) is not int or not low <= config[key] <= high:
            raise ValueError(f"{key}は{low}～{high}の整数です。")
    if config["batch_size"] > config["n_envs"] * config["n_steps"]:
        raise ValueError("batch_sizeは環境数×ロールアウト手数以下にしてください。")
    for key, low, high in (("learning_rate", 1e-7, .1), ("gamma", .01, 1), ("ent_coef", 0, 1)):
        value = config.get(key)
        if type(value) not in (int, float) or not low <= value <= high:
            raise ValueError(f"{key}は{low}～{high}です。")
    hidden = config.get("hidden")
    if not isinstance(hidden, list) or not 1 <= len(hidden) <= 3 or any(type(n) is not int or not 1 <= n <= 128 for n in hidden):
        raise ValueError("隠れ層は1～3層、各層1～128ユニットです。")
    if type(config.get("eval_seed_start")) is not int or not 0 <= config["eval_seed_start"] <= 2**32 - config["eval_episodes"]:
        raise ValueError("検証seedの範囲が不正です。")
    if type(config.get("seed")) is not int or not 0 <= config["seed"] < 2**32:
        raise ValueError("学習seedの範囲が不正です。")
    if config.get("reward") not in ("log_score", "score", "score_potential"):
        raise ValueError("報酬方式が不正です。")
    if config.get("observation", OBSERVATION_ID) not in OBSERVATION_SIZES:
        raise ValueError("観測形式が不正です。")
    coefficient = config.get("shaping_coef", .2)
    if type(coefficient) not in (int, float) or not isfinite(coefficient) or not 0 <= coefficient <= 10:
        raise ValueError("補助報酬係数は0～10です。")


def train(config, output, *, resume=None, parent_metadata=None, reserved_seeds=(),
          stopped=lambda: False, progress_callback=lambda data: None, code_revision=None, code_sha256=None):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("出力先に既存の実験があります。別のディレクトリを指定してください。")
    output.mkdir(parents=True, exist_ok=True)
    validate_config(config)
    validation_seeds = list(range(config["eval_seed_start"], config["eval_seed_start"] + config["eval_episodes"]))
    parent_metadata = parent_metadata or {}
    inherited = set(parent_metadata.get("training_seeds", []))
    excluded = set(reserved_seeds) | set(validation_seeds) | inherited
    if inherited & set(validation_seeds):
        raise ValueError("親モデルの学習seedと定期検証seedが重複します。")
    torch.set_num_threads(config["threads"])
    environments = [DropNumberEnv(config["max_steps"], config["reward"], reserved_seeds=excluded,
                    observation_id=config.get("observation", OBSERVATION_ID), gamma=config["gamma"],
                    shaping_coef=config.get("shaping_coef", .2)) for _ in range(config["n_envs"])]
    vec = DummyVecEnv([lambda env=env: Monitor(env) for env in environments])
    started = perf_counter()
    class StopAfterUpdate(Exception):
        pass

    class ControlledPPO(PPO):
        def train(self):
            super().train()
            metrics = {key: float(value) for key, value in self.logger.name_to_value.items()
                       if key.startswith("train/") and isinstance(value, Real) and isfinite(value)}
            actions = self.rollout_buffer.actions.reshape(-1).astype(int)
            metrics["action_counts"] = [(actions == col).sum().item() for col in range(5)]
            row = {"timesteps": self.num_timesteps, "seconds": perf_counter() - started, "metrics": metrics}
            with (output / "updates.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, allow_nan=False) + "\n")
            progress_callback({**row, "phase": "更新完了"})
            if stopped():
                raise StopAfterUpdate()

    class Progress(BaseCallback):
        last = 0
        def _on_step(self):
            now = perf_counter()
            if now - self.last >= 1:
                self.last = now
                progress_callback({"timesteps": self.num_timesteps, "seconds": now - started, "phase": "学習"})
            return True

    model = ControlledPPO("MlpPolicy", vec, seed=config["seed"], device="cpu", verbose=0,
                n_steps=config["n_steps"], batch_size=config["batch_size"], n_epochs=config["n_epochs"],
                learning_rate=config["learning_rate"], gamma=config["gamma"], ent_coef=config["ent_coef"],
                policy_kwargs={"net_arch": {"pi": config["hidden"], "vf": config["hidden"]}, "activation_fn": torch.nn.Tanh})
    if resume:
        model = ControlledPPO.load(resume, env=vec, device="cpu")
        model.set_random_seed(config["seed"])
    initial_steps = model.num_timesteps
    target = initial_steps + config["timesteps"]
    emit = progress_callback
    progress_callback = lambda row: emit({"initial_timesteps":initial_steps, "target_timesteps":target, **row})
    metadata = {"config": config, "config_sha256": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
                "versions": {p: version(p) for p in ("gymnasium", "numpy", "torch", "stable-baselines3")},
                "validation_seeds": sorted(set(validation_seeds) | set(parent_metadata.get("validation_seeds", []))),
                "engine": __version__, "rules": asdict(Rules()), "code_revision": code_revision, "code_sha256":code_sha256,
                "parent": parent_metadata.get("model_id"), "initial_timesteps": initial_steps,
                "seed_history_known": parent_metadata.get("seed_history_known", True)}
    atomic_json(output / "config.json", metadata)
    progress = []
    best = -float("inf")
    try:
        while model.num_timesteps < target:
            amount = min(config["checkpoint_steps"], target - model.num_timesteps)
            try:
                model.learn(total_timesteps=amount, reset_num_timesteps=False, callback=Progress())
            except StopAfterUpdate:
                pass
            seen = sorted(inherited | set().union(*(env.seen_seeds for env in environments)))
            if set(seen) & set(validation_seeds):
                raise RuntimeError("学習seedと検証seedが重複しました。別の設定で実行してください。")
            metadata.update({"training_seeds": seen, "timesteps": model.num_timesteps})
            data = export_actor(model, metadata)
            stem = f"step-{model.num_timesteps}"
            temporary = output / f"{stem}.tmp.zip"
            model.save(temporary)
            replace(temporary, output / f"{stem}.zip")
            atomic_json(output / f"{stem}.json", data)
            shutil.copyfile(output / f"{stem}.zip", output / "latest.tmp.zip")
            replace(output / "latest.tmp.zip", output / "latest.zip")
            atomic_json(output / "latest.json", data)
            progress_callback({"timesteps": model.num_timesteps, "seconds": perf_counter() - started, "phase": "定期検証"})
            portable = Policy(data)
            report = evaluate(lambda seed: portable, validation_seeds, config["max_steps"], stopped=stopped,
                              on_episode=lambda index, row, session: progress_callback({"timesteps":model.num_timesteps,
                                  "seconds":perf_counter()-started,"phase":"定期検証","completed":index+1,"total":len(validation_seeds)}))
            row = {"timesteps": model.num_timesteps, "seconds": perf_counter() - started,
                   "validation_mean_score": report["mean_score"], "validation_mean_moves": report["mean_moves"],
                   "validation_complete": report["complete"], "checkpoint": stem}
            progress.append(row)
            print(json.dumps(row), flush=True)
            atomic_json(output / f"{stem}-validation.json", report)
            if report["complete"] and report["mean_score"] > best:
                best = report["mean_score"]
                shutil.copyfile(output / f"{stem}.zip", output / "best.tmp.zip")
                replace(output / "best.tmp.zip", output / "best.zip")
                atomic_json(output / "best.json", data)
                atomic_json(output / "validation.json", report)
            atomic_json(output / "progress.json", progress)
            if report["complete"] and not stopped() and not (output / "baselines.json").exists():
                progress_callback({"timesteps":model.num_timesteps,"seconds":perf_counter()-started,"phase":"比較基準の検証"})
                baselines={}
                for kind,factory in (("random",lambda seed:RandomAgent(seed ^ 0xA5A5A5A5)),("greedy",lambda seed:GreedyAgent())):
                    baselines[kind]=evaluate(factory,validation_seeds,config["max_steps"],stopped=stopped)
                if all(r["complete"] for r in baselines.values()):
                    atomic_json(output / "baselines.json",{"seeds":validation_seeds,"max_steps":config["max_steps"],"agents":baselines})
            progress_callback({**row, "phase": "保存完了", "initial_timesteps": initial_steps, "target_timesteps": target})
            if stopped():
                break
    finally:
        vec.close()
    return output / ("best.json" if (output / "best.json").exists() else "latest.json")
