"""Comparison agents. Never use the game's random state or hidden preview."""

from dataclasses import asdict
from math import log2
from random import Random

from drop_the_number.core import Game


class RandomAgent:
    def __init__(self, seed=0):
        self.random = Random(seed)

    def choose(self, game):
        if game.over:
            raise ValueError("終了したゲームではAIは操作できません。")
        return self.random.randrange(5)


class GreedyAgent:
    def choose(self, game):
        if game.over:
            raise ValueError("終了したゲームではAIは操作できません。")
        ranks = []
        for col in range(5):
            # Rebuild from visible data, with a separate dummy RNG. The new
            # preview is generated but is never used to rank a move.
            trial = Game.from_snapshot({
                "rules": asdict(game.rules), "board": game._wire_board(),
                "current": str(game.current), "next": str(game.next),
                "merged_max": str(game.merged_max), "seed": 1,
            })
            result = trial.step(col)
            heights = [sum(bool(row[c]) for row in trial.board) for c in range(5)]
            roughness = sum(abs(a - b) for a, b in zip(heights, heights[1:]))
            score = log2(1 + int(result["score_delta"])) + .7 * (30 - sum(heights))
            score -= 2 * max(heights) + .3 * roughness
            ranks.append((not trial.over, score, -col))
        return max(range(5), key=lambda col: ranks[col])
