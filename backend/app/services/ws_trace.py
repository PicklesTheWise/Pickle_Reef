from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

from ..core.config import settings
from .module_identity import resolve_module_id

MAX_TRACE_ENTRIES = 10_000
MAX_HISTORY_WINDOW_MINUTES = 24 * 60
RETENTION_DAYS = max(0, settings.ws_trace_retention_days)
_db_path = Path(settings.ws_trace_db_path)
_db_path.parent.mkdir(parents=True, exist_ok=True)
_db_lock = Lock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _initialize() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ws_trace_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recorded_at TEXT NOT NULL,
                direction TEXT NOT NULL,
                module_id TEXT,
                payload TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ws_trace_recorded_at ON ws_trace_log(recorded_at DESC, id DESC)"
        )
        conn.commit()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _prune(conn: sqlite3.Connection) -> None:
    if MAX_TRACE_ENTRIES <= 0:
        return
    row = conn.execute(
        "SELECT id FROM ws_trace_log ORDER BY id DESC LIMIT 1 OFFSET ?",
        (MAX_TRACE_ENTRIES - 1,),
    ).fetchone()
    if row:
        conn.execute("DELETE FROM ws_trace_log WHERE id < ?", (row[0],))
    if RETENTION_DAYS > 0:
        cutoff = datetime.utcnow() - timedelta(days=RETENTION_DAYS)
        conn.execute(
            "DELETE FROM ws_trace_log WHERE recorded_at < ?",
            (cutoff.isoformat(timespec="milliseconds"),),
        )


def record_ws_trace(direction: str, payload: dict[str, Any], module_id: str | None = None) -> None:
    entry = {
        "timestamp": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
        "direction": direction,
        "module_id": module_id,
        "payload": payload,
    }
    payload_blob = json.dumps(entry["payload"], default=_json_default)
    with _db_lock:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO ws_trace_log (recorded_at, direction, module_id, payload) VALUES (?, ?, ?, ?)",
                (entry["timestamp"], entry["direction"], entry["module_id"], payload_blob),
            )
            _prune(conn)
            conn.commit()


def maybe_record_ws_trace(
    direction: str,
    payload: dict[str, Any],
    module_id: str | None = None,
    *,
    force: bool = False,
) -> None:
    if not (settings.ws_trace or force):
        return
    record_ws_trace(direction, payload, module_id)


def get_ws_trace(limit: int | None = None) -> list[dict[str, Any]]:
    query_limit = limit if limit is not None else 200
    query_limit = max(1, min(query_limit, MAX_TRACE_ENTRIES))
    with _connect() as conn:
        rows = conn.execute(
            "SELECT recorded_at, direction, module_id, payload FROM ws_trace_log ORDER BY id DESC LIMIT ?",
            (query_limit,),
        ).fetchall()
    entries: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row["payload"]) if row["payload"] else {}
        except json.JSONDecodeError:
            payload = {"raw": row["payload"]}
        entries.append(
            {
                "timestamp": row["recorded_at"],
                "direction": row["direction"],
                "module_id": row["module_id"],
                "payload": payload,
            }
        )
    return entries


def clear_ws_trace() -> None:
    with _db_lock:
        with _connect() as conn:
            conn.execute("DELETE FROM ws_trace_log")
            conn.commit()


def list_heater_history(
    *,
    window_minutes: int = 60,
    module_id: str | None = None,
    limit: int = 720,
) -> list[dict[str, Any]]:
    window_bound = max(1, min(window_minutes, MAX_HISTORY_WINDOW_MINUTES))
    query_limit = max(1, min(limit, MAX_TRACE_ENTRIES))
    cutoff = datetime.utcnow() - timedelta(minutes=window_bound)
    cutoff_iso = cutoff.isoformat(timespec="milliseconds")
    params: list[Any] = [cutoff_iso]
    query = [
        "SELECT recorded_at, module_id, payload",
        "FROM ws_trace_log",
        "WHERE direction = 'rx' AND recorded_at >= ?",
    ]
    if module_id:
        query.append("AND module_id = ?")
        params.append(module_id)
    query.append("ORDER BY recorded_at DESC LIMIT ?")
    params.append(query_limit)
    sql = " \n".join(query)
    with _connect() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()

    samples: list[dict[str, Any]] = []
    for row in rows:
        payload = _safe_json_load(row["payload"])
        sample = _build_heater_sample(row["recorded_at"], row["module_id"], payload)
        if sample:
            samples.append(sample)
    return list(reversed(samples))


