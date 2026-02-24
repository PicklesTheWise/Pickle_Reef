"""Helpers for persisting live module status frames."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import logging

from sqlmodel import select

from ..db import SessionLocal
from ..schemas.module import ModuleStatus
from .spool_usage import derive_spool_usage_delta, record_spool_usage_entry

logger = logging.getLogger(__name__)

async def upsert_module_status(payload: dict[str, Any], client_ip: str | None = None) -> ModuleStatus:
    """Persist the latest status payload for a module."""

    module_id = payload.get("module") or "unknown"

    async with SessionLocal() as session:
        result = await session.exec(select(ModuleStatus).where(ModuleStatus.module_id == module_id))
        module = result.first()

        previous_spool = (module.status_payload or {}).get("spool") if module and module.status_payload else None
        config_spool = (module.config_payload or {}).get("spool") if module and module.config_payload else None

        if module is None:
            module = ModuleStatus(module_id=module_id, label=module_id)
            previous_spool = None

        module.status = "online"
        module.last_seen = datetime.utcnow()
        current_spool = payload.get("spool") if isinstance(payload, dict) else None
        module.status_payload = payload
        module.ip_address = client_ip or module.ip_address
        if current_spool:
            usage_delta = derive_spool_usage_delta(module_id, previous_spool, current_spool, config_spool)
            if usage_delta:
                await record_spool_usage_entry(
                    module_id,
                    usage_delta["delta_edges"],
                    usage_delta["delta_mm"],
                    usage_delta["total_used_edges"],
                )
        logger.info("Status update for %s spool=%s", module_id, current_spool)
        session.add(module)
        await session.commit()
        await session.refresh(module)
        return module


async def mark_module_offline(module_id: str) -> None:
    """Mark a module as offline once its WebSocket disconnects."""

    async with SessionLocal() as session:
        result = await session.exec(select(ModuleStatus).where(ModuleStatus.module_id == module_id))
        module = result.first()
        if module is None:
            return
        module.status = "offline"
        module.last_seen = datetime.utcnow()
        session.add(module)
        await session.commit()


async def upsert_module_config(module_id: str, payload: dict[str, Any]) -> ModuleStatus:
    """Persist the last config payload reported by a module."""

    async with SessionLocal() as session:
        result = await session.exec(select(ModuleStatus).where(ModuleStatus.module_id == module_id))
        module = result.first()

        if module is None:
            module = ModuleStatus(module_id=module_id, label=module_id)

        module.config_payload = payload
        module.last_seen = datetime.utcnow()
        module.status = module.status or "online"
        session.add(module)
        await session.commit()
        await session.refresh(module)
        return module


async def record_module_alarm(payload: dict[str, Any]) -> None:
    """Track module alarm transitions so downstream consumers can render them."""

    module_id = payload.get("module") or "unknown"
    alarm_payload = payload.get("alarm") or {}
    code = alarm_payload.get("code")
    if not code:
        return

    normalized = _normalize_alarm_payload(alarm_payload)

    async with SessionLocal() as session:
        result = await session.exec(select(ModuleStatus).where(ModuleStatus.module_id == module_id))
        module = result.first()

        if module is None:
            module = ModuleStatus(module_id=module_id, label=module_id)

        existing = module.alarms or []
        without_code = [entry for entry in existing if entry.get("code") != code]
        # Drop cleared alarms from the public list to keep the payload concise.
        if normalized["active"]:
            without_code.append(normalized)

        module.alarms = without_code
        module.last_seen = datetime.utcnow()
        module.status = module.status or "online"
        session.add(module)
        await session.commit()


def _normalize_alarm_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": payload.get("code"),
        "severity": payload.get("severity") or "warning",
        "active": bool(payload.get("active")),
        "message": payload.get("message") or payload.get("code"),
        "timestamp_s": payload.get("timestamp_s"),
        "meta": payload.get("meta"),
        "received_at": datetime.utcnow().isoformat(),
    }
