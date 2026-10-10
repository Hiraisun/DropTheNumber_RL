"""Portable feed-forward PPO actor. No NumPy, Torch, or executable model files."""

from dataclasses import asdict
from math import fsum, isfinite, tanh

from drop_the_number import __version__
from drop_the_number.core import Rules
from .observation import OBSERVATION_ID, OBSERVATION_SIZE, observation

POLICY_SCHEMA = "drop-number/policy-v1"


class Policy:
    def __init__(self, data):
        if data.get("schema") != POLICY_SCHEMA or data.get("engine") != __version__:
            raise ValueError("対応していないAIモデル形式・エンジン版です。")
        if data.get("observation") != OBSERVATION_ID:
            raise ValueError("AIの観測形式が一致しません。")
        self.rules = asdict(Rules(**data["rules"]))
        layers = data.get("layers")
        if not isinstance(layers, list) or not 1 <= len(layers) <= 4:
            raise ValueError("AIの層数が不正です。")
        inputs = OBSERVATION_SIZE
        self.layers = []
        for index, layer in enumerate(layers):
            weights, biases = layer["weights"], layer["biases"]
            activation = "linear" if index == len(layers) - 1 else "tanh"
            if layer.get("activation") != activation or not 1 <= len(biases) <= 128:
                raise ValueError("AIの層・活性化関数が不正です。")
            if len(weights) != len(biases) or any(len(row) != inputs for row in weights):
                raise ValueError("AIの重みのサイズが不正です。")
            if any(type(n) not in (int, float) or not isfinite(n) or abs(n) > 1e6
                   for n in [*biases, *(n for row in weights for n in row)]):
                raise ValueError("AIの重みは有限の数値で指定してください。")
            self.layers.append((weights, biases, activation))
            inputs = len(biases)
        if inputs != 5:
            raise ValueError("AIの出力は5列で指定してください。")
        self.name = str(data.get("name", "PPO"))[:80]

    def logits(self, game):
        if asdict(game.rules) != self.rules:
            raise ValueError("AIの学習ルールとゲームのルールが一致しません。")
        values = observation(game)
        for weights, biases, activation in self.layers:
            values = [b + fsum(w * x for w, x in zip(row, values))
                      for row, b in zip(weights, biases)]
            if activation == "tanh":
                values = [tanh(n) for n in values]
        return values

    def choose(self, game):
        if game.over:
            raise ValueError("終了したゲームではAIは操作できません。")
        logits = self.logits(game)
        return max(range(5), key=lambda col: logits[col])