def list_spool_history_from_trace(
    *,
    window_hours: int = 24,
    module_id: str | None = None,
    limit: int = 2000,
) -> list[dict[str, Any]]:
    window_bound = max(1, min(window_hours, 24 * 30))
    query_limit = max(1, min(limit, MAX_TRACE_ENTRIES))
    cutoff = datetime.utcnow() - timedelta(hours=window_bound)
    rows = _query_trace_rows(cutoff=cutoff, module_id=module_id, limit=query_limit)

    samples: list[dict[str, Any]] = []
    for row in rows:
        payload = _safe_json_load(row["payload"])
        sample = _build_spool_sample(row["recorded_at"], row["module_id"], payload)
        if sample:
            samples.append(sample)
    return list(reversed(samples))


def list_ato_history_from_trace(
    *,
    window_hours: int = 24,
    module_id: str | None = None,
    limit: int = 2000,
) -> list[dict[str, Any]]:
    window_bound = max(1, min(window_hours, 24 * 30))
    query_limit = max(1, min(limit, MAX_TRACE_ENTRIES))
    cutoff = datetime.utcnow() - timedelta(hours=window_bound)
    rows = _query_trace_rows(cutoff=cutoff, module_id=module_id, limit=query_limit)

    samples: list[dict[str, Any]] = []
    for row in rows:
        payload = _safe_json_load(row["payload"])
        sample = _build_ato_sample(row["recorded_at"], row["module_id"], payload)
        if sample:
            samples.append(sample)
    return list(reversed(samples))


def _query_trace_rows(*, cutoff: datetime, module_id: str | None, limit: int) -> list[sqlite3.Row]:
    cutoff_iso = cutoff.isoformat(timespec="milliseconds")
    params: list[Any] = [cutoff_iso]
    query = [
        "SELECT recorded_at, module_id, payload",
        "FROM ws_trace_log",
        "WHERE direction = 'rx' AND recorded_at >= ?",
    ]
    if module_id:
        query.append("AND module_id = ?")
        params.append(module_id)
    query.append("ORDER BY recorded_at DESC LIMIT ?")
    params.append(limit)
    sql = " \n".join(query)
    with _connect() as conn:
        return conn.execute(sql, tuple(params)).fetchall()


def _extract_status_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    if (payload.get("type") or "").lower() == "status":
        nested_payload = payload.get("payload")
        if isinstance(nested_payload, dict):
            return nested_payload
        return payload
    status_payload = payload.get("status_payload")
    if isinstance(status_payload, dict):
        return status_payload
    status = payload.get("status")
    if isinstance(status, dict):
        return status
    nested = payload.get("payload")
    if isinstance(nested, dict):
        if (nested.get("type") or "").lower() == "status":
            return nested
        nested_status_payload = nested.get("status_payload")
        if isinstance(nested_status_payload, dict):
            return nested_status_payload
        nested_status = nested.get("status")
        if isinstance(nested_status, dict):
            return nested_status
    return None


def _build_spool_sample(recorded_at: str, module_id: str | None, payload: dict[str, Any] | None) -> dict[str, Any] | None:
    status = _extract_status_payload(payload)
    if not isinstance(status, dict):
        return None
    spool = status.get("spool")
    if not isinstance(spool, dict):
        spool = _extract_subsystem_snapshot(status, ("spool", "roller", "filter"))
    if not isinstance(spool, dict):
        return None
    spool_data = _safe_dict_get(spool, "spool") or spool

    timestamp_ms = _timestamp_to_epoch_ms(recorded_at)
    if timestamp_ms is None:
        return None

    total_length_mm = _resolve_numeric(("total_length_mm", "length_mm"), spool_data)
    percent_remaining = _resolve_numeric(("percent_remaining",), spool_data)
    used_mm: float | None = None
    if total_length_mm is not None and percent_remaining is not None:
        used_mm = max(0.0, ((100.0 - percent_remaining) / 100.0) * total_length_mm)

    if used_mm is None:
        return None

    return {
        "timestamp": timestamp_ms,
        "module_id": module_id or resolve_module_id(payload or {}) or None,
        "used_mm": round(used_mm, 3),
        "percent_remaining": round(percent_remaining, 3) if percent_remaining is not None else None,
        "total_length_mm": round(total_length_mm, 3) if total_length_mm is not None else None,
    }


