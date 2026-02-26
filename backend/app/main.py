import asyncio
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router
from .api.websocket import ws_router
from .core.config import settings
from .services.mqtt import mqtt_bootstrap
from .services.module_status import purge_legacy_modules


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(ws_router)


@app.on_event("startup")
async def startup_event() -> None:
    await purge_legacy_modules()
    asyncio.create_task(mqtt_bootstrap())


@app.get("/")
async def root():
    return {"message": "Pickle Reef backend online"}
