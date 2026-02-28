from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class ModuleSnapshot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    module_id: str = Field(index=True)
    payload: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    recorded_at: datetime = Field(default_factory=datetime.utcnow, index=True)
