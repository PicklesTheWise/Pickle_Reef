from __future__ import annotations

from datetime import datetime
from typing import Any, List

from sqlalchemy import delete, func
from sqlmodel import select

from ..db.session import get_session
from ..schemas.cycle import CycleLog
from .module_identity import resolve_module_id

MAX_CYCLE_LOG_ENTRIES = 2000


async def record_cycle_log(payload: dict[str, Any]) -> CycleLog:
    """Persist an incoming cycle_log frame from a hardware module."""

    module_id = resolve_module_id(payload)
    log = CycleLog(
        module_id=module_id,
        cycle_type=payload.get("cycle_type") or "unknown",
        trigger=payload.get("trigger"),
        duration_ms=payload.get("duration_ms"),
        timeout=bool(payload.get("timeout", False)),
        module_timestamp_s=payload.get("timestamp_s"),
        recorded_at=datetime.utcnow(),
    )
    async with get_session() as session:
        session.add(log)
        await session.commit()
        await session.refresh(log)
        await _prune_cycle_logs(session)
    return log


async def get_cycle_logs_since(timestamp: datetime) -> List[CycleLog]:
    statement = (
        select(CycleLog)
        .where(CycleLog.recorded_at >= timestamp)
        .order_by(CycleLog.recorded_at, CycleLog.id)
    )
    async with get_session() as session:
        result = await session.exec(statement)
        return result.all()


async def add_cycle_log_entry(entry: CycleLog) -> None:
    """Testing helper to append a preconstructed entry."""

    async with get_session() as session:
        session.add(entry)
        await session.commit()
        await _prune_cycle_logs(session)


async def clear_cycle_logs() -> None:
    async with get_session() as session:
        await session.exec(delete(CycleLog))
        await session.commit()


async def _prune_cycle_logs(session) -> None:
    count_result = await session.exec(select(func.count()).select_from(CycleLog))
    total = count_result.one()
    if total <= MAX_CYCLE_LOG_ENTRIES:
        return

    offset = MAX_CYCLE_LOG_ENTRIES
    stale_ids_result = await session.exec(
        select(CycleLog.id)
        .order_by(CycleLog.recorded_at.desc(), CycleLog.id.desc())
        .offset(offset)
    )
    stale_ids = stale_ids_result.all()
    if not stale_ids:
        return
    await session.exec(delete(CycleLog).where(CycleLog.id.in_(stale_ids)))
    await session.commit()
