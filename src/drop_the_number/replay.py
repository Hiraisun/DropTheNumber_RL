"""Validated session export and deterministic reconstruction."""

from copy import deepcopy

from .core.game import Game, MAX_IMPORT_MOVES, SCHEMA


def new_session(game, auto_drop=False, interval_ms=3500, diagnostic=False):
    return {"schema": SCHEMA, "initial": game.snapshot(), "actions": [],
            "settings": {"auto_drop": auto_drop, "interval_ms": interval_ms},
            "diagnostic": diagnostic}


def reconstruct(data):
    if data.get("schema") != SCHEMA:
        raise ValueError("対応していない保存・リプレイ形式です。")
    actions = data.get("actions", [])
    if not isinstance(actions, list) or len(actions) > MAX_IMPORT_MOVES:
        raise ValueError("操作列が不正または長すぎます。")
    game = Game.from_snapshot(data["initial"])
    for action in actions:
        result = game.step(action["column"])
        if not result["accepted"]:
            raise ValueError("リプレイに受理できない操作が含まれています。")
    if "final" in data and game.snapshot() != data["final"]:
        raise ValueError("リプレイの最終状態が一致しません。ルール版・データを確認してください。")
    settings = data.get("settings", {})
    automatic = settings.get("auto_drop", False)
    interval = settings.get("interval_ms", 3500)
    if type(automatic) is not bool or type(interval) is not int or interval != 3500:
        raise ValueError("この版の自然落下設定は3500msに固定されています。")
    session = new_session(Game.from_snapshot(data["initial"]), automatic, interval,
                          bool(data.get("diagnostic", False)))
    session["actions"] = deepcopy(actions)
    return game, session
