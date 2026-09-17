"""state.json: the cursor plus the ids already handled. Written atomically."""
import json
import os
from pathlib import Path

MAX_IDS = 5000
EMPTY = {"cursor": None, "processed_ids": []}


def load(path) -> dict:
    p = Path(path)
    if not p.exists():
        return dict(EMPTY, processed_ids=[])
    return json.loads(p.read_text())


def save(path, state) -> None:
    p = Path(path)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    os.replace(tmp, p)


def mark_processed(state, msg_id) -> None:
    ids = state["processed_ids"]
    if msg_id not in ids:
        ids.append(msg_id)
    del ids[:-MAX_IDS]


def is_processed(state, msg_id) -> bool:
    return msg_id in state["processed_ids"]
