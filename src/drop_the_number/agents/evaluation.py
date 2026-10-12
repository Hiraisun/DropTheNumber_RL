"""Same seeds, same engine, exact browser-compatible records for all agents."""

import json
from math import fsum, sqrt
from pathlib import Path
from time import perf_counter
from statistics import median

from drop_the_number.core import Game
from drop_the_number.replay import new_session


def episode(agent, seed, max_steps=1000):
    game = Game(seed)
    session = new_session(game, diagnostic=True)
    inference = 0.0
    while not game.over and len(session["actions"]) < max_steps:
        start = perf_counter()
        column = agent.choose(game)
        inference += perf_counter() - start
        result = game.step(column)
        if not result["accepted"]:
            raise RuntimeError("AIが不正な行動を選択しました。")
        session["actions"].append({"column": column, "source": "ai", "elapsed_ms": 0})
    session["final"] = game.snapshot()
    session["generated"] = game.generated.copy()
    metrics = {"seed": seed, "score": str(game.score), "merged_max": str(game.merged_max),
               "moves": game.moves, "terminated": game.over, "truncated": not game.over,
               "inference_ms_per_move": inference * 1000 / max(1, game.moves)}
    return metrics, session


def summarize(rows):
    if not rows:
        return {"episodes": [], "mean_score": None, "score_std": None, "median_score": None,
                "mean_moves": None, "max_merged": "0", "truncated_episodes": 0, "mean_inference_ms": None, "reach_rates": {},
                "score_15000_rate": None, "score_p10": None}
    scores = [int(row["score"]) for row in rows]
    mean = fsum(scores) / len(scores)
    ordered = sorted(scores)
    position = (len(ordered) - 1) * .1
    lower = int(position)
    p10 = ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * (position - lower)
    return {"episodes": rows, "mean_score": mean, "median_score": median(scores),
            "score_15000_rate": sum(score >= 15000 for score in scores) / len(scores), "score_p10": p10,
            "score_std": sqrt(fsum((s - mean) ** 2 for s in scores) / len(scores)),
            "mean_moves": fsum(row["moves"] for row in rows) / len(rows),
            "max_merged": str(max(int(row["merged_max"]) for row in rows)),
            "truncated_episodes": sum(row["truncated"] for row in rows),
            "mean_inference_ms": fsum(row["inference_ms_per_move"] for row in rows) / len(rows),
            "reach_rates": {str(n): sum(int(row["merged_max"]) >= n for row in rows) / len(rows)
                            for n in (128, 256, 512, 1024, 2048, 4096, 8192, 16384, 65536)}}


def evaluate(factory, seeds, max_steps=1000, replay_path=None, *, on_episode=None, stopped=lambda: False):
    rows = []
    for index, seed in enumerate(seeds):
        if stopped():
            break
        row, session = episode(factory(seed), seed, max_steps)
        rows.append(row)
        if on_episode:
            on_episode(index, row, session)
        if index == 0 and replay_path is not None:
            path = Path(replay_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(session, ensure_ascii=False), encoding="utf-8")
    return {**summarize(rows), "complete": len(rows) == len(seeds)}
