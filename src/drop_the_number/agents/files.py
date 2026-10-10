"""Atomic local artifact writes, including transient Windows sharing conflicts."""
import json
import os
import time
from pathlib import Path


def replace(source, destination):
    for attempt in range(21):
        try:
            os.replace(source, destination)
            return
        except PermissionError as error:
            if os.name != "nt" or getattr(error,"winerror",None) not in (5,32) or attempt==20:
                raise
            time.sleep(.05)


def atomic_json(path, data):
    path=Path(path)
    temporary=path.with_suffix(path.suffix+".tmp")
    temporary.write_text(json.dumps(data,ensure_ascii=False,allow_nan=False),encoding="utf-8")
    replace(temporary,path)
