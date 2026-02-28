"""Helpers for persisting live module status frames."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict

from sqlmodel import delete, select

from ..db.session import get_session
from ..schemas.module import ModuleStatus
from .cycle_log import record_cycle_log
from .module_identity import resolve_module_id
from .module_snapshot import delete_snapshots_for_module, record_module_snapshot
from .spool_usage import (
    clear_spool_usage_for_module,
    derive_spool_usage_delta,
    record_spool_usage_entry,
)

logger = logging.getLogger(__name__)
ATO_FLOW_ML_PER_MS = 0.0375

LEGACY_MODULE_IDS = {
    "SpoolTickTester",
    "SpoolTickCountAlias",
    "SpoolTickLegacy",
}
LEGACY_MODULE_IDS_LOWER = {module_id.lower() for module_id in LEGACY_MODULE_IDS}

_module_status_store: Dict[str, ModuleStatus] = {}
_next_module_id = 1
_pending_persist_tasks: set[asyncio.Task[Any]] = set()


def list_module_statuses() -> list[ModuleStatus]:
    """Return all known modules ordered by label for API responses."""

    return sorted(_module_status_store.values(), key=_module_sort_key)


def get_module_status(module_id: str) -> ModuleStatus | None:
    return _module_status_store.get(module_id)


def reset_module_store() -> None:
    """Testing helper to wipe module metadata."""

    global _next_module_id
    _module_status_store.clear()
    _next_module_id = 1
    _truncate_module_table()


async def hydrate_module_store_from_db() -> int:
    """Load the last known module snapshots from the database on startup."""

    global _next_module_id
    async with get_session() as session:
        result = await session.exec(select(ModuleStatus))
        rows = result.all()

    _module_status_store.clear()
    _next_module_id = 1
    for row in rows:
        module = ModuleStatus.model_validate(row)
        _module_status_store[module.module_id] = module
        if module.id and module.id >= _next_module_id:
            _next_module_id = module.id + 1
    return len(rows)


async def upsert_module_status(payload: dict[str, Any], client_ip: str | None = None) -> ModuleStatus:
    """Persist the latest status payload for a module."""

    module_id = resolve_module_id(payload)
    module = _get_or_create_module(module_id)

    previous_spool = (module.status_payload or {}).get("spool") if isinstance(module.status_payload, dict) else None
    config_spool = (module.config_payload or {}).get("spool") if isinstance(module.config_payload, dict) else None

    module.status = "online"
    module.last_seen = datetime.utcnow()

    payload_copy = dict(payload)
    _mirror_subsystems_into_heater(payload_copy)
    current_spool = payload_copy.get("spool") if isinstance(payload_copy.get("spool"), dict) else None
    existing_payload = dict(module.status_payload) if isinstance(module.status_payload, dict) else {}
    existing_spool = existing_payload.get("spool") if isinstance(existing_payload.get("spool"), dict) else None

    if existing_spool and current_spool:
        merged_spool = {**existing_spool, **current_spool}
        payload_copy["spool"] = merged_spool
        current_spool = merged_spool
    elif existing_spool and not current_spool:
        payload_copy["spool"] = existing_spool
        current_spool = existing_spool

    module.status_payload = payload_copy
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
    _schedule_persist(module)
    try:
        await record_module_snapshot(module.module_id, payload_copy, module.last_seen)
    except asyncio.CancelledError:
        logger.debug("Snapshot persistence cancelled for %s", module.module_id)
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.warning("Snapshot persistence failed for %s: %s", module.module_id, exc)
    return module


async def mark_module_offline(module_id: str) -> None:
    """Mark a module as offline once its WebSocket disconnects."""

    module = _module_status_store.get(module_id)
    if module is None:
        return
    module.status = "offline"
    module.last_seen = datetime.utcnow()
    _schedule_persist(module)


async def upsert_module_config(module_id: str, payload: dict[str, Any]) -> ModuleStatus:
    """Persist the last config payload reported by a module."""

    module = _get_or_create_module(module_id)
    module.config_payload = dict(payload)
    module.last_seen = datetime.utcnow()
    module.status = module.status or "online"
    _schedule_persist(module)
    return module


async def upsert_module_manifest(module_id: str, payload: dict[str, Any]) -> ModuleStatus:
    """Persist the latest manifest broadcast by a module."""

    resolved_id = resolve_module_id(payload, module_id or "unknown")
    manifest = dict(payload) if isinstance(payload, dict) else {}
    submodules = manifest.get("submodules") if isinstance(manifest.get("submodules"), list) else None

    module = _get_or_create_module(resolved_id)

    existing_config = dict(module.config_payload) if isinstance(module.config_payload, dict) else {}
    merged_config = {**existing_config, "module_manifest": manifest}
    if submodules is not None:
        merged_config["subsystems"] = submodules

    module.config_payload = merged_config
    module.last_seen = datetime.utcnow()
    module.status = module.status or "online"
    _schedule_persist(module)
    return module


async def upsert_module_metadata(module_id: str, updates: dict[str, Any]) -> ModuleStatus:
    """Apply manual metadata updates from the REST API."""

    module = _get_or_create_module(module_id)
    for field in ("label", "firmware_version", "ip_address", "rssi", "status"):
        if field in updates and updates[field] is not None:
            setattr(module, field, updates[field])

    module.last_seen = updates.get("last_seen") or datetime.utcnow()
    if not module.label:
        module.label = module_id
    if not module.status:
        module.status = "discovering"
    _schedule_persist(module)
    return module


async def purge_module_records(module_id: str) -> int:
    """Remove a module and any associated spool usage entries."""

    normalized_id = (module_id or "").strip()
    if not normalized_id:
        return 0

    removed = 0
    if normalized_id in _module_status_store:
        del _module_status_store[normalized_id]
        removed += 1

    removed += await clear_spool_usage_for_module(normalized_id)
    removed += await delete_snapshots_for_module(normalized_id)
    removed += await _delete_module_from_db(normalized_id)
    if removed:
        logger.info("Purged module %s with %s related rows", normalized_id, removed)
    return removed


async def apply_spool_activations(payload: dict[str, Any], module_hint: str | None = None) -> None:
    """Merge lightweight spool telemetry (activations, percent remaining, etc.)."""

    module_id = resolve_module_id(payload, module_hint or "unknown")
    if not module_id or module_id == "unknown":
        return

    spool_fragment = payload.get("spool") if isinstance(payload.get("spool"), dict) else {}

    # Accept top-level helpers for firmware that omits the nested object.
    for key in ("activations", "percent_remaining", "used_edges", "remaining_edges", "empty_alarm"):
        if key in payload and key not in spool_fragment:
            spool_fragment[key] = payload[key]

    if "activations" not in spool_fragment and "count" in payload:
        spool_fragment["activations"] = payload["count"]

    if not spool_fragment:
        return

    module = _get_or_create_module(module_id)
    existing_payload = dict(module.status_payload) if isinstance(module.status_payload, dict) else {}
    previous_spool = existing_payload.get("spool") if isinstance(existing_payload.get("spool"), dict) else {}
    merged_spool = {**previous_spool, **spool_fragment}
    module.status_payload = {**existing_payload, "spool": merged_spool}
    module.last_seen = datetime.utcnow()
    module.status = module.status or "online"

    config_spool = (module.config_payload or {}).get("spool") if isinstance(module.config_payload, dict) else None
    if "used_edges" not in spool_fragment:
        derived_edges = _calculate_used_edges_from_percent(
            merged_spool.get("full_edges") or (config_spool or {}).get("full_edges"),
            merged_spool.get("percent_remaining"),
        )
        if derived_edges is not None:
            merged_spool["used_edges"] = derived_edges
    usage_delta = derive_spool_usage_delta(module_id, previous_spool, merged_spool, config_spool)
    if usage_delta:
        await record_spool_usage_entry(
            module_id,
            usage_delta["delta_edges"],
            usage_delta["delta_mm"],
            usage_delta["total_used_edges"],
        )

    await _record_spool_activation_cycles(module_id, previous_spool, merged_spool, payload)
    _schedule_persist(module)


async def apply_ato_activations(payload: dict[str, Any], module_hint: str | None = None) -> None:
    """Merge lightweight ATO telemetry (activations, reservoir level, etc.)."""

    module_id = resolve_module_id(payload, module_hint or "unknown")
    if not module_id or module_id == "unknown":
        return

    ato_fragment = payload.get("ato") if isinstance(payload.get("ato"), dict) else {}

    for key in ("activations", "tank_level_ml", "tank_capacity_ml", "tank_percent"):
        if key in payload and key not in ato_fragment:
            ato_fragment[key] = payload[key]

    if not ato_fragment:
        return

    module = _get_or_create_module(module_id)
    existing_payload = dict(module.status_payload) if isinstance(module.status_payload, dict) else {}
    previous_ato = existing_payload.get("ato") if isinstance(existing_payload.get("ato"), dict) else {}
    merged_ato = {**previous_ato, **ato_fragment}
    module.status_payload = {**existing_payload, "ato": merged_ato}
    module.last_seen = datetime.utcnow()
    module.status = module.status or "online"

    await _record_ato_activation_cycles(module_id, previous_ato, merged_ato, payload)
    _schedule_persist(module)


async def record_module_alarm(payload: dict[str, Any], module_hint: str | None = None) -> None:
    """Track module alarm transitions so downstream consumers can render them."""

    module_id = resolve_module_id(payload, module_hint or "unknown")
    alarm_payload = payload.get("alarm") or {}
    code = alarm_payload.get("code")
    if not code:
        return

    module = _get_or_create_module(module_id)
    normalized = _normalize_alarm_payload(alarm_payload)
    _enrich_alarm_meta_with_heater_snapshot(module, alarm_payload, normalized)
    existing = list(module.alarms or [])
    without_code = [entry for entry in existing if entry.get("code") != code]
    # Drop cleared alarms from the public list to keep the payload concise.
    if normalized["active"]:
        without_code.append(normalized)

    module.alarms = without_code
    module.last_seen = datetime.utcnow()
    module.status = module.status or "online"
    _schedule_persist(module)


async def _record_spool_activation_cycles(
    module_id: str,
    previous_spool: dict[str, Any] | None,
    current_spool: dict[str, Any] | None,
    payload: dict[str, Any],
) -> None:
    prev_count = _coerce_int((previous_spool or {}).get("activations"))
    curr_count = _coerce_int((current_spool or {}).get("activations"))
    if prev_count is None or curr_count is None or curr_count <= prev_count:
        return

    trigger = _resolve_trigger(payload, default="auto")
    timestamp_s = payload.get("timestamp_s") or (current_spool or {}).get("timestamp_s")
    increments = curr_count - prev_count
    for _ in range(increments):
        await record_cycle_log(
            {
                "module": module_id,
                "cycle_type": "roller_activation",
                "trigger": trigger,
                "duration_ms": None,
                "timestamp_s": timestamp_s,
            }
        )


async def _record_ato_activation_cycles(
    module_id: str,
    previous_ato: dict[str, Any] | None,
    current_ato: dict[str, Any] | None,
    payload: dict[str, Any],
) -> None:
    prev_count = _coerce_int((previous_ato or {}).get("activations"))
    curr_count = _coerce_int((current_ato or {}).get("activations"))
    if prev_count is None or curr_count is None or curr_count <= prev_count:
        return

    increments = curr_count - prev_count
    trigger = _resolve_trigger(payload, default="auto")
    timestamp_s = payload.get("timestamp_s") or (current_ato or {}).get("timestamp_s")

    runtime_hint = payload.get("duration_ms")
    if runtime_hint is None:
        runtime_hint = payload.get("runtime_ms")
    duration_override = _coerce_int(runtime_hint)
    per_cycle_duration = duration_override if duration_override and duration_override > 0 else None
    if per_cycle_duration is None:
        per_cycle_duration = _estimate_ato_duration_ms(previous_ato, current_ato, increments)

    for _ in range(increments):
        await record_cycle_log(
            {
                "module": module_id,
                "cycle_type": "pump_activation",
                "trigger": trigger,
                "duration_ms": per_cycle_duration,
                "timestamp_s": timestamp_s,
            }
        )


def _estimate_ato_duration_ms(
    previous_ato: dict[str, Any] | None,
    current_ato: dict[str, Any] | None,
    increments: int,
) -> int | None:
    if increments <= 0:
        return None

    prev_level = _coerce_number((previous_ato or {}).get("tank_level_ml"))
    curr_level = _coerce_number((current_ato or {}).get("tank_level_ml"))
    if prev_level is None or curr_level is None:
        return None
    if prev_level <= curr_level:
        return None

    delta_ml = prev_level - curr_level
    per_activation_ml = delta_ml / increments if increments else delta_ml
    if per_activation_ml <= 0:
        return None

    duration_ms = per_activation_ml / ATO_FLOW_ML_PER_MS
    if duration_ms <= 0:
        return None
    return int(round(duration_ms))


def _resolve_trigger(payload: dict[str, Any], default: str | None = None) -> str | None:
    for key in ("trigger", "reason", "source"):
        candidate = payload.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return default


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


def _enrich_alarm_meta_with_heater_snapshot(
    module: ModuleStatus,
    alarm_payload: dict[str, Any],
    normalized: dict[str, Any],
) -> None:
    if (alarm_payload.get("code") or normalized.get("code")) != "thermistor_mismatch":
        return

    heater_snapshot = _extract_heater_snapshot(module)
    meta = dict(normalized.get("meta") or {})

    delta_value = _resolve_numeric_value(
        ("delta_c", "thermistor_delta_c", "thermistor_diff_c"),
        meta,
        alarm_payload,
        heater_snapshot,
    )
    if delta_value is None:
        delta_value = _compute_probe_delta(heater_snapshot)
    if delta_value is not None:
        meta["delta_c"] = delta_value

    threshold_value = _resolve_numeric_value(
        ("threshold_c", "delta_threshold_c", "thermistor_threshold_c", "thermistor_delta_threshold_c"),
        meta,
        alarm_payload,
        heater_snapshot,
    )
    if threshold_value is not None:
        meta["threshold_c"] = threshold_value

    primary_temp = _resolve_numeric_value(
        ("primary_temp_c", "primary_c", "primary"),
        meta,
        alarm_payload,
        heater_snapshot,
    )
    if primary_temp is None:
        primary_temp = _extract_thermistor_by_index(heater_snapshot, 0)
    if primary_temp is not None:
        meta["primary_temp_c"] = primary_temp

    secondary_temp = _resolve_numeric_value(
        ("secondary_temp_c", "secondary_c", "secondary"),
        meta,
        alarm_payload,
        heater_snapshot,
    )
    if secondary_temp is None:
        secondary_temp = _extract_thermistor_by_index(heater_snapshot, 1)
    if secondary_temp is not None:
        meta["secondary_temp_c"] = secondary_temp

    normalized["meta"] = meta or None


def _extract_heater_snapshot(module: ModuleStatus) -> dict[str, Any] | None:
    payload = module.status_payload if isinstance(module.status_payload, dict) else {}
    heater = payload.get("heater") if isinstance(payload.get("heater"), dict) else None
    if heater:
        return heater
    heaters = payload.get("heaters")
    if isinstance(heaters, list):
        for entry in heaters:
            if isinstance(entry, dict):
                return entry
    subsystems = payload.get("subsystems")
    if isinstance(subsystems, list):
        for entry in subsystems:
            if isinstance(entry, dict) and _looks_like_heater_subsystem(entry):
                return entry
    return None


def _mirror_subsystems_into_heater(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        return
    subsystems = payload.get("subsystems")
    if not isinstance(subsystems, list):
        return

    heater_entries: list[dict[str, Any]] = []
    for entry in subsystems:
        if not isinstance(entry, dict) or not _looks_like_heater_subsystem(entry):
            continue
        heater_entries.append(_adapt_heater_subsystem_entry(entry))

    if not heater_entries:
        return

    payload.setdefault("heaters", heater_entries)
    payload.setdefault("heater", heater_entries[0])


def _looks_like_heater_subsystem(entry: dict[str, Any]) -> bool:
    key_tokens = [
        str(entry.get("key", "")),
        str(entry.get("kind", "")),
        str(entry.get("label", "")),
    ]
    haystack = " ".join(token.lower() for token in key_tokens if isinstance(token, str))
    return "heater" in haystack


def _adapt_heater_subsystem_entry(entry: dict[str, Any]) -> dict[str, Any]:
    clone = dict(entry)
    thermometers = _extract_thermometer_readings(entry)
    if thermometers and "thermometers" not in clone:
        clone["thermometers"] = thermometers
    return clone


def _extract_thermometer_readings(entry: dict[str, Any]) -> list[dict[str, Any]]:
    sensors = entry.get("sensors")
    if not isinstance(sensors, list):
        return []

    readings: list[dict[str, Any]] = []
    for sensor in sensors:
        if not isinstance(sensor, dict):
            continue
        value = _coerce_number(sensor.get("value"))
        if value is None:
            continue
        label = sensor.get("label") or f"Sensor {len(readings) + 1}"
        unit = sensor.get("unit") or sensor.get("units") or "°C"
        readings.append({"label": label, "value": value, "unit": unit})
        if len(readings) >= 2:
            break
    return readings


def _calculate_used_edges_from_percent(full_edges: Any, percent_remaining: Any) -> float | None:
    edges = _coerce_number(full_edges)
    percent = _coerce_number(percent_remaining)
    if edges is None or edges <= 0 or percent is None:
        return None
    clamped = max(0.0, min(100.0, percent))
    return float(edges) * (1.0 - clamped / 100.0)


def _resolve_numeric_value(keys: tuple[str, ...], *sources: dict[str, Any] | None) -> float | None:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            if key not in source:
                continue
            value = _coerce_number(source.get(key))
            if value is not None:
                return value
    return None


def _extract_thermistor_by_index(heater: dict[str, Any] | None, index: int) -> float | None:
    if not heater or index < 0:
        return None
    readings = heater.get("thermistors_c")
    if isinstance(readings, list) and len(readings) > index:
        return _coerce_number(readings[index])
    return None


def _compute_probe_delta(heater: dict[str, Any] | None) -> float | None:
    if not heater:
        return None
    primary = _resolve_numeric_value(("primary_temp_c",), heater)
    if primary is None:
        primary = _extract_thermistor_by_index(heater, 0)
    secondary = _resolve_numeric_value(("secondary_temp_c",), heater)
    if secondary is None:
        secondary = _extract_thermistor_by_index(heater, 1)
    if primary is None or secondary is None:
        return None
    return abs(primary - secondary)


def _coerce_number(value: Any) -> float | None:
    if isinstance(value, bool):  # bool is a subclass of int, ignore explicitly
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _coerce_int(value: Any) -> int | None:
    numeric = _coerce_number(value)
    if numeric is None:
        return None
    return int(numeric)


async def purge_legacy_modules() -> int:
    """Remove leftover compatibility modules from memory."""

    if not LEGACY_MODULE_IDS_LOWER:
        return 0

    removed = 0
    for module_id in list(_module_status_store.keys()):
        if module_id.lower() in LEGACY_MODULE_IDS_LOWER:
            del _module_status_store[module_id]
            removed += 1
            removed += await clear_spool_usage_for_module(module_id)
            await _delete_module_from_db(module_id)

    if removed:
        logger.info("Purged %s legacy spooltick records", removed)
    return removed


def _module_sort_key(module: ModuleStatus) -> str:
    label = module.label or module.module_id or ""
    return label.lower()


def _get_or_create_module(module_id: str) -> ModuleStatus:
    global _next_module_id
    normalized = (module_id or "unknown").strip() or "unknown"
    module = _module_status_store.get(normalized)
    if module is None:
        module = ModuleStatus(id=_next_module_id, module_id=normalized, label=normalized)
        _module_status_store[normalized] = module
        _next_module_id += 1
    return module


def _schedule_persist(module: ModuleStatus) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # pragma: no cover - synchronous fallback
        asyncio.run(_persist_module(module))
        return

    task = loop.create_task(_persist_module(module))
    _pending_persist_tasks.add(task)
    task.add_done_callback(_persist_task_done)


def _persist_task_done(task: asyncio.Task) -> None:
    _pending_persist_tasks.discard(task)
    if task.cancelled():  # pragma: no cover - defensive guard
        return
    exc = task.exception()
    if exc:
        logger.warning("Module persistence task failed: %s", exc)


async def _persist_module(module: ModuleStatus) -> None:
    payload = module.model_dump()

    async def _save() -> None:
        async with get_session() as session:
            existing_result = await session.exec(
                select(ModuleStatus).where(ModuleStatus.module_id == module.module_id)
            )
            existing = existing_result.one_or_none()
            if existing:
                for field, value in payload.items():
                    setattr(existing, field, value)
            else:
                db_row = ModuleStatus(**payload)
                session.add(db_row)
                await session.flush()
                await session.refresh(db_row)
                module.id = db_row.id
            await session.commit()

    await asyncio.shield(_save())

    global _next_module_id
    if module.id and module.id >= _next_module_id:
        _next_module_id = module.id + 1


async def drain_module_persistence() -> None:
    if not _pending_persist_tasks:
        return
    await asyncio.gather(*list(_pending_persist_tasks), return_exceptions=True)


async def _delete_module_from_db(module_id: str) -> int:
    async with get_session() as session:
        result = await session.exec(delete(ModuleStatus).where(ModuleStatus.module_id == module_id))
        await session.commit()
        return result.rowcount or 0


def _truncate_module_table() -> None:
    async def _clear() -> None:
        async with get_session() as session:
            await session.exec(delete(ModuleStatus))
            await session.commit()

    try:
        asyncio.run(_clear())
    except RuntimeError:
        loop = asyncio.get_running_loop()
        loop.create_task(_clear())
