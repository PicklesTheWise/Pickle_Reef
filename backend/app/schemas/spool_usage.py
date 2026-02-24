from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class SpoolUsageLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    module_id: str = Field(index=True)
    delta_edges: float | None = None
    delta_mm: float | None = None
    total_used_edges: float | None = None
    recorded_at: datetime = Field(default_factory=datetime.utcnow, index=True)
