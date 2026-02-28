from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

import anyio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..services.connection_manager import manager
from ..core.config import settings
from ..services.cycle_log import record_cycle_log
from ..services.module_identity import resolve_module_id
from ..services.module_status import (
    apply_ato_activations,
    apply_spool_activations,
    mark_module_offline,
    record_module_alarm,
    upsert_module_config,
    upsert_module_manifest,
    upsert_module_status,
)
from ..services.ws_trace import maybe_record_ws_trace

logger = logging.getLogger(__name__)

ws_router = APIRouter()


DEFAULT_CONFIG = {
    "motor": {
        "max_speed": 255,
        "run_time_ms": 5000,
        "ramp_up_ms": 1000,
        "ramp_down_ms": 1000,
    },
    "ato": {
        "mode": 0,
        "timeout_ms": 300_000,
        "pump_running": False,
        "pump_speed": 255,
        "timeout_alarm": False,
    },
    "system": {
        "chirp_enabled": True,
        "pump_timeout_ms": 120_000,
        "startup_delay_ms": 5000,
    },
}


@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Bidirectional bridge for hardware modules."""

    await websocket.accept()
    module_id: str | None = None
    logger.info("WebSocket accepted from %s", websocket.client)
    config_request = {"type": "config_request"}
    await websocket.send_json(config_request)
    maybe_record_ws_trace("tx", config_request, module_id)
    manifest_request = {"type": "module_manifest_request"}
    await websocket.send_json(manifest_request)
    maybe_record_ws_trace("tx", manifest_request, module_id)

    frame_queue: asyncio.Queue[tuple[str | None, dict[str, Any] | None, str | None]] = asyncio.Queue()
    receiver_task = asyncio.create_task(_receive_module_frames(websocket, frame_queue))

    try:
        while True:
            msg_type, normalized_payload, frame_module_id = await frame_queue.get()
            if msg_type is None:
                if frame_module_id:
                    module_id = frame_module_id
                if module_id:
                    manager.unregister(module_id)
                    await mark_module_offline(module_id)
                break

            if frame_module_id and frame_module_id != "unknown":
                module_id = frame_module_id

            try:
                with anyio.CancelScope(shield=True):
                    module_id = await _handle_module_message(
                        msg_type,
                        normalized_payload,
                        module_id,
                        websocket,
                    )
            except asyncio.CancelledError:
                logger.debug("Message handling cancelled for %s", module_id or "unknown")
                continue
    except WebSocketDisconnect:
        if module_id:
            manager.unregister(module_id)
            await mark_module_offline(module_id)
        logger.info("Module %s disconnected", module_id or "unknown")
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("WebSocket error: %s", exc)
        if module_id:
            manager.unregister(module_id)
            await mark_module_offline(module_id)
        await websocket.close()
    finally:
        if not receiver_task.done():
            receiver_task.cancel()
        with contextlib.suppress(Exception):
            remaining_module_id = await receiver_task
            if remaining_module_id:
                module_id = remaining_module_id


def _build_config_response(module_id: str) -> dict[str, Any]:
    """Return a basic config payload for modules that request it."""

    response = {
        "module": module_id,
        "type": "config",
    }
    response.update(DEFAULT_CONFIG)
    return response


def _normalize_incoming_frame(message: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    msg_type = message.get("type") if isinstance(message, dict) else None
    if not isinstance(message, dict):
        return msg_type, {}

    payload = message.get("payload") if isinstance(message.get("payload"), dict) else None
    defaults = _build_envelope_defaults(message)

    if payload is None:
        normalized = dict(message)
        return msg_type, normalized

    if msg_type == "alarm":
        normalized = dict(defaults)
        normalized["alarm"] = dict(payload)
        return msg_type, normalized

    normalized = dict(payload)
    _apply_envelope_defaults(normalized, defaults)
    return msg_type, normalized


def _build_envelope_defaults(message: dict[str, Any]) -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    module_id = message.get("module_id")
    if isinstance(module_id, str) and module_id.strip():
        defaults["module"] = module_id
        defaults["module_id"] = module_id
    submodule_id = message.get("submodule_id")
    if isinstance(submodule_id, str) and submodule_id.strip():
        defaults["submodule_id"] = submodule_id
    protocol = message.get("protocol")
    if isinstance(protocol, str) and protocol.strip():
        defaults["protocol"] = protocol
    sent_at = message.get("sent_at")
    if isinstance(sent_at, str) and sent_at.strip():
        defaults["sent_at"] = sent_at
        defaults.setdefault("timestamp", sent_at)
        defaults.setdefault("recorded_at", sent_at)
    return defaults


def _apply_envelope_defaults(target: dict[str, Any], defaults: dict[str, Any]) -> None:
    for key, value in defaults.items():
        target.setdefault(key, value)


async def _handle_module_message(
    msg_type: str | None,
    normalized_payload: dict[str, Any] | None,
    module_id: str | None,
    websocket: WebSocket,
) -> str | None:
    if msg_type == "status":
        logger.info("Status frame %s", normalized_payload)
        module = await upsert_module_status(
            normalized_payload or {},
            client_ip=websocket.client.host if websocket.client else None,
        )
        manager.register(module.module_id, websocket)
        return module.module_id

    if msg_type == "config_request" and module_id:
        response = _build_config_response(module_id)
        await manager.send(module_id, response)
        maybe_record_ws_trace("tx", response, module_id)
        return module_id

    if msg_type == "config" and module_id:
        await upsert_module_config(module_id, normalized_payload or {})
        logger.info("Config response from %s: %s", module_id, normalized_payload)
        return module_id

    if msg_type == "module_manifest":
        await upsert_module_manifest(module_id, normalized_payload or {})
        logger.info("Manifest update from %s: %s", module_id or "unknown", normalized_payload)
        return module_id

    if msg_type == "cycle_log":
        await record_cycle_log(normalized_payload or {})
        logger.info("Cycle log from %s: %s", module_id or "unknown", normalized_payload)
        return module_id

    if msg_type == "alarm":
        await record_module_alarm(normalized_payload or {}, module_id)
        logger.info("Alarm event from %s: %s", module_id or "unknown", normalized_payload)
        return module_id

    if msg_type == "spool_activations":
        await apply_spool_activations(normalized_payload or {}, module_id)
        logger.info("Spool activations update from %s: %s", module_id or "unknown", normalized_payload)
        return module_id

    if msg_type == "ato_activations":
        await apply_ato_activations(normalized_payload or {}, module_id)
        logger.info("ATO activations update from %s: %s", module_id or "unknown", normalized_payload)
        return module_id

    logger.debug("Unhandled module message: %s", normalized_payload)
    return module_id


async def _receive_module_frames(
    websocket: WebSocket,
    queue: asyncio.Queue[tuple[str | None, dict[str, Any] | None, str | None]],
) -> str | None:
    module_id: str | None = None
    try:
        while True:
            payload = await websocket.receive_json()
            msg_type, normalized_payload = _normalize_incoming_frame(payload)
            if settings.ws_trace:
                logger.info("WS RX %s", payload)

            resolved_id = resolve_module_id(normalized_payload or payload, module_id)
            if resolved_id and resolved_id != "unknown":
                module_id = resolved_id

            maybe_record_ws_trace("rx", payload, module_id, force=msg_type == "status")
            await queue.put((msg_type, normalized_payload, module_id))
    except WebSocketDisconnect:
        await queue.put((None, None, module_id))
        return module_id
    except Exception:
        await queue.put((None, None, module_id))
        raise
