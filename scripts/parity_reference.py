"""Reference payload for CPython/Pyodide comparison; no browser involved."""

import json
from pathlib import Path

from drop_the_number.bridge import dispatch

root = Path(__file__).resolve().parents[1]
fixtures = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((root / "tests/fixtures").rglob("*.json"))]
request = {"command": "fixtures", "fixtures": fixtures}
calls = []
def record(request):
    calls.append({"request": request, "result": json.loads(dispatch(json.dumps(request)))})

record(request)
policy_data = json.loads((root / "web/public/ai/ppo.json").read_text(encoding="utf-8"))
record({"command": "load-policy", "policy": policy_data})
record({"command": "new", "seed": 2_000_000_000, "diagnostic": True})
for _ in range(40):
    choice = json.loads(dispatch(json.dumps({"command": "ai-action", "agent": "ppo"})))
    record({"command": "ai-action", "agent": "ppo"})
    record({"command": "ai-action", "agent": "greedy"})
    record({"command": "ai-action", "agent": "random"})
    record({"command": "step", "column": choice["column"], "source": "ai"})
    if calls[-1]["result"]["state"]["over"]: break
record({"command": "export"})
session = calls[-1]["result"]
for index in (0, 1, len(session["actions"]) // 2, len(session["actions"])):
    record({"command": "seek", "session": session, "index": index})
# Exercise relational inputs in the browser without distributing a Torch model.
relational = {**policy_data, "observation":"relations-v2", "layers":[
    {"weights":[[(r-c)/512 for c in range(178)] for r in range(5)],
     "biases":[0,.1,-.2,.3,-.4], "activation":"linear"}]}
record({"command":"load-policy","policy":relational})
record({"command":"new","seed":2_100_000_123,"diagnostic":True})
for _ in range(20):
    choice = json.loads(dispatch(json.dumps({"command":"ai-action","agent":"ppo"})))
    record({"command":"ai-action","agent":"ppo"})
    record({"command":"step","column":choice["column"],"source":"ai"})
    if calls[-1]["result"]["state"]["over"]:
        break
print(json.dumps(calls))
