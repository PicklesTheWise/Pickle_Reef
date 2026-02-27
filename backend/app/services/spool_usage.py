from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import logging
from sqlalchemy import delete, func
from sqlmodel import select

from ..db.session import get_session
from ..schemas.spool_usage import SpoolUsageLog
from .module_identity import resolve_module_id
from .ws_trace import MAX_TRACE_ENTRIES, get_ws_trace

logger = logging.getLogger(__name__)

DEFAULT_SPOOL_LENGTH_MM = 50_000
MAX_SPOOL_USAGE_ENTRIES = 5000
TRACE_REHYDRATE_WINDOW_HOURS = 30 * 24


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
    async with get_session() as session:
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
        await _prune_spool_usage_entries(session)
    return entry


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


async def get_spool_usage_entries(
    module_id: str | None = None,
    since: datetime | None = None,
    limit: int | None = None,
) -> list[SpoolUsageLog]:
    statement = select(SpoolUsageLog)
    if module_id:
        statement = statement.where(SpoolUsageLog.module_id == module_id)
    if since:
        statement = statement.where(SpoolUsageLog.recorded_at >= since)
    statement = statement.order_by(SpoolUsageLog.recorded_at, SpoolUsageLog.id)
    if limit is not None:
        statement = statement.limit(max(1, limit))

    async with get_session() as session:
        result = await session.exec(statement)
        return result.all()


async def clear_spool_usage_for_module(module_id: str) -> int:
    """Remove spool usage rows associated with the module."""

    async with get_session() as session:
        result = await session.exec(delete(SpoolUsageLog).where(SpoolUsageLog.module_id == module_id))
        await session.commit()
        return result.rowcount or 0


async def reset_spool_usage_entries() -> None:
    """Testing helper to clear the persisted history."""

    async with get_session() as session:
        await session.exec(delete(SpoolUsageLog))
        await session.commit()


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    elif "+" not in normalized and "-" not in normalized[10:]:
        normalized = f"{normalized}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


async def rehydrate_spool_usage_history(window_hours: int = TRACE_REHYDRATE_WINDOW_HOURS) -> int:
    """Replay historical ws_trace status frames to rebuild usage history after restarts."""

    async with get_session() as session:
        count_result = await session.exec(select(func.count()).select_from(SpoolUsageLog))
        existing_rows = count_result.one()
        if existing_rows:
            return 0

    rows = get_ws_trace(limit=MAX_TRACE_ENTRIES)
    if not rows:
        logger.info("No ws_trace rows available for spool usage rehydration")
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    snapshots: Dict[str, dict[str, Any]] = {}
    rebuilt: List[SpoolUsageLog] = []

    for entry in reversed(rows):
        if entry.get("direction") != "rx":
            continue
        payload = entry.get("payload") or {}
        if (payload.get("type") or "").lower() != "status":
            continue
        spool = payload.get("spool")
        if not isinstance(spool, dict):
            continue
        timestamp = _parse_timestamp(entry.get("timestamp"))
        if timestamp is None or timestamp < cutoff:
            continue
        module_id = entry.get("module_id") or resolve_module_id(payload)
        if not module_id or module_id == "unknown":
            continue
        previous = snapshots.get(module_id)
        delta = derive_spool_usage_delta(module_id, previous, spool, None)
        if delta:
            rebuilt.append(
                SpoolUsageLog(
                    module_id=module_id,
                    delta_edges=delta["delta_edges"],
                    delta_mm=delta["delta_mm"],
                    total_used_edges=delta["total_used_edges"],
                    recorded_at=timestamp,
                )
            )
        snapshots[module_id] = dict(spool)

    if not rebuilt:
        logger.info("No spool usage deltas found in ws_trace history")
        return 0

    rebuilt.sort(key=lambda entry: entry.recorded_at)
    if len(rebuilt) > MAX_SPOOL_USAGE_ENTRIES:
        rebuilt = rebuilt[-MAX_SPOOL_USAGE_ENTRIES:]

    async with get_session() as session:
        session.add_all(rebuilt)
        await session.commit()
        await _prune_spool_usage_entries(session)

    logger.info("Rehydrated %s spool usage entries from ws_trace", len(rebuilt))
    return len(rebuilt)


async def _prune_spool_usage_entries(session) -> None:
    count_result = await session.exec(select(func.count()).select_from(SpoolUsageLog))
    total = count_result.one()
    if total <= MAX_SPOOL_USAGE_ENTRIES:
        return

    offset = MAX_SPOOL_USAGE_ENTRIES
    stale_ids_result = await session.exec(
        select(SpoolUsageLog.id)
        .order_by(SpoolUsageLog.recorded_at.desc(), SpoolUsageLog.id.desc())
        .offset(offset)
    )
    stale_ids = stale_ids_result.all()
    if not stale_ids:
        return
    await session.exec(delete(SpoolUsageLog).where(SpoolUsageLog.id.in_(stale_ids)))
    await session.commit()


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
    percent = spool.get("percent_remaining")
    if isinstance(percent, (int, float)) and not isinstance(percent, bool) and full_edges:
        clamped = max(0.0, min(100.0, float(percent)))
        return float(full_edges) * (1.0 - clamped / 100.0)
    return None
