import pytest
from datetime import datetime, timedelta

from httpx import ASGITransport, AsyncClient
from sqlmodel import delete

from app.db import SessionLocal
from app.main import app
from app.schemas.cycle import CycleLog


@pytest.mark.asyncio
async def test_cycle_history_endpoint_filters_and_summarizes():
    async with SessionLocal() as session:
        await session.exec(delete(CycleLog))
        session.add_all(
            [
                CycleLog(
                    module_id="reef-roller-1",
                    cycle_type="roller_auto",
                    trigger="main_float",
                    duration_ms=3200,
                    recorded_at=datetime.utcnow() - timedelta(hours=2),
                ),
                CycleLog(
                    module_id="reef-roller-1",
                    cycle_type="pump_normal",
                    trigger="min_float",
                    duration_ms=7800,
                    recorded_at=datetime.utcnow() - timedelta(hours=1),
                ),
                CycleLog(
                    module_id="reef-roller-1",
                    cycle_type="roller_auto",
                    trigger="manual_button",
                    duration_ms=2100,
                    recorded_at=datetime.utcnow() - timedelta(days=10),
                ),
            ]
        )
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/cycles/history?window_hours=24")
        assert response.status_code == 200
        data = response.json()
        assert data["roller_stats"]["count"] == 1
        assert data["ato_stats"]["count"] == 1
        assert data["roller_runs"][0]["duration_ms"] == 3200
        assert data["ato_stats"]["avg_fill_seconds"] == pytest.approx(7.8, rel=0.01)