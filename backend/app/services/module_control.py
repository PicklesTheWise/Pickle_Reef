from __future__ import annotations

import logging

from fastapi import HTTPException, status

from ..schemas.module import ModuleControlRequest, SPOOL_LENGTH_MIN_MM
from .connection_manager import manager
from .ws_trace import maybe_record_ws_trace

logger = logging.getLogger(__name__)

ATO_MODE_MAP = {
    "auto": 0,
    "manual": 1,
    "paused": 2,
}

PROTOCOL = "reefnet.v1"
CONTROL_TYPE = "control"


def _build_command_envelope(module_id: str, command: str, parameters: dict | None = None) -> dict:
    payload: dict[str, object] = {"command": command}
    if parameters:
        payload["parameters"] = parameters
    return {
        "protocol": PROTOCOL,
        "module_id": module_id,
        "type": CONTROL_TYPE,
        "payload": payload,
    }


def _build_set_parameter_command(module_id: str, param: str, value) -> dict:
    return _build_command_envelope(
        module_id,
        "set_parameter",
        {
            "name": param,
            "param": param,
            "value": value,
        },
    )


async def apply_module_controls(module_id: str, request: ModuleControlRequest) -> dict[str, int]:
    if not manager.is_connected(module_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Module {module_id} is not connected",
        )

    commands: list[dict] = []

    if request.ato_mode is not None:
        commands.append(
            _build_command_envelope(module_id, "set_ato_mode", {"mode": ATO_MODE_MAP[request.ato_mode]})
        )

    if request.motor_run_time_ms is not None:
        commands.append(_build_set_parameter_command(module_id, "motor_runtime", request.motor_run_time_ms))

    if request.roller_speed is not None:
        commands.append(_build_set_parameter_command(module_id, "motor_speed", request.roller_speed))

    if request.pump_speed is not None:
        commands.append(_build_set_parameter_command(module_id, "pump_speed", request.pump_speed))

    if request.pump_timeout_ms is not None:
        commands.append(_build_set_parameter_command(module_id, "pump_timeout_ms", request.pump_timeout_ms))

    if request.reset_spool:
        commands.append(_build_command_envelope(module_id, "spool_reset"))

    if request.spool_length_mm is not None:
        commands.append(_build_set_parameter_command(module_id, "spool_length_mm", request.spool_length_mm))

    if request.spool_media_thickness_um is not None:
        commands.append(
            _build_set_parameter_command(module_id, "spool_media_thickness_um", request.spool_media_thickness_um)
        )

    if request.spool_core_diameter_mm is not None:
        commands.append(
            _build_set_parameter_command(module_id, "spool_core_diameter_mm", request.spool_core_diameter_mm)
        )

    if request.spool_calibrate_start:
        commands.append(_build_command_envelope(module_id, "spool_calibrate_start"))

    if request.spool_calibrate_finish is not None:
        finish_value = request.spool_calibrate_finish
        if finish_value not in (0,) and finish_value < SPOOL_LENGTH_MIN_MM:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"spool_calibrate_finish must be 0 or >= {SPOOL_LENGTH_MIN_MM}",
            )
        commands.append(
            _build_command_envelope(module_id, "spool_calibrate_finish", {"roll_length_mm": finish_value})
        )

    if request.spool_calibrate_cancel:
        commands.append(_build_command_envelope(module_id, "spool_calibrate_cancel"))

    if request.ato_tank_capacity_ml is not None:
        commands.append(_build_set_parameter_command(module_id, "ato_tank_capacity_ml", request.ato_tank_capacity_ml))

    if request.ato_tank_level_ml is not None:
        commands.append(_build_set_parameter_command(module_id, "ato_tank_level_ml", request.ato_tank_level_ml))

    if request.ato_tank_refill:
        commands.append(_build_command_envelope(module_id, "ato_tank_refill"))

    if request.heater_setpoint_c is not None:
        commands.append(_build_set_parameter_command(module_id, "setpoint_c", request.heater_setpoint_c))

    if request.heater_hysteresis_span_c is not None:
        commands.append(
            _build_set_parameter_command(module_id, "hysteresis_span_c", request.heater_hysteresis_span_c)
        )

    if request.probe_tolerance_c is not None:
        commands.append(_build_set_parameter_command(module_id, "probe_tolerance_c", request.probe_tolerance_c))

    if request.probe_timeout_s is not None:
        commands.append(_build_set_parameter_command(module_id, "probe_timeout_s", request.probe_timeout_s))

    if request.runaway_delta_c is not None:
        commands.append(_build_set_parameter_command(module_id, "runaway_delta_c", request.runaway_delta_c))

    if request.max_heater_on_min is not None:
        commands.append(_build_set_parameter_command(module_id, "max_heater_on_min", request.max_heater_on_min))

    if request.stuck_relay_delta_c is not None:
        commands.append(
            _build_set_parameter_command(module_id, "stuck_relay_delta_c", request.stuck_relay_delta_c)
        )

    if request.stuck_relay_window_s is not None:
        commands.append(
            _build_set_parameter_command(module_id, "stuck_relay_window_s", request.stuck_relay_window_s)
        )

    if request.alarm_snooze:
        commands.append(_build_command_envelope(module_id, "alarm_snooze"))

    if request.heater_setpoint_min_c is not None:
        commands.append(_build_set_parameter_command(module_id, "heater_setpoint_min_c", request.heater_setpoint_min_c))

    if request.heater_setpoint_max_c is not None:
        commands.append(_build_set_parameter_command(module_id, "heater_setpoint_max_c", request.heater_setpoint_max_c))

    if not commands:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No control values supplied")

    sent = 0
    for payload in commands:
        logger.info("Sending command to %s: %s", module_id, payload)
        success = await manager.send(module_id, payload)
        if success:
            sent += 1
            maybe_record_ws_trace("tx", payload, module_id)

    if sent == 0:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Module not ready for commands")

    return {"commands_sent": sent}