def _build_ato_sample(recorded_at: str, module_id: str | None, payload: dict[str, Any] | None) -> dict[str, Any] | None:
    status = _extract_status_payload(payload)
    if not isinstance(status, dict):
        return None
    ato = status.get("ato")
    if not isinstance(ato, dict):
        ato = _extract_subsystem_snapshot(status, ("ato",))
    if not isinstance(ato, dict):
        return None
    ato_data = _safe_dict_get(ato, "ato") or ato

    timestamp_ms = _timestamp_to_epoch_ms(recorded_at)
    if timestamp_ms is None:
        return None

    capacity_ml = _resolve_numeric(("tank_capacity_ml",), ato_data)
    level_ml = _resolve_numeric(("tank_level_ml",), ato_data)
    tank_percent = _resolve_numeric(("tank_percent",), ato_data)

    used_ml: float | None = None
    if capacity_ml is not None and level_ml is not None:
        used_ml = max(0.0, capacity_ml - level_ml)
    elif capacity_ml is not None and tank_percent is not None:
        used_ml = max(0.0, capacity_ml * (1.0 - tank_percent / 100.0))

    if used_ml is None:
        return None

    return {
        "timestamp": timestamp_ms,
        "module_id": module_id or resolve_module_id(payload or {}) or None,
        "used_ml": round(used_ml, 3),
        "tank_level_ml": round(level_ml, 3) if level_ml is not None else None,
        "tank_capacity_ml": round(capacity_ml, 3) if capacity_ml is not None else None,
        "tank_percent": round(tank_percent, 3) if tank_percent is not None else None,
    }


def _build_heater_sample(recorded_at: str, module_id: str | None, payload: dict[str, Any] | None) -> dict[str, Any] | None:
    status = _extract_status_payload(payload)
    if not isinstance(status, dict):
        return None
    heater = _extract_heater_snapshot(status)
    thermistors = _extract_thermistors(status, heater)
    if not thermistors:
        fallback = _resolve_numeric(
            ("primary_temp_c", "primary_c", "average_temp_c"),
            heater,
            status,
        )
        if fallback is not None:
            thermistors.append({"label": "Probe", "value": round(fallback, 3)})
    if not thermistors:
        return None
    timestamp_ms = _timestamp_to_epoch_ms(recorded_at)
    if timestamp_ms is None:
        return None
    setpoint = _resolve_numeric(
        (
            "setpoint_c",
            "target_c",
            "target",
            "average_temp_c",
            "primary_temp_c",
        ),
        heater,
        _safe_dict_get(heater, "setpoints"),
        status,
    )
    if setpoint is None:
        min_band = _resolve_numeric(
            ("setpoint_min_c", "setpoint_low_c", "minimum_c"),
            heater,
            _safe_dict_get(heater, "setpoints"),
            status,
        )
        max_band = _resolve_numeric(
            ("setpoint_max_c", "setpoint_high_c", "maximum_c"),
            heater,
            _safe_dict_get(heater, "setpoints"),
            status,
        )
        if min_band is not None and max_band is not None:
            setpoint = (min_band + max_band) / 2

    return {
        "timestamp": timestamp_ms,
        "module_id": module_id or resolve_module_id(payload),
        "setpoint": round(setpoint, 3) if setpoint is not None else None,
        "heater_on": _determine_heater_active(heater, status),
        "thermistors": thermistors,
    }


