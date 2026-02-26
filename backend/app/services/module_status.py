"""Helpers for persisting live module status frames."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

import logging

from ..schemas.module import ModuleStatus
from .spool_usage import (
    clear_spool_usage_for_module,
    derive_spool_usage_delta,
    record_spool_usage_entry,
)

logger = logging.getLogger(__name__)

LEGACY_MODULE_IDS = {
    "SpoolTickTester",
    "SpoolTickCountAlias",
    "SpoolTickLegacy",
}
LEGACY_MODULE_IDS_LOWER = {module_id.lower() for module_id in LEGACY_MODULE_IDS}

_module_status_store: Dict[str, ModuleStatus] = {}
_next_module_id = 1


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


async def upsert_module_status(payload: dict[str, Any], client_ip: str | None = None) -> ModuleStatus:
    """Persist the latest status payload for a module."""

    module_id = (payload.get("module") or "unknown").strip() or "unknown"
    module = _get_or_create_module(module_id)

    previous_spool = (module.status_payload or {}).get("spool") if isinstance(module.status_payload, dict) else None
    config_spool = (module.config_payload or {}).get("spool") if isinstance(module.config_payload, dict) else None

    module.status = "online"
    module.last_seen = datetime.utcnow()

    payload_copy = dict(payload)
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
    return module


async def mark_module_offline(module_id: str) -> None:
    """Mark a module as offline once its WebSocket disconnects."""

    module = _module_status_store.get(module_id)
    if module is None:
        return
    module.status = "offline"
    module.last_seen = datetime.utcnow()


async def upsert_module_config(module_id: str, payload: dict[str, Any]) -> ModuleStatus:
    """Persist the last config payload reported by a module."""

    module = _get_or_create_module(module_id)
    module.config_payload = dict(payload)
    module.last_seen = datetime.utcnow()
    module.status = module.status or "online"
    return module


async def upsert_module_manifest(module_id: str, payload: dict[str, Any]) -> ModuleStatus:
    """Persist the latest manifest broadcast by a module."""

    manifest_module = payload.get("module")
    resolved_id = (module_id or manifest_module or "unknown").strip() or "unknown"
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

    removed += clear_spool_usage_for_module(normalized_id)
    if removed:
        logger.info("Purged module %s with %s related rows", normalized_id, removed)
    return removed


async def apply_spool_activations(payload: dict[str, Any]) -> None:
    """Merge lightweight spool telemetry (activations, percent remaining, etc.)."""

    module_id = payload.get("module")
    if not module_id:
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
    current_spool = existing_payload.get("spool") if isinstance(existing_payload.get("spool"), dict) else {}
    merged_spool = {**current_spool, **spool_fragment}
    module.status_payload = {**existing_payload, "spool": merged_spool}
    module.last_seen = datetime.utcnow()
    module.status = module.status or "online"


async def record_module_alarm(payload: dict[str, Any]) -> None:
    """Track module alarm transitions so downstream consumers can render them."""

    module_id = payload.get("module") or "unknown"
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
    return None


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


async def purge_legacy_modules() -> int:
    """Remove leftover compatibility modules from memory."""

    if not LEGACY_MODULE_IDS_LOWER:
        return 0

    removed = 0
    for module_id in list(_module_status_store.keys()):
        if module_id.lower() in LEGACY_MODULE_IDS_LOWER:
            del _module_status_store[module_id]
            removed += 1
            removed += clear_spool_usage_for_module(module_id)

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
