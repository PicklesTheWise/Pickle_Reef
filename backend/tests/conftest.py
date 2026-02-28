import asyncio

import pytest

from app.services.cycle_log import clear_cycle_logs
from app.services.module_status import reset_module_store
from app.services.module_snapshot import clear_module_snapshots
from app.services.spool_usage import reset_spool_usage_entries
from app.services.telemetry_store import clear_telemetry_entries


@pytest.fixture(autouse=True)
def reset_in_memory_state():
    reset_module_store()
    asyncio.run(reset_spool_usage_entries())
    asyncio.run(clear_cycle_logs())
    asyncio.run(clear_module_snapshots())
    clear_telemetry_entries()
    yield
    reset_module_store()
    asyncio.run(reset_spool_usage_entries())
    asyncio.run(clear_cycle_logs())
    asyncio.run(clear_module_snapshots())
    clear_telemetry_entries()
