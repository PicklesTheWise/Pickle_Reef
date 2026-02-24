from fastapi.testclient import TestClient

from app.main import app

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
    with client.websocket_connect("/ws") as websocket:
        websocket.receive_json()
        websocket.send_json(
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
        websocket.send_json(
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
