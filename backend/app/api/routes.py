from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, status

from ..schemas.telemetry import Telemetry, TelemetryCreate
from ..schemas.module import (
    ModuleStatus,
    ModuleStatusRead,
    ModuleSubsystemDefinition,
    ModuleUpdate,
    ModuleControlRequest,
)
from ..schemas.cycle import CycleLog
from ..services.module_control import apply_module_controls
from ..services.module_status import (
    list_module_statuses,
    purge_module_records,
    upsert_module_metadata,
)
from ..services.telemetry_store import (
    list_telemetry_entries,
    record_telemetry_entry,
    summarize_telemetry_entries,
)
from ..services.cycle_log import get_cycle_logs_since
from ..services.spool_usage import get_spool_usage_entries
from ..services.ws_trace import get_ws_trace, clear_ws_trace

router = APIRouter(prefix="/api", tags=["telemetry"])
MAX_CYCLE_HISTORY_HOURS = 365 * 24
MAX_DECLARED_SUBSYSTEMS = 8
ALLOWED_SUBSYSTEM_KINDS = {"roller", "ato"}
CATEGORY_KIND_MAP = {
    "filter": "roller",
    "roller": "roller",
    "spool": "roller",
    "media": "roller",
    "ato": "ato",
    "pump": "ato",
    "reservoir": "ato",
    "refill": "ato",
}
CAPABILITY_KIND_MAP = {
    "roller": "roller",
    "spool": "roller",
    "filter": "roller",
    "ato": "ato",
    "pump": "ato",
    "reservoir": "ato",
    "alarm": "roller",
}
DEFAULT_SUBSYSTEM_PAYLOADS: list[dict[str, str]] = [
    {
        "key": "roller",
        "kind": "roller",
        "card_suffix": "Roller",
        "badge_label": "Filter",
    },
    {
        "key": "ato",
        "kind": "ato",
        "card_suffix": "ATO",
        "badge_label": "ATO",
    },
]


@router.get("/telemetry", response_model=list[Telemetry])
async def list_telemetry(limit: int = 100):
    clamped_limit = max(1, min(limit, 1000))
    return list_telemetry_entries(limit=clamped_limit)


@router.post("/telemetry", response_model=Telemetry, status_code=status.HTTP_201_CREATED)
async def create_telemetry(payload: TelemetryCreate):
    data = payload.model_dump(exclude_unset=True)
    if "captured_at" not in data or data["captured_at"] is None:
        data["captured_at"] = datetime.utcnow()
    telemetry = Telemetry(**data)
    return record_telemetry_entry(telemetry)


@router.get("/telemetry/summary")
async def telemetry_summary():
    return summarize_telemetry_entries()


@router.get("/modules", response_model=list[ModuleStatusRead])
async def list_modules():
    modules = list_module_statuses()
    response: list[ModuleStatusRead] = []
    for module in modules:
        hydrated = ModuleStatusRead.model_validate(module)
        hydrated.module_type = _infer_module_type(module)
        hydrated.spool_state = _merge_spool_state(module)
        hydrated.subsystems = _derive_module_subsystems(module)
        response.append(hydrated)
    return response


@router.put("/modules/{module_id}", response_model=ModuleStatus)
async def upsert_module(
    module_id: str,
    payload: ModuleUpdate,
):
    data = payload.model_dump(exclude_unset=True)
    data["last_seen"] = data.get("last_seen") or datetime.utcnow()
    return await upsert_module_metadata(module_id, data)


@router.get("/health")
async def healthcheck():
    return {"status": "ok"}


@router.post("/modules/{module_id}/control", status_code=status.HTTP_202_ACCEPTED)
async def control_module(module_id: str, payload: ModuleControlRequest):
    return await apply_module_controls(module_id, payload)


@router.delete("/modules/{module_id}")
async def delete_module(module_id: str):
    removed = await purge_module_records(module_id)
    if removed == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Module not found")
    return {"removed": removed}


@router.get("/cycles/history")
async def cycle_history(window_hours: int = 24):
    """Return historical roller and pump cycles within the requested window."""

    clamped_window = max(1, min(window_hours, MAX_CYCLE_HISTORY_HOURS))
    since = datetime.utcnow() - timedelta(hours=clamped_window)
    logs = sorted(get_cycle_logs_since(since), key=lambda entry: entry.recorded_at)

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
):
    clamped_window = max(1, min(window_hours, 24 * 90))
    since = datetime.utcnow() - timedelta(hours=clamped_window)
    entries = get_spool_usage_entries(
        module_id=module_id,
        since=since,
        limit=max(1, limit) if limit else None,
    )
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


