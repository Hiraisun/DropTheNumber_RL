"""String-in/string-out API used by the module worker and parity tests."""

import json
from copy import deepcopy

from .core import Game
from .replay import new_session, reconstruct

_game = None
_session = None


def dispatch(raw):
    global _game, _session
    request = json.loads(raw)
    command = request["command"]
    if command == "new":
        game = Game(seed=request.get("seed", 1))
        session = new_session(game, request.get("auto_drop", False))
        _game, _session = game, session
        result = {"state": _game.snapshot(), "events": []}
    elif command == "diagnostic":
        game = Game.from_snapshot(request["state"])
        _game, _session = game, new_session(game, diagnostic=True)
        result = {"state": _game.snapshot(), "events": []}
    elif command == "import":
        game, session = reconstruct(request["session"])
        _game, _session = game, session
        result = {"state": _game.snapshot(), "events": [], "settings": session["settings"]}
    elif command == "fixtures":
        results = []
        for fixture in request["fixtures"]:
            game = Game.from_snapshot(fixture["initial"])
            result = game.step(fixture["column"])
            results.append({"id": fixture["id"], "result": result})
        return json.dumps(results)
    else:
        if _game is None:
            raise ValueError("ゲームを先に初期化してください。")
        if command == "step":
            if len(_session["actions"]) >= 10000:
                raise ValueError("試作版の記録上限10000手に達しました。新しいゲームを開始してください。")
            result = _game.step(request["column"])
            if result["accepted"]:
                _session["actions"].append({"column": request["column"],
                    "source": request.get("source", "manual"), "elapsed_ms": request.get("elapsed_ms", 0)})
        elif command == "settings":
            automatic = request["auto_drop"]
            if type(automatic) is not bool:
                raise ValueError("自然落下設定が不正です。")
            _session["settings"]["auto_drop"] = automatic
            result = {"state": _game.snapshot(), "events": []}
        elif command == "export":
            result = deepcopy(_session)
            result["final"] = _game.snapshot()
            result["generated"] = _game.generated.copy()
            return json.dumps(result)
        else:
            raise ValueError("未対応の操作です。")
    result["diagnostic"] = _session["diagnostic"]
    return json.dumps(result)
