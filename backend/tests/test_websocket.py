import asyncio

from fastapi.testclient import TestClient

from app.main import app
from app.services.module_status import (
    apply_spool_activations,
    apply_spool_tick,
    record_module_alarm,
    upsert_module_status,
)

client = TestClient(app)


def test_websocket_accepts_status_payload():
    with client.websocket_connect("/ws") as websocket:
        hello = websocket.receive_json()
        assert hello["type"] == "config_request"

        payload = {
            "module": "TestModule",
            "type": "status",
            "motor": {
                "state": "stopped",
                "speed": 0,
                "runtime_ms": 0,
                "mode": "auto",
            },
            "floats": {"main": False, "min": False, "max": False},
            "ato": {
                "pump_running": False,
                "manual_mode": False,
                "paused": False,
                "timeout_alarm": False,
            },
            "system": {"chirp_enabled": True, "uptime_s": 1},
        }
        websocket.send_json(payload)
        # allow server to process without expecting another message


def test_alarm_payload_persists_in_module_record():
    module_id = "AlarmTester"
    asyncio.run(
        upsert_module_status(
            {
                "module": module_id,
                "type": "status",
                "motor": {"state": "running", "speed": 100, "runtime_ms": 500, "mode": "auto"},
                "floats": {"main": True, "min": False, "max": False},
                "ato": {
                    "pump_running": True,
                    "manual_mode": False,
                    "paused": False,
                    "timeout_alarm": False,
                },
                "system": {"chirp_enabled": True, "uptime_s": 42},
            }
        )
    )
    asyncio.run(
        record_module_alarm(
            {
                "module": module_id,
                "type": "alarm",
                "alarm": {
                    "code": "pump_timeout",
                    "severity": "warning",
                    "active": True,
                    "timestamp_s": 1337,
                    "message": "ATO pump exceeded pump_timeout_ms",
                    "meta": {"timeout_ms": 120000, "runtime_ms": 135000},
                },
            }
        )
    )

    response = client.get("/api/modules")
    response.raise_for_status()
    module_records = response.json()
    target = next((entry for entry in module_records if entry["module_id"] == module_id), None)
    assert target is not None
    assert target["alarms"]
    alarm = target["alarms"][0]
    assert alarm["code"] == "pump_timeout"
    assert alarm["severity"] == "warning"
    assert alarm["active"] is True


def test_spool_activations_updates_activation_counter():
    module_id = "SpoolTickTester"
    asyncio.run(
        upsert_module_status(
            {
                "module": module_id,
                "type": "status",
                "motor": {"state": "stopped", "speed": 0, "runtime_ms": 0, "mode": "auto"},
                "floats": {"main": False, "min": False, "max": False},
                "ato": {
                    "pump_running": False,
                    "manual_mode": False,
                    "paused": False,
                    "timeout_alarm": False,
                },
                "system": {"chirp_enabled": True, "uptime_s": 10},
                "spool": {"full_edges": 1000, "used_edges": 0, "percent_remaining": 100},
            }
        )
    )
    asyncio.run(
        apply_spool_activations(
            {
                "module": module_id,
                "type": "spool_activations",
                "activations": 7,
                "percent_remaining": 98,
            }
        )
    )

    response = client.get("/api/modules")
    response.raise_for_status()
    module_records = response.json()
    target = next((entry for entry in module_records if entry["module_id"] == module_id), None)
    assert target is not None
    spool_state = target.get("spool_state")
    assert spool_state is not None
    assert spool_state.get("activations") == 7
    assert spool_state.get("percent_remaining") == 98


def test_spool_activations_uses_count_alias():
    module_id = "SpoolTickCountAlias"
    asyncio.run(
        upsert_module_status(
            {
                "module": module_id,
                "type": "status",
                "motor": {"state": "stopped", "speed": 0, "runtime_ms": 0, "mode": "auto"},
                "floats": {"main": False, "min": False, "max": False},
                "ato": {
                    "pump_running": False,
                    "manual_mode": False,
                    "paused": False,
                    "timeout_alarm": False,
                },
                "system": {"chirp_enabled": True, "uptime_s": 10},
                "spool": {"full_edges": 1000, "used_edges": 0, "percent_remaining": 100},
            }
        )
    )
    asyncio.run(
        apply_spool_activations(
            {
                "module": module_id,
                "type": "spool_activations",
                "count": 3,
                "percent_remaining": 97,
            }
        )
    )

    response = client.get("/api/modules")
    response.raise_for_status()
    module_records = response.json()
    target = next((entry for entry in module_records if entry["module_id"] == module_id), None)
    assert target is not None
    spool_state = target.get("spool_state")
    assert spool_state is not None
    assert spool_state.get("activations") == 3
    assert spool_state.get("percent_remaining") == 97


def test_legacy_spool_tick_still_supported():
    module_id = "SpoolTickLegacy"
    asyncio.run(
        upsert_module_status(
            {
                "module": module_id,
                "type": "status",
                "motor": {"state": "stopped", "speed": 0, "runtime_ms": 0, "mode": "auto"},
                "floats": {"main": False, "min": False, "max": False},
                "ato": {
                    "pump_running": False,
                    "manual_mode": False,
                    "paused": False,
                    "timeout_alarm": False,
                },
                "system": {"chirp_enabled": True, "uptime_s": 10},
                "spool": {"full_edges": 1000, "used_edges": 0, "percent_remaining": 100},
            }
        )
    )
    asyncio.run(
        apply_spool_tick(
            {
                "module": module_id,
                "type": "spool_tick",
                "spool": {"activations": 5, "percent_remaining": 93},
            }
        )
    )

    response = client.get("/api/modules")
    response.raise_for_status()
    module_records = response.json()
    target = next((entry for entry in module_records if entry["module_id"] == module_id), None)
    assert target is not None
    spool_state = target.get("spool_state")
    assert spool_state is not None
    assert spool_state.get("activations") == 5
    assert spool_state.get("percent_remaining") == 93
