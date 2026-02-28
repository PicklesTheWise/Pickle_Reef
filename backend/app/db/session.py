from __future__ import annotations

from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from ..core.config import settings


def _build_engine() -> AsyncEngine:
    return create_async_engine(settings.database_url, future=True, echo=False)


def _build_session_factory(engine: AsyncEngine) -> sessionmaker[AsyncSession]:
    return sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)


engine: AsyncEngine = _build_engine()
async_session_factory: sessionmaker[AsyncSession] = _build_session_factory(engine)


async def init_db() -> None:
    """Create database tables if they do not already exist."""

    # Import models so SQLModel is aware of them before create_all runs.
    from ..schemas import cycle, module, module_snapshot, spool_usage, telemetry  # noqa: F401

    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)


async def close_db() -> None:
    """Dispose of the async engine and close all connections."""

    await engine.dispose()


@asynccontextmanager
async def get_session() -> AsyncSession:
    session: AsyncSession = async_session_factory()
    try:
        yield session
    finally:
        await session.close()
