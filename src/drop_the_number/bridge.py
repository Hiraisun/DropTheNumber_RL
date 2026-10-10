"""String-in/string-out API used by the module worker and parity tests."""

import json
from copy import deepcopy

from .core import Game
from .agents.baselines import GreedyAgent, RandomAgent
from .agents.policy import Policy
from .replay import new_session, reconstruct

_game = None
_session = None
_policy = None
_random = RandomAgent()


def dispatch(raw):
    global _game, _session, _policy, _random
    request = json.loads(raw)
    command = request["command"]
    if command == "load-policy":
        policy = Policy(request["policy"])
        _policy = policy
        return json.dumps({"name": policy.name})
    if command == "new":
        game = Game(seed=request.get("seed", 1))
        session = new_session(game, request.get("auto_drop", False), diagnostic=request.get("diagnostic", False))
        _random = RandomAgent(game.seed ^ 0xA5A5A5A5)
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
        if command == "ai-action":
            kind = request["agent"]
            agent = {"random": _random, "greedy": GreedyAgent(), "ppo": _policy}.get(kind)
            if agent is None:
                raise ValueError("AIモデルを先に読み込んでください。")
            return json.dumps({"column": agent.choose(_game)})
        elif command == "step":
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
