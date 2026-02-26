from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..services.connection_manager import manager
from ..core.config import settings
from ..services.cycle_log import record_cycle_log
from ..services.module_status import (
    apply_spool_activations,
    mark_module_offline,
    record_module_alarm,
    upsert_module_config,
    upsert_module_manifest,
    upsert_module_status,
)
from ..services.ws_trace import record_ws_trace

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
    if settings.ws_trace:
        record_ws_trace("tx", config_request, module_id)
    manifest_request = {"type": "module_manifest_request"}
    await websocket.send_json(manifest_request)
    if settings.ws_trace:
        record_ws_trace("tx", manifest_request, module_id)

    try:
        while True:
            payload = await websocket.receive_json()
            if settings.ws_trace:
                logger.info("WS RX %s", payload)
                record_ws_trace("rx", payload, module_id)
            msg_type = payload.get("type")
            maybe_module = payload.get("module")
            if maybe_module:
                module_id = maybe_module

            if msg_type == "status":
                logger.info("Status frame %s", payload)
                module = await upsert_module_status(
                    payload,
                    client_ip=websocket.client.host if websocket.client else None,
                )
                manager.register(module.module_id, websocket)
            elif msg_type == "config_request" and module_id:
                response = _build_config_response(module_id)
                await manager.send(module_id, response)
                if settings.ws_trace:
                    record_ws_trace("tx", response, module_id)
            elif msg_type == "config" and module_id:
                await upsert_module_config(module_id, payload)
                logger.info("Config response from %s: %s", module_id, payload)
            elif msg_type == "module_manifest":
                await upsert_module_manifest(module_id, payload)
                logger.info("Manifest update from %s: %s", module_id or "unknown", payload)
            elif msg_type == "cycle_log":
                await record_cycle_log(payload)
                logger.info("Cycle log from %s: %s", module_id or "unknown", payload)
            elif msg_type == "alarm":
                await record_module_alarm(payload)
                logger.info("Alarm event from %s: %s", module_id or "unknown", payload)
            elif msg_type == "spool_activations":
                await apply_spool_activations(payload)
                logger.info("Spool activations update from %s: %s", module_id or "unknown", payload)
            else:
                logger.debug("Unhandled module message: %s", payload)
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


def _build_config_response(module_id: str) -> dict[str, Any]:
    """Return a basic config payload for modules that request it."""

    response = {
        "module": module_id,
        "type": "config",
    }
    response.update(DEFAULT_CONFIG)
    return response
