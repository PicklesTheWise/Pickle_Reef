from __future__ import annotations

from datetime import datetime
from typing import Any, List

import logging

from ..schemas.spool_usage import SpoolUsageLog

logger = logging.getLogger(__name__)

DEFAULT_SPOOL_LENGTH_MM = 50_000
MAX_SPOOL_USAGE_ENTRIES = 5000
_spool_usage_log: List[SpoolUsageLog] = []


async def record_spool_usage_entry(
    module_id: str,
    delta_edges: float,
    delta_mm: float,
    total_used_edges: float,
    timestamp: datetime | None = None,
) -> None:
    entry = SpoolUsageLog(
        module_id=module_id,
        delta_edges=delta_edges,
        delta_mm=delta_mm,
        total_used_edges=total_used_edges,
        recorded_at=timestamp or datetime.utcnow(),
    )
    _spool_usage_log.append(entry)
    _prune_spool_usage_entries()


def derive_spool_usage_delta(
    module_id: str,
    previous_spool: dict[str, Any] | None,
    current_spool: dict[str, Any] | None,
    config_spool: dict[str, Any] | None,
) -> dict[str, float] | None:
    if not current_spool:
        return None

    full_edges = _resolve_numeric([current_spool, config_spool], "full_edges")
    if not full_edges or full_edges <= 0:
        return None

    total_length = _resolve_numeric(
        [current_spool, config_spool],
        ["total_length_mm", "length_mm"],
        fallback=DEFAULT_SPOOL_LENGTH_MM,
    )
    if not total_length or total_length <= 0:
        return None

    mm_per_edge = total_length / full_edges

    current_used = _resolve_used_edges(current_spool, full_edges)
    previous_used = _resolve_used_edges(previous_spool, full_edges) if previous_spool else None

    if current_used is None or previous_used is None:
        return None

    delta_edges = current_used - previous_used
    if delta_edges <= 0:
        return None

    delta_mm = delta_edges * mm_per_edge
    # Guard against implausible spikes (e.g., re-threading) by dropping deltas that exceed a full roll.
    if delta_mm > total_length:
        logger.debug("Skipping spool delta for %s exceeding total length", module_id)
        return None

    return {
        "delta_edges": float(delta_edges),
        "delta_mm": float(delta_mm),
        "total_used_edges": float(current_used),
    }


def get_spool_usage_entries(
    module_id: str | None = None,
    since: datetime | None = None,
    limit: int | None = None,
) -> list[SpoolUsageLog]:
    entries = _spool_usage_log
    if module_id:
        entries = [entry for entry in entries if entry.module_id == module_id]
    if since:
        entries = [entry for entry in entries if entry.recorded_at >= since]
    entries = sorted(entries, key=lambda entry: entry.recorded_at)
    if limit is not None:
        return entries[: max(0, limit)]
    return entries


def clear_spool_usage_for_module(module_id: str) -> int:
    """Remove spool usage rows associated with the module."""

    global _spool_usage_log
    before = len(_spool_usage_log)
    _spool_usage_log = [entry for entry in _spool_usage_log if entry.module_id != module_id]
    return before - len(_spool_usage_log)


def reset_spool_usage_entries() -> None:
    """Testing helper to clear the in-memory history."""

    _spool_usage_log.clear()


def _prune_spool_usage_entries() -> None:
    if len(_spool_usage_log) > MAX_SPOOL_USAGE_ENTRIES:
        del _spool_usage_log[:-MAX_SPOOL_USAGE_ENTRIES]


def _resolve_numeric(sources: list[dict[str, Any] | None], keys: str | list[str], fallback: float | None = None):
    if isinstance(keys, str):
        keys = [keys]
    for source in sources:
        if not source:
            continue
        for key in keys:
            value = source.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
    return fallback


def _resolve_used_edges(spool: dict[str, Any] | None, full_edges: float | None) -> float | None:
    if not spool:
        return None
    used = spool.get("used_edges")
    if isinstance(used, (int, float)) and not isinstance(used, bool):
        return float(used)
    remaining = spool.get("remaining_edges")
    if isinstance(remaining, (int, float)) and not isinstance(remaining, bool) and full_edges:
        return float(max(0.0, full_edges - remaining))
    return None
