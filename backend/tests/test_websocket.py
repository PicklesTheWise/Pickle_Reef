import asyncio
from math import isclose

from fastapi.testclient import TestClient

from app.main import app
from app.services.module_status import (
    apply_spool_activations,
    record_module_alarm,
    upsert_module_manifest,
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


def test_thermistor_alarm_enriches_meta_from_status():
    module_id = "ThermistorAlarm"
    status_payload = _base_status_payload(module_id)
    status_payload["heater"] = {
        "primary_temp_c": 78.4,
        "secondary_temp_c": 75.9,
        "thermistor_delta_c": 2.5,
        "thermistor_delta_threshold_c": 1.2,
    }
    asyncio.run(upsert_module_status(status_payload))
    asyncio.run(
        record_module_alarm(
            {
                "module": module_id,
                "type": "alarm",
                "alarm": {
                    "code": "thermistor_mismatch",
                    "severity": "critical",
                    "active": True,
                    "message": "Thermistor disagreement detected",
                    "meta": {},
                },
            }
        )
    )

    response = client.get("/api/modules")
    response.raise_for_status()
    module_records = response.json()
    target = next((entry for entry in module_records if entry["module_id"] == module_id), None)
    assert target is not None
    alarm = next((entry for entry in target.get("alarms", []) if entry.get("code") == "thermistor_mismatch"), None)
    assert alarm is not None
    meta = alarm.get("meta") or {}
    assert isclose(meta.get("delta_c", 0), 2.5)
    assert isclose(meta.get("threshold_c", 0), 1.2)
    assert isclose(meta.get("primary_temp_c", 0), 78.4)
    assert isclose(meta.get("secondary_temp_c", 0), 75.9)


def test_spool_activations_updates_activation_counter():
    module_id = "ActivationTester"
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
    module_id = "ActivationCountAlias"
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


def _base_status_payload(module_id: str) -> dict:
    return {
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
    }


def test_module_subsystems_fallback_to_defaults():
    module_id = "SubsystemDefaults"
    asyncio.run(upsert_module_status(_base_status_payload(module_id)))

    response = client.get("/api/modules")
    response.raise_for_status()
    module_records = response.json()
    target = next((entry for entry in module_records if entry["module_id"] == module_id), None)
    assert target is not None
    subsystems = target.get("subsystems")
    assert subsystems is not None
    kinds = {entry["kind"] for entry in subsystems}
    assert kinds == {"ato"}
    assert target["module_type"] == "ATO"


def test_module_subsystems_return_custom_definitions():
    module_id = "SubsystemCustom"
    payload = _base_status_payload(module_id)
    payload["subsystems"] = [
        {
            "key": "roller-left",
            "kind": "roller",
            "label": "Lagoon Roller",
            "badge_label": "Lagoon",
            "card_suffix": "North",
        },
        {
            "key": "ato-topoff",
            "kind": "ato",
            "label": "Reservoir",
            "badge_label": "ATO+",
        },
    ]
    asyncio.run(upsert_module_status(payload))

    response = client.get("/api/modules")
    response.raise_for_status()
    module_records = response.json()
    target = next((entry for entry in module_records if entry["module_id"] == module_id), None)
    assert target is not None
    subsystems = target.get("subsystems")
    assert subsystems is not None
    assert [entry["key"] for entry in subsystems] == ["roller-left", "ato-topoff"]
    assert subsystems[0]["label"] == "Lagoon Roller"
    assert subsystems[0]["badge_label"] == "Lagoon"
    # Defaults still backfill optional presentation fields.
    assert subsystems[1]["card_suffix"] == "ATO"


def test_module_manifest_overrides_subsystems():
    module_id = "ManifestSubject"
    asyncio.run(upsert_module_status(_base_status_payload(module_id)))
    manifest_payload = {
        "module": module_id,
        "type": "module_manifest",
        "name": "PickleSump",
        "submodules": [
            {
                "id": "PickleSump.Filter",
                "label": "Filter Roller",
                "category": "filter",
                "capabilities": ["roller", "spool", "alarm"],
            },
            {
                "id": "PickleSump.ATO",
                "label": "ATO Reservoir",
                "category": "ato",
                "capabilities": ["pump", "reservoir", "alarm"],
            },
        ],
    }
    asyncio.run(upsert_module_manifest(module_id, manifest_payload))

    response = client.get("/api/modules")
    response.raise_for_status()
    module_records = response.json()
    target = next((entry for entry in module_records if entry["module_id"] == module_id), None)
    assert target is not None
    subsystems = target.get("subsystems")
    assert subsystems is not None
    assert [entry["key"] for entry in subsystems] == ["PickleSump.Filter", "PickleSump.ATO"]
    assert subsystems[0]["kind"] == "roller"
    assert subsystems[1]["kind"] == "ato"
    assert subsystems[0]["label"] == "Filter Roller"
    assert subsystems[1]["badge_label"] == "ATO"


def test_module_subsystems_fallback_when_no_signals():
    module_id = "SubsystemFallback"
    payload = _base_status_payload(module_id)
    payload.pop("ato", None)
    asyncio.run(upsert_module_status(payload))

    response = client.get("/api/modules")
    response.raise_for_status()
    module_records = response.json()
    target = next((entry for entry in module_records if entry["module_id"] == module_id), None)
    assert target is not None
    subsystems = target.get("subsystems")
    assert subsystems is not None
    kinds = {entry["kind"] for entry in subsystems}
    assert kinds == {"roller", "ato"}
    assert target["module_type"] == "Sensor"


def test_module_type_infers_filter_when_spool_present():
    module_id = "FilterType"
    payload = _base_status_payload(module_id)
    payload["spool"] = {
        "full_edges": 1000,
        "used_edges": 250,
        "total_length_mm": 50000,
    }
    asyncio.run(upsert_module_status(payload))

    response = client.get("/api/modules")
    response.raise_for_status()
    module_records = response.json()
    target = next((entry for entry in module_records if entry["module_id"] == module_id), None)
    assert target is not None
    assert target["module_type"] == "Filter"


def test_module_type_infers_heater_from_payload():
    module_id = "PickleHeat01"
    payload = _base_status_payload(module_id)
    payload.pop("ato", None)
    payload["heater"] = {"setpoint_c": 25.5, "output": 0.42, "state": "heating"}
    asyncio.run(upsert_module_status(payload))

    response = client.get("/api/modules")
    response.raise_for_status()
    module_records = response.json()
    target = next((entry for entry in module_records if entry["module_id"] == module_id), None)
    assert target is not None
    assert target["module_type"] == "Heater"


def test_delete_module_endpoint_removes_records():
    module_id = "PurgeTester"
    asyncio.run(upsert_module_status(_base_status_payload(module_id)))

    response = client.delete(f"/api/modules/{module_id}")
    response.raise_for_status()
    payload = response.json()
    assert payload["removed"] >= 1

    refreshed = client.get("/api/modules").json()
    assert not any(entry["module_id"] == module_id for entry in refreshed)

    second = client.delete(f"/api/modules/{module_id}")
    assert second.status_code == 404

