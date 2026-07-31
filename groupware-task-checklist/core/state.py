"""완료 체크한 항목을 로컬 JSON에 저장해서, 다음 실행 때는 팝업에 안 뜨게 한다."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List

from .models import Task

DEFAULT_STATE_PATH = Path(__file__).resolve().parent.parent / ".state" / "task_state.json"


def load_state(path: Path = DEFAULT_STATE_PATH) -> Dict[str, dict]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state: Dict[str, dict], path: Path = DEFAULT_STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def apply_state(tasks: List[Task], state: Dict[str, dict], today: date) -> List[Task]:
    """이전에 완료 처리된 task는 목록에서 제외하고, 나머지는 state에 최초/최종 발견일을 기록한다."""
    remaining = []
    for t in tasks:
        entry = state.get(t.id)
        if entry and entry.get("done"):
            continue
        if entry is None:
            state[t.id] = {"first_seen": today.isoformat(), "done": False}
        state[t.id]["last_seen"] = today.isoformat()
        state[t.id]["title"] = t.title
        state[t.id]["due_date"] = t.due_date.isoformat() if t.due_date else None
        remaining.append(t)
    return remaining


def mark_done(task_ids: List[str], state: Dict[str, dict], today: date) -> None:
    for tid in task_ids:
        state.setdefault(tid, {})
        state[tid]["done"] = True
        state[tid]["done_at"] = today.isoformat()
