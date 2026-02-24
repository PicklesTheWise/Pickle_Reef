from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field


class CycleLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    module_id: str = Field(index=True)
    cycle_type: str = Field(index=True)
    trigger: str | None = None
    duration_ms: int | None = None
    timeout: bool = False
    module_timestamp_s: int | None = None
    recorded_at: datetime = Field(default_factory=datetime.utcnow, index=True)
