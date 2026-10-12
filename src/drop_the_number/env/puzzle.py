"""Turn-based Gymnasium adapter around the unchanged game engine."""

from math import log2, isfinite

import gymnasium as gym
import numpy as np

from drop_the_number.agents.observation import OBSERVATION_ID, OBSERVATION_SIZES, observation, board_potential
from drop_the_number.core import Game


class DropNumberEnv(gym.Env):
    metadata = {"render_modes": ["ansi"]}

    def __init__(self, max_steps=1000, reward="log_score", render_mode=None, reserved_seeds=(),
                 observation_id=OBSERVATION_ID, gamma=.995, shaping_coef=.2):
        if type(max_steps) is not int or not 1 <= max_steps <= 10000:
            raise ValueError("max_stepsは1～10000です。")
        if reward not in ("log_score", "score", "score_potential") or render_mode not in (None, "ansi"):
            raise ValueError("報酬・描画設定が不正です。")
        if observation_id not in OBSERVATION_SIZES:
            raise ValueError("観測形式が不正です。")
        if any(type(v) not in (int, float) or not isfinite(v) for v in (gamma, shaping_coef)) or not .01 <= gamma <= 1 or not 0 <= shaping_coef <= 10:
            raise ValueError("割引率・補助報酬係数が不正です。")
        self.observation_id, self.gamma, self.shaping_coef = observation_id, gamma, shaping_coef
        self.max_steps, self.reward_mode, self.render_mode = max_steps, reward, render_mode
        self.action_space = gym.spaces.Discrete(5)
        self.observation_space = gym.spaces.Box(0, np.inf, (OBSERVATION_SIZES[observation_id],), np.float32)
        self.game = None
        self.finished = True
        self.steps = 0
        self.seen_seeds = set()
        self.reserved_seeds = set(reserved_seeds)

    def _observation(self):
        return np.asarray(observation(self.game, self.observation_id), dtype=np.float32)

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
        potential_before = board_potential(self.game) if self.reward_mode == "score_potential" else 0
        result = self.game.step(int(action))
        if not result["accepted"]:
            raise RuntimeError(result["reason"])
        delta = int(result["score_delta"])
        reward = log2(1 + delta) / 16 if self.reward_mode == "log_score" else delta / 256
        shaping = self.shaping_coef * (self.gamma * board_potential(self.game) - potential_before) if self.reward_mode == "score_potential" else 0
        reward += shaping
        self.steps += 1
        terminated = self.game.over
        truncated = self.steps >= self.max_steps and not terminated
        self.finished = terminated or truncated
        return self._observation(), reward, terminated, truncated, {**self._info(), "score_delta": delta, "shaping_reward": shaping}

    def render(self):
        return "\n".join(" ".join(str(n).rjust(6) if n else "     ." for n in row) for row in self.game.board)
