from __future__ import annotations

from datetime import datetime
from typing import Any, List

from ..schemas.cycle import CycleLog

MAX_CYCLE_LOG_ENTRIES = 2000
_cycle_logs: List[CycleLog] = []


async def record_cycle_log(payload: dict[str, Any]) -> CycleLog:
    """Persist an incoming cycle_log frame from a hardware module."""

    module_id = payload.get("module") or "unknown"
    log = CycleLog(
        module_id=module_id,
        cycle_type=payload.get("cycle_type") or "unknown",
        trigger=payload.get("trigger"),
        duration_ms=payload.get("duration_ms"),
        timeout=bool(payload.get("timeout", False)),
        module_timestamp_s=payload.get("timestamp_s"),
        recorded_at=datetime.utcnow(),
    )

    _cycle_logs.append(log)
    _prune_cycle_logs()
    return log


def get_cycle_logs_since(timestamp: datetime) -> List[CycleLog]:
    return [log for log in _cycle_logs if log.recorded_at >= timestamp]


def add_cycle_log_entry(entry: CycleLog) -> None:
    """Testing helper to append a preconstructed entry."""

    _cycle_logs.append(entry)
    _prune_cycle_logs()


def clear_cycle_logs() -> None:
    _cycle_logs.clear()


def _prune_cycle_logs() -> None:
    if len(_cycle_logs) > MAX_CYCLE_LOG_ENTRIES:
        del _cycle_logs[:-MAX_CYCLE_LOG_ENTRIES]
