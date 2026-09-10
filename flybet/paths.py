import hashlib
import json
import os
from pathlib import Path


def data_root():
    return Path(os.environ.get("FLYBET_DATA", "data/malecns-v1.0")).resolve()


def runs_root():
    return Path(os.environ.get("FLYBET_RUNS", "runs")).resolve()


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    tmp.replace(path)
