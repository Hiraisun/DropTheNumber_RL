"""python -m drop_the_number.ai train/evaluate; optional dependencies are lazy."""

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .agents.baselines import GreedyAgent, RandomAgent
from .agents.evaluation import evaluate
from .agents.policy import Policy
from .core import Rules


def main():
    parser = argparse.ArgumentParser(description="Drop Number AI training and evaluation")
    sub = parser.add_subparsers(dest="command", required=True)
    training = sub.add_parser("train")
    training.add_argument("--config", default="configs/ppo.json")
    training.add_argument("--output", required=True)
    evaluation = sub.add_parser("evaluate")
    evaluation.add_argument("--model")
    evaluation.add_argument("--episodes", type=int, default=64)
    evaluation.add_argument("--seed-start", type=int, default=2000000000)
    evaluation.add_argument("--max-steps", type=int, default=1000)
    evaluation.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "train":
        from .agents.training import train
        print(train(json.loads(Path(args.config).read_text(encoding="utf-8")), args.output))
        return
    if not 1 <= args.episodes <= 10000 or not 1 <= args.max_steps <= 10000:
        parser.error("episodes/max-stepsは1～10000です。")
    if not 0 <= args.seed_start <= 2**32 - args.episodes:
        parser.error("seedは32ビット範囲内にしてください。")
    output = Path(args.output)
    if output.exists() and any(output.iterdir()):
        parser.error("評価の出力先は空のディレクトリを指定してください。")
    output.mkdir(parents=True, exist_ok=True)
    seeds = list(range(args.seed_start, args.seed_start + args.episodes))
    factories = {"random": lambda seed: RandomAgent(seed ^ 0xA5A5A5A5), "greedy": lambda seed: GreedyAgent()}
    report = {"engine": __version__, "rules": asdict(Rules()), "max_steps": args.max_steps, "seeds": seeds, "agents": {}}
    if args.model:
        model_bytes = Path(args.model).read_bytes()
        data = json.loads(model_bytes.decode("utf-8"))
        policy = Policy(data)
        excluded = set(data.get("metadata", {}).get("training_seeds", [])) | set(data.get("metadata", {}).get("validation_seeds", []))
        if excluded & set(seeds):
            parser.error("評価seedに学習または検証で使用したseedが含まれています。")
        factories["ppo"] = lambda seed: policy
        report["model_metadata"] = data.get("metadata", {})
        report["model_sha256"] = hashlib.sha256(model_bytes).hexdigest()
    for name, factory in factories.items():
        result = evaluate(factory, seeds, args.max_steps, output / f"{name}-replay.json")
        report["agents"][name] = result
        print(f"{name}: score={result['mean_score']:.1f}, moves={result['mean_moves']:.1f}, max={result['max_merged']}", flush=True)
    (output / "evaluation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
