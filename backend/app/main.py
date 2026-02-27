import asyncio
import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler

from .api.routes import router
from .api.websocket import ws_router
from .core.config import settings
from .db.session import close_db, init_db
from .services.mqtt import mqtt_bootstrap
from .services.module_status import (
    drain_module_persistence,
    hydrate_module_store_from_db,
    purge_legacy_modules,
)
from .services.spool_usage import rehydrate_spool_usage_history


def _configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        force=True,
    )


_configure_logging()

app = FastAPI(title="Pickle Reef API")
validation_logger = logging.getLogger("picklereef.validation")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(ws_router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
        body = await request.body()
        preview = body[:2048]
        decoded = preview.decode("utf-8", errors="replace") if preview else ""
        validation_logger.warning(
                "Request validation failed path=%s errors=%s body=%s",
                request.url.path,
                exc.errors(),
                decoded,
        )
        return await request_validation_exception_handler(request, exc)


@app.on_event("startup")
async def startup_event() -> None:
    await init_db()
    await hydrate_module_store_from_db()
    await purge_legacy_modules()
    await rehydrate_spool_usage_history()
    asyncio.create_task(mqtt_bootstrap())


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await drain_module_persistence()
    await close_db()


@app.get("/")
async def root():
    return {"message": "Pickle Reef backend online"}
