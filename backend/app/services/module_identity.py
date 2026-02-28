from __future__ import annotations

from typing import Any

MODULE_ID_KEYS = (
    "module",
    "module_id",
    "id",
    "device_id",
    "device",
)


def resolve_module_id(payload: dict[str, Any] | None, fallback: str | None = "unknown") -> str:
    """Extract a stable module identifier from mixed payload styles."""

    if not isinstance(payload, dict):
        return fallback or "unknown"
    for key in MODULE_ID_KEYS:
        if key not in payload:
            continue
        candidate = payload[key]
        normalized = _normalize_module_value(candidate)
        if normalized:
            return normalized
    return fallback or "unknown"


def _normalize_module_value(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, (int, float)):
        return str(value)
    return None
