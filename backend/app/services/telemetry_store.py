from __future__ import annotations

from datetime import datetime
from typing import Dict, List

from ..schemas.telemetry import Telemetry

MAX_TELEMETRY_RECORDS = 2000
_telemetry_log: List[Telemetry] = []


def record_telemetry_entry(entry: Telemetry) -> Telemetry:
    """Store a telemetry sample in memory."""

    _telemetry_log.append(entry)
    if len(_telemetry_log) > MAX_TELEMETRY_RECORDS:
        del _telemetry_log[:-MAX_TELEMETRY_RECORDS]
    return entry


def list_telemetry_entries(limit: int | None = None) -> List[Telemetry]:
    """Return telemetry samples ordered from newest to oldest."""

    records = sorted(_telemetry_log, key=lambda row: row.captured_at, reverse=True)
    if limit is not None:
        return records[:limit]
    return records


def summarize_telemetry_entries() -> List[dict[str, object]]:
    """Produce simple aggregates for each metric."""

    buckets: Dict[str, dict[str, object]] = {}
    for row in _telemetry_log:
        bucket = buckets.setdefault(
            row.metric,
            {"total": 0.0, "count": 0, "last_seen": datetime.min},
        )
        bucket["total"] = float(bucket["total"]) + float(row.value)
        bucket["count"] = int(bucket["count"]) + 1
        if row.captured_at and row.captured_at > bucket["last_seen"]:
            bucket["last_seen"] = row.captured_at

    summary: List[dict[str, object]] = []
    for metric, bucket in buckets.items():
        count = bucket["count"] or 1
        avg_value = float(bucket["total"]) / count
        summary.append(
            {
                "metric": metric,
                "avg_value": avg_value,
                "last_seen": bucket["last_seen"],
            }
        )
    return summary


def clear_telemetry_entries() -> None:
    """Helper for tests to reset the in-memory log."""

    _telemetry_log.clear()