def _derive_module_subsystems(module: ModuleStatus) -> list[ModuleSubsystemDefinition]:
    manifest_submodules = _extract_manifest_submodules(module)
    if manifest_submodules:
        normalized_manifest = _normalize_subsystems(manifest_submodules)
        if normalized_manifest:
            return normalized_manifest

    sources = [
        (module.config_payload or {}).get("subsystems"),
        (module.status_payload or {}).get("subsystems"),
    ]
    for raw in sources:
        normalized = _normalize_subsystems(raw)
        if normalized:
            return normalized
    inferred = _infer_subsystems_from_payload(module)
    if inferred:
        return inferred
    return [_build_default_subsystem(payload) for payload in DEFAULT_SUBSYSTEM_PAYLOADS]


def _infer_module_type(module: ModuleStatus) -> str:
    status_payload = module.status_payload if isinstance(module.status_payload, dict) else {}

    if _module_manifest_declares_kind(module, "heater") or _is_heater_module(module, status_payload):
        return "Heater"

    if _module_manifest_declares_kind(module, "filter") or _module_has_spool_signals(module):
        return "Filter"

    if _module_manifest_declares_kind(module, "ato") or _module_has_ato_signals(module):
        return "ATO"

    return "Sensor"


def _extract_manifest_submodules(module: ModuleStatus) -> list | None:
    manifest_sources = [
        (module.config_payload or {}).get("module_manifest"),
        (module.status_payload or {}).get("module_manifest"),
    ]
    for manifest in manifest_sources:
        if isinstance(manifest, dict):
            submodules = manifest.get("submodules")
            if isinstance(submodules, list):
                return submodules
    return None


def _normalize_subsystems(raw: Any) -> list[ModuleSubsystemDefinition]:
    if not isinstance(raw, list):
        return []
    normalized: list[ModuleSubsystemDefinition] = []
    for index, entry in enumerate(raw):
        definition = _normalize_subsystem_entry(entry, index)
        if definition:
            normalized.append(definition)
        if len(normalized) >= MAX_DECLARED_SUBSYSTEMS:
            break
    return normalized


def _normalize_subsystem_entry(entry: Any, index: int) -> ModuleSubsystemDefinition | None:
    if isinstance(entry, str):
        payload: dict[str, Any] = {"key": entry}
    elif isinstance(entry, dict):
        payload = entry
    else:
        return None

    key = _sanitize_slug(payload.get("key") or payload.get("id") or payload.get("slug"))
    if not key:
        key = f"subsystem-{index + 1}"

    kind = _resolve_subsystem_kind(payload, key)

    template = next((tpl for tpl in DEFAULT_SUBSYSTEM_PAYLOADS if tpl["kind"] == kind), None)

    card_suffix = _safe_str(payload.get("card_suffix") or payload.get("suffix"))
    badge_label = _safe_str(payload.get("badge_label") or payload.get("badge"))
    badge_variant = _safe_str(payload.get("badge_variant"))
    label = _safe_str(payload.get("label"))
    raw_category = _safe_str(payload.get("category"))

    if not card_suffix and template:
        card_suffix = template.get("card_suffix")
    if not badge_label:
        if template:
            badge_label = template.get("badge_label")
        elif raw_category:
            badge_label = raw_category.capitalize()

    return ModuleSubsystemDefinition(
        key=key,
        kind=kind,
        label=label,
        badge_label=badge_label,
        badge_variant=badge_variant,
        card_suffix=card_suffix,
    )


def _resolve_subsystem_kind(payload: dict[str, Any], key: str) -> str:
    candidates = [payload.get("kind"), payload.get("type"), payload.get("category"), key]
    for candidate in candidates:
        normalized = _normalize_kind_candidate(candidate)
        if not normalized:
            continue
        if normalized in ALLOWED_SUBSYSTEM_KINDS:
            return normalized
        category_match = CATEGORY_KIND_MAP.get(normalized)
        if category_match:
            return category_match

    capabilities = payload.get("capabilities")
    if isinstance(capabilities, list):
        for capability in capabilities:
            normalized_cap = _normalize_kind_candidate(capability)
            if not normalized_cap:
                continue
            mapped = CAPABILITY_KIND_MAP.get(normalized_cap)
            if mapped:
                return mapped

    prefix = (key or "roller").split(":", 1)[0]
    if prefix in ALLOWED_SUBSYSTEM_KINDS:
        return prefix
    return "roller"


def _build_default_subsystem(payload: dict[str, str]) -> ModuleSubsystemDefinition:
    return ModuleSubsystemDefinition(**payload)


