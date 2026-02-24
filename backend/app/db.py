from sqlalchemy import inspect, text
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from .core.config import settings


def get_engine():
    return create_async_engine(settings.database_url, echo=False, future=True)


engine = get_engine()
SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        await _ensure_module_payload_columns(conn)


async def _ensure_module_payload_columns(conn) -> None:
    from .schemas.module import ModuleStatus  # Imported lazily to avoid cycles.

    table_name = ModuleStatus.__tablename__

    def missing_columns(sync_conn) -> set[str]:
        inspector = inspect(sync_conn)
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        required = {"status_payload", "config_payload", "alarms"}
        return required - columns

    missing = await conn.run_sync(missing_columns)
    if not missing:
        return

    safe_table = table_name.replace('"', '""')
    for column in missing:
        await conn.execute(text(f'ALTER TABLE "{safe_table}" ADD COLUMN {column} JSON'))
