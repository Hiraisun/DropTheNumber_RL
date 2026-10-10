"""Reference payload for CPython/Pyodide comparison; no browser involved."""

import json
from pathlib import Path

from drop_the_number.bridge import dispatch

root = Path(__file__).resolve().parents[1]
fixtures = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((root / "tests/fixtures").rglob("*.json"))]
request = {"command": "fixtures", "fixtures": fixtures}
print(json.dumps({"request": request, "results": json.loads(dispatch(json.dumps(request)))}))
