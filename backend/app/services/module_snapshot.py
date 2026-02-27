from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, List

from sqlalchemy import delete, func
from sqlmodel import select

from ..db.session import get_session
from ..schemas.module_snapshot import ModuleSnapshot

MAX_SNAPSHOT_ROWS = 100_000
SNAPSHOT_RETENTION_HOURS = 24 * 30
logger = logging.getLogger(__name__)


async def record_module_snapshot(
    module_id: str,
    payload: dict[str, Any],
    recorded_at: datetime | None = None,
) -> ModuleSnapshot:
    if not module_id:
        raise ValueError("module_id is required for snapshots")

    snapshot = ModuleSnapshot(
        module_id=module_id,
        payload=dict(payload),
        recorded_at=recorded_at or datetime.utcnow(),
    )

    async def _persist_snapshot() -> ModuleSnapshot:
        async with get_session() as session:
            session.add(snapshot)
            await session.commit()
            await _prune_snapshots(session)
            await session.refresh(snapshot)
            return snapshot

    try:
        return await asyncio.shield(_persist_snapshot())
    except asyncio.CancelledError:
        logger.debug("Snapshot persistence cancelled for module %s", module_id)
        raise



async def list_module_snapshots(
    module_id: str,
    *,
    limit: int = 100,
    window_hours: int | None = None,
) -> List[ModuleSnapshot]:
    if not module_id:
        return []

    clamped_limit = max(1, min(limit, 1000))
    statement = select(ModuleSnapshot).where(ModuleSnapshot.module_id == module_id)
    if window_hours and window_hours > 0:
        since = datetime.utcnow() - timedelta(hours=window_hours)
        statement = statement.where(ModuleSnapshot.recorded_at >= since)
    statement = statement.order_by(ModuleSnapshot.recorded_at.desc(), ModuleSnapshot.id.desc())
    statement = statement.limit(clamped_limit)

    async with get_session() as session:
        result = await session.exec(statement)
        rows = result.all()
    return list(reversed(rows))


async def delete_snapshots_for_module(module_id: str) -> int:
    if not module_id:
        return 0
    async with get_session() as session:
        result = await session.exec(delete(ModuleSnapshot).where(ModuleSnapshot.module_id == module_id))
        await session.commit()
        return result.rowcount or 0


async def clear_module_snapshots() -> None:
    async with get_session() as session:
        await session.exec(delete(ModuleSnapshot))
        await session.commit()


async def _prune_snapshots(session) -> None:
    cutoff = datetime.utcnow() - timedelta(hours=SNAPSHOT_RETENTION_HOURS)
    await session.exec(delete(ModuleSnapshot).where(ModuleSnapshot.recorded_at < cutoff))
    await session.commit()

    count_result = await session.exec(select(func.count()).select_from(ModuleSnapshot))
    total = count_result.one()
    if total <= MAX_SNAPSHOT_ROWS:
        return

    offset = MAX_SNAPSHOT_ROWS
    stale_ids_result = await session.exec(
        select(ModuleSnapshot.id)
        .order_by(ModuleSnapshot.recorded_at.desc(), ModuleSnapshot.id.desc())
        .offset(offset)
    )
    stale_ids = stale_ids_result.all()
    if not stale_ids:
        return
    await session.exec(delete(ModuleSnapshot).where(ModuleSnapshot.id.in_(stale_ids)))
    await session.commit()
