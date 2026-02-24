from datetime import datetime
from typing import Any, Literal, Optional

from sqlalchemy import Column, JSON
from sqlmodel import SQLModel, Field
from pydantic import ConfigDict


SPOOL_LENGTH_MIN_MM = 10_000
SPOOL_LENGTH_MAX_MM = 200_000
MEDIA_THICKNESS_MIN_UM = 40
MEDIA_THICKNESS_MAX_UM = 400
SPOOL_CORE_DIAMETER_MIN_MM = 12
SPOOL_CORE_DIAMETER_MAX_MM = 80


class ModuleStatus(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    module_id: str = Field(index=True, unique=True)
    label: str = Field(default="Unnamed module")
    firmware_version: str | None = None
    ip_address: str | None = None
    rssi: int | None = None
    status: str = "offline"
    last_seen: datetime = Field(default_factory=datetime.utcnow, index=True)
    status_payload: dict | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description="Last status frame reported by the module",
    )
    config_payload: dict | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description="Last config payload reported by the module",
    )
    alarms: list[dict[str, Any]] | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description="Latest alarm states streamed from the module",
    )


class ModuleStatusRead(SQLModel, table=False):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    module_id: str
    label: str = "Unnamed module"
    firmware_version: str | None = None
    ip_address: str | None = None
    rssi: int | None = None
    status: str = "offline"
    last_seen: datetime | None = None
    status_payload: dict | None = None
    config_payload: dict | None = None
    alarms: list[dict[str, Any]] | None = None
    spool_state: dict | None = None


class ModuleUpdate(SQLModel):
    label: str | None = None
    firmware_version: str | None = None
    ip_address: str | None = None
    rssi: int | None = None
    status: str | None = None
    last_seen: datetime | None = None


class ModuleControlRequest(SQLModel):
    ato_mode: Literal["auto", "manual", "paused"] | None = None
    motor_run_time_ms: int | None = Field(
        default=None,
        ge=1000,
        le=30000,
        description="Duration the roller should run after a trigger (milliseconds)",
    )
    roller_speed: int | None = Field(
        default=None,
        ge=50,
        le=255,
        description="PWM setpoint for the roller motor (50-255)",
    )
    pump_speed: int | None = Field(
        default=None,
        ge=0,
        le=255,
        description="PWM setpoint for the ATO pump (0-255)",
    )
    pump_timeout_ms: int | None = Field(
        default=None,
        ge=60_000,
        le=600_000,
        description="Duration the ATO pump continues after a trigger (milliseconds)",
    )
    reset_spool: bool | None = Field(
        default=None,
        description="When true the module should zero roller usage and mark the spool as full",
    )
    spool_length_mm: int | None = Field(
        default=None,
        ge=SPOOL_LENGTH_MIN_MM,
        le=SPOOL_LENGTH_MAX_MM,
        description="Full roll length in millimetres for calibration math",
    )
    spool_media_thickness_um: int | None = Field(
        default=None,
        ge=MEDIA_THICKNESS_MIN_UM,
        le=MEDIA_THICKNESS_MAX_UM,
        description="Filter media thickness in microns used by the wrap model",
    )
    spool_core_diameter_mm: float | None = Field(
        default=None,
        ge=SPOOL_CORE_DIAMETER_MIN_MM,
        le=SPOOL_CORE_DIAMETER_MAX_MM,
        description="Core or shaft diameter in millimetres for the geometric model",
    )
    spool_calibrate_start: bool | None = Field(
        default=None,
        description="Begin the 10 m calibration pull sequence",
    )
    spool_calibrate_finish: int | None = Field(
        default=None,
        ge=0,
        le=SPOOL_LENGTH_MAX_MM,
        description="Finish calibration using the supplied roll length (0 reuses stored length)",
    )
    spool_calibrate_cancel: bool | None = Field(
        default=None,
        description="Abort calibration without persisting changes",
    )
