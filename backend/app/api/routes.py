from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, status
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from sqlalchemy import func

from ..schemas.telemetry import Telemetry, TelemetryCreate
from ..schemas.module import ModuleStatus, ModuleStatusRead, ModuleUpdate, ModuleControlRequest
from ..schemas.cycle import CycleLog
from ..schemas.spool_usage import SpoolUsageLog
from ..db import SessionLocal
from ..services.module_control import apply_module_controls
from ..services.ws_trace import get_ws_trace, clear_ws_trace

router = APIRouter(prefix="/api", tags=["telemetry"])


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session


@router.get("/telemetry", response_model=list[Telemetry])
async def list_telemetry(limit: int = 100, session: AsyncSession = Depends(get_session)):
    statement = select(Telemetry).order_by(Telemetry.captured_at.desc()).limit(limit)
    result = await session.exec(statement)
    return list(result)


@router.post("/telemetry", response_model=Telemetry, status_code=status.HTTP_201_CREATED)
async def create_telemetry(payload: TelemetryCreate, session: AsyncSession = Depends(get_session)):
    data = payload.model_dump(exclude_unset=True)
    if "captured_at" not in data or data["captured_at"] is None:
        data["captured_at"] = datetime.utcnow()
    telemetry = Telemetry(**data)
    session.add(telemetry)
    await session.commit()
    await session.refresh(telemetry)
    return telemetry


@router.get("/telemetry/summary")
async def telemetry_summary(session: AsyncSession = Depends(get_session)):
    statement = (
        select(
            Telemetry.metric,
            func.avg(Telemetry.value).label("avg_value"),
            func.max(Telemetry.captured_at).label("last_seen"),
        )
        .group_by(Telemetry.metric)
    )
    result = await session.exec(statement)
    return [
        {
            "metric": metric,
            "avg_value": avg_value,
            "last_seen": last_seen,
        }
        for metric, avg_value, last_seen in result
    ]


@router.get("/modules", response_model=list[ModuleStatusRead])
async def list_modules(session: AsyncSession = Depends(get_session)):
    result = await session.exec(select(ModuleStatus).order_by(ModuleStatus.label))
    modules = list(result)
    response: list[ModuleStatusRead] = []
    for module in modules:
        hydrated = ModuleStatusRead.model_validate(module)
        hydrated.spool_state = _merge_spool_state(module)
        response.append(hydrated)
    return response


@router.put("/modules/{module_id}", response_model=ModuleStatus)
async def upsert_module(
    module_id: str,
    payload: ModuleUpdate,
    session: AsyncSession = Depends(get_session),
):
    data = payload.model_dump(exclude_unset=True)
    statement = select(ModuleStatus).where(ModuleStatus.module_id == module_id)
    result = await session.exec(statement)
    module = result.first()

    if module:
        for key, value in data.items():
            setattr(module, key, value)
    else:
        module = ModuleStatus(
            module_id=module_id,
            label=data.get("label") or module_id,
            firmware_version=data.get("firmware_version"),
            ip_address=data.get("ip_address"),
            rssi=data.get("rssi"),
            status=data.get("status") or "discovering",
        )
        session.add(module)

    module.last_seen = data.get("last_seen") or datetime.utcnow()
    await session.commit()
    await session.refresh(module)
    return module


@router.get("/health")
async def healthcheck():
    return {"status": "ok"}


@router.post("/modules/{module_id}/control", status_code=status.HTTP_202_ACCEPTED)
async def control_module(module_id: str, payload: ModuleControlRequest):
    return await apply_module_controls(module_id, payload)


@router.get("/cycles/history")
async def cycle_history(window_hours: int = 24, session: AsyncSession = Depends(get_session)):
    """Return historical roller and pump cycles within the requested window."""

    clamped_window = max(1, min(window_hours, 24 * 7))
    since = datetime.utcnow() - timedelta(hours=clamped_window)
    statement = select(CycleLog).where(CycleLog.recorded_at >= since).order_by(CycleLog.recorded_at)
    result = await session.exec(statement)
    logs = list(result)

    def serialize(log: CycleLog) -> dict:
        return {
            "id": log.id,
            "module_id": log.module_id,
            "cycle_type": log.cycle_type,
            "trigger": log.trigger,
            "duration_ms": log.duration_ms,
            "timeout": log.timeout,
            "recorded_at": log.recorded_at.isoformat(),
        }

    def summarize(items: list[CycleLog]) -> dict[str, float]:
        count = len(items)
        total_duration = sum((entry.duration_ms or 0) for entry in items)
        avg_duration = total_duration / count if count else 0
        frequency_per_hour = count / clamped_window if clamped_window else 0
        return {
            "count": count,
            "total_duration_ms": total_duration,
            "avg_duration_ms": avg_duration,
            "frequency_per_hour": frequency_per_hour,
        }

    roller_logs = [log for log in logs if log.cycle_type and log.cycle_type.startswith("roller")]
    pump_logs = [log for log in logs if log.cycle_type and log.cycle_type.startswith("pump")]

    roller_stats = summarize(roller_logs)
    ato_stats = summarize(pump_logs)
    ato_stats["avg_fill_seconds"] = (ato_stats["avg_duration_ms"] / 1000) if ato_stats["count"] else 0

    return {
        "window_hours": clamped_window,
        "roller_runs": [serialize(log) for log in roller_logs],
        "roller_stats": roller_stats,
        "ato_runs": [serialize(log) for log in pump_logs],
        "ato_stats": ato_stats,
    }


@router.get("/spool-usage")
async def spool_usage_history(
    module_id: str | None = None,
    window_hours: int = 72,
    limit: int | None = None,
    session: AsyncSession = Depends(get_session),
):
    clamped_window = max(1, min(window_hours, 24 * 90))
    since = datetime.utcnow() - timedelta(hours=clamped_window)
    statement = select(SpoolUsageLog).where(SpoolUsageLog.recorded_at >= since)
    if module_id:
        statement = statement.where(SpoolUsageLog.module_id == module_id)
    statement = statement.order_by(SpoolUsageLog.recorded_at)
    if limit:
        statement = statement.limit(max(1, limit))
    result = await session.exec(statement)
    entries = list(result)
    return [
        {
            "id": entry.id,
            "module_id": entry.module_id,
            "delta_edges": entry.delta_edges,
            "delta_mm": entry.delta_mm,
            "total_used_edges": entry.total_used_edges,
            "recorded_at": entry.recorded_at.isoformat(),
        }
        for entry in entries
    ]


@router.get("/debug/ws-trace")
async def list_ws_trace(limit: int = 200):
    clamped = max(1, min(limit, 1000))
    return get_ws_trace(clamped)


@router.delete("/debug/ws-trace", status_code=status.HTTP_204_NO_CONTENT)
async def clear_ws_trace_log():
    clear_ws_trace()
    return None


def _merge_spool_state(module: ModuleStatus) -> dict | None:
    status_spool = (module.status_payload or {}).get("spool") or {}
    config_spool = (module.config_payload or {}).get("spool") or {}
    merged = {**config_spool, **status_spool}
    return merged or None
