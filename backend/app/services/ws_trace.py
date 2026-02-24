from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Any

MAX_TRACE_ENTRIES = 500
_ws_trace_log: deque[dict[str, Any]] = deque(maxlen=MAX_TRACE_ENTRIES)


def record_ws_trace(direction: str, payload: dict[str, Any], module_id: str | None = None) -> None:
    entry = {
        "timestamp": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
        "direction": direction,
        "module_id": module_id,
        "payload": payload,
    }
    _ws_trace_log.appendleft(entry)


def get_ws_trace(limit: int | None = None) -> list[dict[str, Any]]:
    entries = list(_ws_trace_log)
    if limit is not None:
        return entries[:limit]
    return entries


def clear_ws_trace() -> None:
    _ws_trace_log.clear()