def _sanitize_slug(value: Any) -> str | None:
    text = _safe_str(value)
    if not text:
        return None
    cleaned = "".join(ch for ch in text if ch.isalnum() or ch in {"-", "_", ":", "."})
    return cleaned or None


def _safe_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_kind_candidate(value: Any) -> str | None:
    text = _safe_str(value)
    if not text:
        return None
    return text.split(":", 1)[0].lower()


def _merge_spool_state(module: ModuleStatus) -> dict | None:
    status_spool = (module.status_payload or {}).get("spool") or {}
    config_spool = (module.config_payload or {}).get("spool") or {}
    merged = {**config_spool, **status_spool}
    return merged or None


def _module_manifest_declares_kind(module: ModuleStatus, target_kind: str) -> bool:
    submodules = _extract_manifest_submodules(module)
    if not submodules:
        return False
    normalized = _normalize_subsystems(submodules)
    looking_for = target_kind.lower()
    return any(entry.kind == looking_for for entry in normalized)


def _infer_subsystems_from_payload(module: ModuleStatus) -> list[ModuleSubsystemDefinition]:
    status_payload = module.status_payload if isinstance(module.status_payload, dict) else {}
    config_payload = module.config_payload if isinstance(module.config_payload, dict) else {}

    spool_sources = [
        status_payload.get("spool") if isinstance(status_payload.get("spool"), dict) else None,
        config_payload.get("spool") if isinstance(config_payload.get("spool"), dict) else None,
    ]
    has_spool = any(_spool_payload_has_signals(payload) for payload in spool_sources)

    ato_sources = [
        status_payload.get("ato") if isinstance(status_payload.get("ato"), dict) else None,
        config_payload.get("ato") if isinstance(config_payload.get("ato"), dict) else None,
    ]
    has_ato = any(_ato_payload_has_signals(payload) for payload in ato_sources)

    subsystems: list[ModuleSubsystemDefinition] = []
    if has_spool:
        subsystems.append(_build_default_subsystem(DEFAULT_SUBSYSTEM_PAYLOADS[0]))
    if has_ato:
        subsystems.append(_build_default_subsystem(DEFAULT_SUBSYSTEM_PAYLOADS[1]))

    if subsystems:
        return subsystems

    if _is_heater_module(module, status_payload):
        return [
            ModuleSubsystemDefinition(
                key="heater",
                kind="heater",
                label=module.label or module.module_id or "Heater",
                badge_label="Heat",
                card_suffix="Heat",
            )
        ]

    return []


def _spool_payload_has_signals(payload: dict | None) -> bool:
    if not isinstance(payload, dict):
        return False
    for key in ("used_edges", "remaining_edges", "percent_remaining", "full_edges", "total_length_mm", "length_mm", "activations"):
        value = payload.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
    return False


def _module_has_spool_signals(module: ModuleStatus) -> bool:
    status_payload = module.status_payload if isinstance(module.status_payload, dict) else {}
    config_payload = module.config_payload if isinstance(module.config_payload, dict) else {}
    spool_sources = [
        status_payload.get("spool") if isinstance(status_payload.get("spool"), dict) else None,
        config_payload.get("spool") if isinstance(config_payload.get("spool"), dict) else None,
    ]
    return any(_spool_payload_has_signals(payload) for payload in spool_sources)


def _ato_payload_has_signals(payload: dict | None) -> bool:
    if not isinstance(payload, dict):
        return False
    for key in ("pump_running", "manual_mode", "timeout_alarm", "pump_speed", "tank_level_ml", "tank_capacity_ml"):
        if key in payload:
            return True
    return False


def _module_has_ato_signals(module: ModuleStatus) -> bool:
    status_payload = module.status_payload if isinstance(module.status_payload, dict) else {}
    config_payload = module.config_payload if isinstance(module.config_payload, dict) else {}
    ato_sources = [
        status_payload.get("ato") if isinstance(status_payload.get("ato"), dict) else None,
        config_payload.get("ato") if isinstance(config_payload.get("ato"), dict) else None,
    ]
    return any(_ato_payload_has_signals(payload) for payload in ato_sources)


def _is_heater_module(module: ModuleStatus, status_payload: dict[str, Any]) -> bool:
    name_haystack = f"{module.module_id or ''} {module.label or ''}".lower()
    if any(token in name_haystack for token in ("heat", "heater")):
        return True

    heater_payload = status_payload.get("heater")
    if isinstance(heater_payload, dict) and heater_payload:
        return True
    heaters_collection = status_payload.get("heaters")
    if isinstance(heaters_collection, list) and heaters_collection:
        return True
    return False
