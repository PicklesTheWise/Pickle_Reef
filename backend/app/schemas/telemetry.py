from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field


class Telemetry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    module_id: str
    metric: str
    value: float
    unit: str | None = None
    captured_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class TelemetryCreate(SQLModel):
    module_id: str
    metric: str
    value: float
    unit: str | None = None
    captured_at: datetime | None = None
