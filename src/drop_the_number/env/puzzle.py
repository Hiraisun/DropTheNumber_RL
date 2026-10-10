"""Turn-based Gymnasium adapter around the unchanged game engine."""

from math import log2

import gymnasium as gym
import numpy as np

from drop_the_number.agents.observation import OBSERVATION_SIZE, observation
from drop_the_number.core import Game


class DropNumberEnv(gym.Env):
    metadata = {"render_modes": ["ansi"]}

    def __init__(self, max_steps=1000, reward="log_score", render_mode=None, reserved_seeds=()):
        if type(max_steps) is not int or not 1 <= max_steps <= 10000:
            raise ValueError("max_stepsは1～10000です。")
        if reward not in ("log_score", "score") or render_mode not in (None, "ansi"):
            raise ValueError("報酬・描画設定が不正です。")
        self.max_steps, self.reward_mode, self.render_mode = max_steps, reward, render_mode
        self.action_space = gym.spaces.Discrete(5)
        self.observation_space = gym.spaces.Box(0, np.inf, (OBSERVATION_SIZE,), np.float32)
        self.game = None
        self.finished = True
        self.steps = 0
        self.seen_seeds = set()
        self.reserved_seeds = set(reserved_seeds)

    def _observation(self):
        return np.asarray(observation(self.game), dtype=np.float32)

    def _info(self):
        return {"score": self.game.score, "merged_max": self.game.merged_max,
                "moves": self.game.moves, "game_seed": self.game.seed,
                "rules": self.game.rules.id, "auto_drop": False}

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        game_seed = int(seed) if seed is not None else int(self.np_random.integers(0, 2**32))
        while game_seed in self.reserved_seeds:
            game_seed = int(self.np_random.integers(0, 2**32))
        self.game = Game.from_snapshot(options["snapshot"]) if options and "snapshot" in options else Game(game_seed)
        if self.game.over:
            raise ValueError("学習の初期盤面は未終了の状態にしてください。")
        self.seen_seeds.add(self.game.seed)
        self.finished, self.steps = False, 0
        return self._observation(), self._info()

    def step(self, action):
        if self.finished:
            raise RuntimeError("resetしてからstepを実行してください。")
        if isinstance(action, (bool, np.bool_)) or not self.action_space.contains(action):
            raise ValueError("行動は0～4の整数です。")
        result = self.game.step(int(action))
        if not result["accepted"]:
            raise RuntimeError(result["reason"])
        delta = int(result["score_delta"])
        reward = log2(1 + delta) / 16 if self.reward_mode == "log_score" else delta / 256
        self.steps += 1
        terminated = self.game.over
        truncated = self.steps >= self.max_steps and not terminated
        self.finished = terminated or truncated
        return self._observation(), reward, terminated, truncated, {**self._info(), "score_delta": delta}

    def render(self):
        return "\n".join(" ".join(str(n).rjust(6) if n else "     ." for n in row) for row in self.game.board)
