from __future__ import annotations

from datetime import datetime
from typing import Any

from ..db import SessionLocal
from ..schemas.cycle import CycleLog


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

    async with SessionLocal() as session:
        session.add(log)
        await session.commit()
        await session.refresh(log)
        return log
