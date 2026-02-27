import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
from math import isclose

from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services.ws_trace import clear_ws_trace, record_ws_trace, get_ws_trace
from app.services.module_status import (
    apply_ato_activations,
    apply_spool_activations,
    record_module_alarm,
    reset_module_store,
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


def test_status_frames_always_logged_in_trace():
    clear_ws_trace()
    module_id = "TraceLogger"
    with client.websocket_connect("/ws") as websocket:
        websocket.receive_json()  # config_request
        websocket.receive_json()  # module_manifest_request
        websocket.send_json(_base_status_payload(module_id))

    response = client.get("/api/debug/ws-trace")
    response.raise_for_status()
    entries = response.json()
    assert any(
        entry.get("payload", {}).get("type") == "status" and entry.get("payload", {}).get("module") == module_id
        for entry in entries
    ), "Expected status frame to be persisted in trace log"
    clear_ws_trace()


def test_ws_trace_retention_prunes_old_entries():
    clear_ws_trace()
    conn = sqlite3.connect(settings.ws_trace_db_path)
    old_timestamp = (datetime.utcnow() - timedelta(days=settings.ws_trace_retention_days + 1)).isoformat(
        timespec="milliseconds"
    )
    conn.execute(
        "INSERT INTO ws_trace_log (recorded_at, direction, module_id, payload) VALUES (?, ?, ?, ?)",
        (old_timestamp, "rx", "LegacyModule", json.dumps({"type": "status"})),
    )
    conn.commit()
    conn.close()

    record_ws_trace("rx", {"type": "status"}, "FreshModule")

    entries = get_ws_trace(limit=100)
    assert all(entry["module_id"] != "LegacyModule" for entry in entries)
    assert any(entry["module_id"] == "FreshModule" for entry in entries)
    clear_ws_trace()


def test_temperature_history_endpoint_filters_window():
    clear_ws_trace()

    # Insert an old entry that should be outside the default window.
    conn = sqlite3.connect(settings.ws_trace_db_path)
    old_timestamp = (datetime.utcnow() - timedelta(hours=2)).isoformat(timespec="milliseconds")
    conn.execute(
        "INSERT INTO ws_trace_log (recorded_at, direction, module_id, payload) VALUES (?, ?, ?, ?)",
        (old_timestamp, "rx", "HistoryOld", json.dumps(_heater_status_payload("HistoryOld"))),
    )
    conn.commit()
    conn.close()

    record_ws_trace("rx", _heater_status_payload("HistoryFresh"), "HistoryFresh")

    response = client.get("/api/temperature/history", params={"window_minutes": 60})
    response.raise_for_status()
    samples = response.json()
    module_ids = {entry["module_id"] for entry in samples}
    assert "HistoryFresh" in module_ids
    assert "HistoryOld" not in module_ids
    sample = next(entry for entry in samples if entry["module_id"] == "HistoryFresh")
    assert sample["thermistors"]
    assert sample["timestamp"] > 0
    assert isinstance(sample["heater_on"], bool)
    clear_ws_trace()


def test_temperature_history_endpoint_supports_module_filter():
    clear_ws_trace()
    record_ws_trace("rx", _heater_status_payload("HeaterA"), "HeaterA")
    record_ws_trace("rx", _heater_status_payload("HeaterB"), "HeaterB")

    response = client.get("/api/temperature/history", params={"module_id": "HeaterB"})
    response.raise_for_status()
    samples = response.json()
    module_ids = {entry["module_id"] for entry in samples}
    assert module_ids == {"HeaterB"}
    clear_ws_trace()


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


def test_spool_activations_record_usage_history():
    module_id = "SpoolUsageTracker"
    initial_status = _base_status_payload(module_id)
    initial_status["spool"] = {
        "full_edges": 20000,
        "total_length_mm": 50000,
        "used_edges": 0,
        "percent_remaining": 100,
    }
    asyncio.run(upsert_module_status(initial_status))

    asyncio.run(
        apply_spool_activations(
            {
                "module": module_id,
                "type": "spool_activations",
                "activations": 10,
                "percent_remaining": 100,
            }
        )
    )
    asyncio.run(
        apply_spool_activations(
            {
                "module": module_id,
                "type": "spool_activations",
                "activations": 11,
                "percent_remaining": 98,
            }
        )
    )

    response = client.get("/api/spool-usage?window_hours=24")
    response.raise_for_status()
    entries = response.json()
    assert entries, "Expected at least one spool usage entry"
    entry = entries[0]
    assert entry["delta_mm"] > 0
    assert entry["total_used_edges"] > 0


def test_status_frame_with_envelope_populates_heater_snapshot():
    module_id = "PickleHeat.Heater"
    with client.websocket_connect("/ws") as websocket:
        websocket.receive_json()
        websocket.receive_json()
        websocket.send_json(
            {
                "protocol": "reefnet.v1",
                "module_id": module_id,
                "type": "status",
                "payload": {
                    "subsystems": [
                        {
                            "key": "heater",
                            "kind": "heater",
                            "state": "heating",
                            "sensors": [
                                {"label": "Primary", "value": 25.2, "unit": "C"},
                                {"label": "Secondary", "value": 25.0, "unit": "C"},
                            ],
                        }
                    ]
                },
            }
        )

    response = client.get("/api/modules")
    response.raise_for_status()
    module_records = response.json()
    target = next((entry for entry in module_records if entry["module_id"] == module_id), None)
    assert target is not None
    heater = target.get("status_payload", {}).get("heater")
    assert heater is not None
    assert heater.get("state") == "heating"
    thermometers = heater.get("thermometers")
    assert isinstance(thermometers, list) and len(thermometers) >= 2


def test_upsert_status_accepts_module_id_alias():
    reset_module_store()
    module_id = "AliasStatus"
    payload = _base_status_payload(module_id)
    payload.pop("module")
    payload["module_id"] = module_id
    asyncio.run(upsert_module_status(payload))

    response = client.get("/api/modules")
    response.raise_for_status()
    module_records = response.json()
    target = next((entry for entry in module_records if entry["module_id"] == module_id), None)
    assert target is not None
    assert target["label"] == module_id


def test_spool_activations_use_connection_hint_when_module_missing():
    reset_module_store()
    module_id = "HintedSpool"
    asyncio.run(upsert_module_status(_base_status_payload(module_id)))
    asyncio.run(
        apply_spool_activations(
            {
                "type": "spool_activations",
                "activations": 4,
                "percent_remaining": 96,
            },
            module_hint=module_id,
        )
    )

    response = client.get("/api/modules")
    response.raise_for_status()
    module_records = response.json()
    target = next((entry for entry in module_records if entry["module_id"] == module_id), None)
    assert target is not None
    spool_state = target.get("spool_state")
    assert spool_state.get("activations") == 4
    assert spool_state.get("percent_remaining") == 96


def test_module_snapshots_endpoint_returns_history():
    module_id = "SnapshotLogger"
    with client.websocket_connect("/ws") as websocket:
        websocket.receive_json()
        websocket.receive_json()
        websocket.send_json(_base_status_payload(module_id))
        updated = _base_status_payload(module_id)
        updated["motor"]["runtime_ms"] = 5000
        websocket.send_json(updated)

    response = client.get(f"/api/modules/{module_id}/snapshots?limit=5")
    response.raise_for_status()
    snapshots = response.json()
    assert len(snapshots) >= 2
    payload = snapshots[-1]["payload"]
    assert payload["module"] == module_id
    assert payload["motor"]["runtime_ms"] == 5000


def test_ato_activations_updates_reservoir_snapshot():
    reset_module_store()
    module_id = "PickleSump"
    asyncio.run(upsert_module_status(_base_status_payload(module_id)))
    asyncio.run(
        apply_ato_activations(
            {
                "type": "ato_activations",
                "activations": 12,
                "tank_percent": 55,
                "tank_level_ml": 8250,
                "tank_capacity_ml": 15000,
            },
            module_hint=module_id,
        )
    )

    response = client.get("/api/modules")
    response.raise_for_status()
    module_records = response.json()
    target = next((entry for entry in module_records if entry["module_id"] == module_id), None)
    assert target is not None
    ato_state = target.get("status_payload", {}).get("ato")
    assert ato_state is not None
    assert ato_state.get("activations") == 12
    assert ato_state.get("tank_percent") == 55
    assert ato_state.get("tank_level_ml") == 8250


def test_alarm_frame_with_envelope_records_alarm():
    module_id = "HeaterAlarmEnvelope"
    with client.websocket_connect("/ws") as websocket:
        websocket.receive_json()
        websocket.receive_json()
        websocket.send_json(
            {
                "protocol": "reefnet.v1",
                "module_id": module_id,
                "type": "status",
                "payload": {
                    "module": module_id,
                    "motor": {"state": "idle", "speed": 0},
                },
            }
        )
        websocket.send_json(
            {
                "protocol": "reefnet.v1",
                "module_id": module_id,
                "type": "alarm",
                "payload": {
                    "severity": "warning",
                    "code": "thermistor_mismatch",
                    "message": "Thermistors disagree",
                    "active": True,
                    "triggered_at": "2026-02-27T21:02:00Z",
                    "meta": {"delta_c": 0.9},
                },
            }
        )

    response = client.get("/api/modules")
    response.raise_for_status()
    module_records = response.json()
    target = next((entry for entry in module_records if entry["module_id"] == module_id), None)
    assert target is not None
    alarms = target.get("alarms") or []
    assert any(alarm.get("code") == "thermistor_mismatch" for alarm in alarms)

def test_alarm_frame_with_envelope_records_alarm():
    module_id = "HeaterAlarmEnvelope"
    with client.websocket_connect("/ws") as websocket:
        websocket.receive_json()
        websocket.receive_json()
        websocket.send_json(
            {
                "protocol": "reefnet.v1",
                "module_id": module_id,
                "type": "status",
                "payload": {
                    "module": module_id,
                    "motor": {"state": "idle", "speed": 0},
                },
            }
        )
        websocket.send_json(
            {
                "protocol": "reefnet.v1",
                "module_id": module_id,
                "type": "alarm",
                "payload": {
                    "severity": "warning",
                    "code": "thermistor_mismatch",
                    "message": "Thermistors disagree",
                    "active": True,
                    "triggered_at": "2026-02-27T21:02:00Z",
                    "meta": {"delta_c": 0.9},
                },
            }
        )

    response = client.get("/api/modules")
    response.raise_for_status()
    module_records = response.json()
    target = next((entry for entry in module_records if entry["module_id"] == module_id), None)
    assert target is not None
    alarms = target.get("alarms") or []
    assert any(alarm.get("code") == "thermistor_mismatch" for alarm in alarms)


def test_ato_activations_emit_cycle_logs():
    module_id = "AtoCycleTester"
    asyncio.run(upsert_module_status(_base_status_payload(module_id)))
    asyncio.run(
        apply_ato_activations(
            {
                "module": module_id,
                "type": "ato_activations",
                "activations": 5,
                "tank_level_ml": 9000,
            }
        )
    )
    asyncio.run(
        apply_ato_activations(
            {
                "module": module_id,
                "type": "ato_activations",
                "activations": 6,
                "tank_level_ml": 8800,
            }
        )
    )

    response = client.get("/api/cycles/history?window_hours=24")
    response.raise_for_status()
    data = response.json()
    assert data["ato_runs"], "Expected inferred pump cycles"
    cycle = data["ato_runs"][0]
    assert cycle["cycle_type"].startswith("pump")
    assert cycle["duration_ms"] and cycle["duration_ms"] > 0
    expected_duration = int(round((9000 - 8800) / 0.0375))
    assert abs(cycle["duration_ms"] - expected_duration) <= 10


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


def _heater_status_payload(module_id: str) -> dict:
    payload = _base_status_payload(module_id)
    payload["heater"] = {
        "setpoint_c": 78.6,
        "output": 0.3,
        "thermistors": [
            {"label": "Probe 1", "value": 78.4},
            {"label": "Probe 2", "value": 77.9},
        ],
    }
    return payload


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

