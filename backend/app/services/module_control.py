from __future__ import annotations

import logging

from fastapi import HTTPException, status

from ..schemas.module import ModuleControlRequest, SPOOL_LENGTH_MIN_MM
from ..core.config import settings
from .connection_manager import manager
from .ws_trace import record_ws_trace

logger = logging.getLogger(__name__)

ATO_MODE_MAP = {
    "auto": 0,
    "manual": 1,
    "paused": 2,
}


async def apply_module_controls(module_id: str, request: ModuleControlRequest) -> dict[str, int]:
    if not manager.is_connected(module_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Module {module_id} is not connected",
        )

    commands: list[dict] = []

    if request.ato_mode is not None:
        commands.append({"type": "set_param", "param": "ato_mode", "value": ATO_MODE_MAP[request.ato_mode]})

    if request.motor_run_time_ms is not None:
        commands.append({"type": "set_param", "param": "motor_runtime", "value": request.motor_run_time_ms})

    if request.roller_speed is not None:
        commands.append({"type": "set_param", "param": "motor_speed", "value": request.roller_speed})

    if request.pump_speed is not None:
        commands.append({"type": "set_param", "param": "pump_speed", "value": request.pump_speed})

    if request.pump_timeout_ms is not None:
        commands.append({"type": "set_param", "param": "pump_timeout_ms", "value": request.pump_timeout_ms})

    if request.reset_spool:
        commands.append({"type": "set_param", "param": "spool_reset", "value": 1})

    if request.spool_length_mm is not None:
        commands.append({
            "type": "set_param",
            "param": "spool_length_mm",
            "value": request.spool_length_mm,
        })

    if request.spool_media_thickness_um is not None:
        commands.append({
            "type": "set_param",
            "param": "spool_media_thickness_um",
            "value": request.spool_media_thickness_um,
        })

    if request.spool_core_diameter_mm is not None:
        commands.append({
            "type": "set_param",
            "param": "spool_core_diameter_mm",
            "value": request.spool_core_diameter_mm,
        })

    if request.spool_calibrate_start:
        commands.append({"type": "set_param", "param": "spool_calibrate_start", "value": 1})

    if request.spool_calibrate_finish is not None:
        finish_value = request.spool_calibrate_finish
        if finish_value not in (0,) and finish_value < SPOOL_LENGTH_MIN_MM:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"spool_calibrate_finish must be 0 or >= {SPOOL_LENGTH_MIN_MM}",
            )
        commands.append({
            "type": "set_param",
            "param": "spool_calibrate_finish",
            "value": finish_value,
        })

    if request.spool_calibrate_cancel:
        commands.append({"type": "set_param", "param": "spool_calibrate_cancel", "value": 1})

    if not commands:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No control values supplied")

    sent = 0
    for payload in commands:
        logger.info("Sending command to %s: %s", module_id, payload)
        success = await manager.send(module_id, payload)
        if success:
            sent += 1
            if settings.ws_trace:
                record_ws_trace("tx", payload, module_id)

    if sent == 0:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Module not ready for commands")

    return {"commands_sent": sent}
