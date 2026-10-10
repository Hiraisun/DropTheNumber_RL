"""A single trusted job. No HTTP server or user-supplied commands run here."""
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .manager import write as atomic_json
from drop_the_number import __version__
from drop_the_number.core import Rules


def run(directory):
    directory = Path(directory)
    job = json.loads((directory / "job.json").read_text(encoding="utf-8"))
    stopped = lambda: (directory / "stop").exists()
    progress = lambda row: atomic_json(directory / "status.json", row)
    if job["kind"] == "train":
        from drop_the_number.agents.training import train
        parent = job.get("parent") or {}
        train(job["config"], directory / "training", resume=parent.get("zip"),
              parent_metadata=parent.get("metadata"), reserved_seeds=job["reserved_seeds"],
              stopped=stopped, progress_callback=progress, code_revision=job["code_revision"],code_sha256=job.get("code_sha256"))
    elif job["kind"] == "evaluate":
        from drop_the_number.agents.baselines import RandomAgent, GreedyAgent
        from drop_the_number.agents.policy import Policy
        from drop_the_number.agents.evaluation import evaluate
        reports = {}
        condition = job["condition"]
        seeds = condition["seeds"]
        agents = job["agents"]
        completed = 0
        for item in agents:
            key = item["id"]
            if item.get("path"):
                policy = Policy(json.loads(Path(item["path"]).read_text(encoding="utf-8")))
                factory = lambda seed, policy=policy: policy
            elif key == "random":
                factory = lambda seed: RandomAgent(seed ^ 0xA5A5A5A5)
            else:
                factory = lambda seed: GreedyAgent()
            def on_episode(index, row, session):
                nonlocal completed
                atomic_json(directory / f"replay-{key}-{index}.json", session)
                completed += 1
                progress({"phase": "検証", "completed": completed, "total": len(seeds) * len(agents), "agent": item["name"]})
            report = evaluate(factory, seeds, condition["max_steps"], on_episode=on_episode, stopped=stopped)
            report.update({"name": item["name"], "model_sha256": item.get("sha256"),
                           "seed_history_known": item.get("seed_history_known", True),
                           "overlapping_seeds": item.get("overlapping_seeds", [])})
            if report["episodes"]:
                ordered = sorted(enumerate(report["episodes"]), key=lambda pair: int(pair[1]["score"]))
                report["representatives"] = {"worst": ordered[0][0], "median": ordered[len(ordered)//2][0], "best": ordered[-1][0]}
            reports[key] = report
            atomic_json(directory / "evaluation.json", {"schema":"drop-number/evaluation-v1", "engine":__version__,
                         "rules":asdict(Rules()), "deterministic":True, "condition": condition, "agents": reports,
                         "complete": len(reports) == len(agents) and all(r["complete"] for r in reports.values())})
            if stopped():
                break
    else:
        raise ValueError("不明なジョブです。")
    atomic_json(directory / "result.json", {"status": "stopped" if stopped() else "completed"})


if __name__ == "__main__":
    try:
        run(sys.argv[1])
    except Exception as error:
        import traceback
        traceback.print_exc()
        atomic_json(Path(sys.argv[1]) / "result.json", {"status": "failed", "error": str(error)})
        sys.exit(1)
