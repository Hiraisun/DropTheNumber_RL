"""Optional local-only Torch/SB3 training and portable actor export."""

import hashlib
import json
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

import torch
from stable_baselines3 import PPO
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import DummyVecEnv

from drop_the_number import __version__
from drop_the_number.core import Rules
from drop_the_number.env import DropNumberEnv
from .evaluation import evaluate
from .observation import OBSERVATION_ID
from .policy import POLICY_SCHEMA, Policy


def export_actor(model, metadata=None):
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
            "observation": OBSERVATION_ID, "name": f"PPO / {model.num_timesteps:,}手",
            "metadata": metadata or {}, "layers": layers}
    Policy(data)
    return data


def train(config, output):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("出力先に既存の実験があります。別のディレクトリを指定してください。")
    output.mkdir(parents=True, exist_ok=True)
    if config.get("schema") != "drop-number/train-v1" or config.get("algorithm") != "ppo":
        raise ValueError("学習設定の形式・アルゴリズムが不正です。")
    integers = ("timesteps", "n_envs", "n_steps", "batch_size", "n_epochs", "checkpoint_steps", "eval_episodes", "threads")
    if any(type(config.get(k)) is not int or config[k] < 1 for k in integers):
        raise ValueError("学習設定の回数は正の整数です。")
    if config["n_steps"] * config["n_envs"] < 2:
        raise ValueError("ロールアウトは2手以上必要です。")
    hidden = config.get("hidden")
    if not isinstance(hidden, list) or not 1 <= len(hidden) <= 3 or any(type(n) is not int or not 1 <= n <= 128 for n in hidden):
        raise ValueError("隠れ層は1～3層、各層1～128ユニットです。")
    if type(config.get("eval_seed_start")) is not int or not 0 <= config["eval_seed_start"] <= 2**32 - config["eval_episodes"]:
        raise ValueError("検証seedの範囲が不正です。")
    if type(config.get("seed")) is not int or not 0 <= config["seed"] < 2**32:
        raise ValueError("学習seedの範囲が不正です。")
    torch.set_num_threads(config["threads"])
    environments = [DropNumberEnv(config["max_steps"], config["reward"]) for _ in range(config["n_envs"])]
    vec = DummyVecEnv([lambda env=env: Monitor(env) for env in environments])
    model = PPO("MlpPolicy", vec, seed=config["seed"], device="cpu", verbose=0,
                n_steps=config["n_steps"], batch_size=config["batch_size"], n_epochs=config["n_epochs"],
                learning_rate=config["learning_rate"], gamma=config["gamma"], ent_coef=config["ent_coef"],
                policy_kwargs={"net_arch": {"pi": config["hidden"], "vf": config["hidden"]}, "activation_fn": torch.nn.Tanh})
    validation_seeds = list(range(config["eval_seed_start"], config["eval_seed_start"] + config["eval_episodes"]))
    metadata = {"config": config, "config_sha256": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
                "versions": {p: version(p) for p in ("gymnasium", "numpy", "torch", "stable-baselines3")},
                "validation_seeds": validation_seeds, "engine": __version__, "rules": asdict(Rules())}
    (output / "config.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    progress = []
    best = -float("inf")
    started = perf_counter()
    try:
        while model.num_timesteps < config["timesteps"]:
            amount = min(config["checkpoint_steps"], config["timesteps"] - model.num_timesteps)
            model.learn(total_timesteps=amount, reset_num_timesteps=False)
            seen = sorted(set().union(*(env.seen_seeds for env in environments)))
            if set(seen) & set(validation_seeds):
                raise RuntimeError("学習seedと検証seedが重複しました。別の設定で実行してください。")
            metadata.update({"training_seeds": seen, "timesteps": model.num_timesteps})
            data = export_actor(model, metadata)
            portable = Policy(data)
            report = evaluate(lambda seed: portable, validation_seeds, config["max_steps"])
            row = {"timesteps": model.num_timesteps, "seconds": perf_counter() - started,
                   "validation_mean_score": report["mean_score"], "validation_mean_moves": report["mean_moves"]}
            progress.append(row)
            print(json.dumps(row), flush=True)
            model.save(output / "latest.zip")
            (output / "latest.json").write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
            if report["mean_score"] > best:
                best = report["mean_score"]
                model.save(output / "best.zip")
                (output / "best.json").write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
                (output / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            (output / "progress.json").write_text(json.dumps(progress, indent=2), encoding="utf-8")
    finally:
        vec.close()
    return output / "best.json"