def _extract_heater_snapshot(payload: dict[str, Any]) -> dict[str, Any] | None:
    heater = payload.get("heater")
    if isinstance(heater, dict):
        return heater
    subsystem = _extract_subsystem_snapshot(payload, ("heater",))
    if isinstance(subsystem, dict):
        return subsystem
    heaters = payload.get("heaters")
    if isinstance(heaters, list):
        for entry in heaters:
            if isinstance(entry, dict):
                return entry
    return None


def _extract_thermistors(payload: dict[str, Any], heater: dict[str, Any] | None) -> list[dict[str, Any]]:
    readings: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    if heater:
        sources.append(heater)
    sources.append(payload)
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("thermistors", "thermistors_c", "temps_c"):
            entries = source.get(key)
            if not isinstance(entries, list):
                continue
            readings.extend(_normalize_probe_entries(entries, len(readings)))
        sensors = source.get("sensors")
        if isinstance(sensors, list):
            readings.extend(_normalize_probe_entries(sensors, len(readings)))
    return readings[:8]


def _extract_subsystem_snapshot(status: dict[str, Any], kinds: tuple[str, ...]) -> dict[str, Any] | None:
    entries = status.get("subsystems")
    if not isinstance(entries, list):
        return None
    kind_set = {item.lower() for item in kinds}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        kind_value = str(entry.get("kind") or "").lower()
        key_value = str(entry.get("key") or "").lower()
        if kind_value in kind_set or key_value in kind_set:
            return entry
    return None


def _safe_dict_get(source: dict[str, Any] | None, key: str) -> dict[str, Any] | None:
    if not isinstance(source, dict):
        return None
    value = source.get(key)
    return value if isinstance(value, dict) else None


def _normalize_probe_entries(entries: list[Any], start_index: int) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for offset, entry in enumerate(entries):
        index = start_index + offset
        if isinstance(entry, (int, float)):
            normalized.append({"label": f"Probe {index + 1}", "value": round(float(entry), 3)})
            continue
        if isinstance(entry, dict):
            label = entry.get("label") or entry.get("sensor") or f"Probe {index + 1}"
            numeric = _resolve_numeric(("value", "value_c", "c", "temp", "temp_c"), entry)
            if numeric is None and isinstance(entry.get("reading"), (int, float, str)):
                numeric = _coerce_number(entry.get("reading"))
            if numeric is None:
                continue
            normalized.append({"label": str(label), "value": round(numeric, 3)})
    return normalized


def _determine_heater_active(heater: dict[str, Any] | None, payload: dict[str, Any] | None) -> bool:
    numeric = _resolve_numeric(("output", "power", "duty", "duty_cycle"), heater)
    if numeric is not None:
        return numeric > 0.01
    for source in (heater, payload):
        if not isinstance(source, dict):
            continue
        flag = source.get("heater_on") or source.get("active") or source.get("heater_active")
        if isinstance(flag, bool):
            return flag
        if isinstance(flag, (int, float)):
            return flag > 0
        if isinstance(flag, str):
            lowered = flag.strip().lower()
            if lowered in {"on", "heating", "active", "true", "yes"}:
                return True
            if lowered in {"off", "idle", "false", "no"}:
                return False
        state = source.get("state")
        if isinstance(state, str):
            lowered_state = state.lower()
            if "heat" in lowered_state or lowered_state in {"on", "active"}:
                return True
    return False


def _resolve_numeric(keys: tuple[str, ...], *sources: dict[str, Any] | None) -> float | None:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            if key not in source:
                continue
            numeric = _coerce_number(source.get(key))
            if numeric is not None:
                return numeric
    return None


def _coerce_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _timestamp_to_epoch_ms(value: str | None) -> int | None:
    if not value:
        return None
    normalized = value
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    elif "+" not in normalized and "-" not in normalized[10:]:
        normalized = f"{normalized}+00:00"
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return int(dt.timestamp() * 1000)


def _safe_json_load(blob: str | None) -> dict[str, Any]:
    if not blob:
        return {}
    try:
        data = json.loads(blob)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {"raw": blob}


_initialize()
