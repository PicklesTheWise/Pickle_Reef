# Pickle Heat WebSocket Commands

Frontend reference for all WebSocket traffic currently implemented by the Pickle Heat firmware (`src/main.cpp`).

## Endpoint + Session

- Transport: WebSocket text frames (JSON)
- Host/path (current firmware constants): `ws://192.168.4.1:80/ws`
- Protocol string: `reefnet.v1`
- Module identity:
  - `module_id`: `PickleHeat.Heater`
  - `submodule_id`: `PickleHeat.Heater`

## Shared Envelope

All outbound frames and modern inbound frames use this shape:

```json
{
  "protocol": "reefnet.v1",
  "module_id": "PickleHeat.Heater",
  "submodule_id": "PickleHeat.Heater",
  "type": "status|alarm|control",
  "sent_at": "2026-02-27T21:15:10Z",
  "payload": {}
}
```

Notes:
- `sent_at` is UTC ISO-8601.
- Inbound frames with mismatched `protocol` are logged (not hard-rejected).
- Only `type: "control"` inbound frames are accepted.

---

## Outbound (Heater → Frontend)

## 1) `type: "status"`

Sent when:
- On WS connect
- Every ~1s heartbeat while connected
- After accepted param/config changes
- After safety alarm state transitions
- In response to `config_request`, `module_manifest_request`, `status_request`, and `ping`

Payload schema:

```json
{
  "uptime_s": 12345,
  "firmware": {
    "version": "0.6.0",
    "build": "Feb 27 2026 12:34:56"
  },
  "network": {
    "ip": "192.168.4.20",
    "mac": "3C:DC:75:6E:D4:6C",
    "ssid": "ReefNet",
    "rssi_dbm": -62
  },
  "environment": {
    "temperature_c": 25.4
  },
  "subsystems": [
    {
      "key": "heater",
      "label": "Pickle Heat",
      "kind": "heater",
      "submodule_id": "PickleHeat.Heater",
      "state": "idle|heating",
      "badge": "ok|active|alarm",
      "setpoints": {
        "setpoint_c": 25.0,
        "setpoint_min_c": 24.9,
        "setpoint_max_c": 25.1,
        "hysteresis_span_c": 0.2,
        "hysteresis_half_c": 0.1,
        "probe_tolerance_c": 0.7,
        "probe_timeout_s": 45,
        "runaway_delta_c": 2.0,
        "max_heater_on_min": 15,
        "stuck_relay_delta_c": 0.5,
        "stuck_relay_window_s": 60,
        "thermistor_alarm": false,
        "duty_cycle_percent": 32.5
      },
      "sensors": [
        { "label": "Primary", "value": 25.2, "unit": "C" },
        { "label": "Secondary", "value": 24.9, "unit": "C" },
        { "label": "Average", "value": 25.05, "unit": "C" },
        { "label": "Delta", "value": 0.3, "unit": "C" },
        { "label": "Duty Cycle", "value": 32.5, "unit": "%" },
        { "label": "Activations", "value": 42, "unit": "cycles" }
      ]
    }
  ]
}
```

Important frontend notes:
- `network` appears only when Wi-Fi is connected.
- Safety tuning fields are currently echoed in `setpoints`.

## 2) `type: "alarm"` (Thermistor mismatch)

Generated when probe delta crosses threshold.

Payload shape:

```json
{
  "severity": "warning|info",
  "code": "thermistor_mismatch",
  "message": "Thermistors disagree|Thermistor mismatch cleared",
  "active": true,
  "triggered_at": "2026-02-27T21:02:00Z",
  "cleared_at": "2026-02-27T21:05:10Z",
  "meta": {
    "delta_c": 0.8,
    "threshold_c": 0.7,
    "primary_temp_c": 25.8,
    "secondary_temp_c": 25.0
  }
}
```

Note:
- This alarm payload does **not** currently include `category`.

---

## Inbound (Frontend → Heater)

## 1) `type: "control"` (preferred)

```json
{
  "protocol": "reefnet.v1",
  "type": "control",
  "payload": {
    "command": "set_param|set_parameter|alarm_acknowledge|alarm_snooze|alarm_unsnooze|config_request|module_manifest_request|status_request|ping",
    "parameters": {}
  }
}
```

### `command: "set_param"`

Supported forms:

A) Batch map form (required):
```json
{
  "type": "control",
  "payload": {
    "command": "set_param",
    "parameters": {
      "setpoint_c": 25.0,
      "setpoint_min_c": 24.9,
      "setpoint_max_c": 25.1,
      "probe_tolerance_c": 0.7
    }
  }
}
```

Recognized parameter keys:
- `setpoint_c`
- `setpoint_min_c`
- `setpoint_max_c`
- `probe_tolerance_c`
- `probe_timeout_s` (alias accepted: `alarm.probe_timeout_s`)
- `runaway_delta_c` (alias accepted: `alarm.runaway_delta_c`)
- `max_heater_on_min` (aliases accepted: `alarm.max_heater_on_min`, `heater_timeout_min`)
- `stuck_relay_delta_c` (alias accepted: `alarm.stuck_relay_delta_c`)
- `stuck_relay_window_s` (aliases accepted: `alarm.stuck_relay_window_s`, `relay_timeout_s`)
- `hysteresis_span_c`
- `hysteresis_half_c`
- `alarm_snooze` (alias accepted: `alarm.snooze`) (`1` = snooze now, `0` = clear snooze)
- `alarm_acknowledge` (`1` = snooze now, `0` = clear snooze)
- `alarm_unsnooze` (alias accepted: `alarm.unsnooze`) (`1` = clear snooze)

Behavior:
- Unknown params are logged and ignored.
- Successful updates trigger an immediate outbound `status`.
- `payload.parameters` is required for `set_param`.
- Applied heater setting changes are persisted to Preferences (ESP32 NVS / EEPROM-backed flash) and restored at boot.

### `command: "set_parameter"`

Also accepted for frontend compatibility.

Supported payload forms:

```json
{
  "type": "control",
  "payload": {
    "command": "set_parameter",
    "parameters": {
      "name": "setpoint_c",
      "value": 25.0
    }
  }
}
```

Or batch map form (same as `set_param`):

```json
{
  "type": "control",
  "payload": {
    "command": "set_parameter",
    "parameters": {
      "setpoint_c": 25.0,
      "probe_tolerance_c": 0.7
    }
  }
}
```

### `command: "config_request" | "module_manifest_request" | "status_request" | "ping"`

Any of these commands returns an immediate outbound `status` snapshot.

### `command: "alarm_acknowledge" | "alarm_snooze" | "alarm_unsnooze"`

Alarm control commands (no extra fields required):

- `alarm_acknowledge` / `alarm_snooze`: applies the same 15-minute snooze as pressing the popup acknowledge button.
- `alarm_unsnooze`: clears any active snooze immediately.

Each command triggers an immediate `status` response.

## Error + Ignore Behavior

- Invalid JSON: logged and dropped.
- `control` without `payload` or without `command`: logged and dropped.
- Non-`control` inbound `type`: logged and ignored.
- Non-heater control commands (for example `set_ato_mode`) are logged and ignored.
- Protocol mismatch: logged as unsupported; processing may continue.

---

## Frontend Integration Checklist

- Route by `type` first: `status` vs `alarm`.
- Treat `status` as authoritative full-state snapshot.
- Handle missing optional fields (`network`, alarm `detail`, alarm `cleared_at`).
- Use `control/set_param` batch mode when updating multiple values.
- After sending commands, expect an immediate `status` frame for state reconciliation.
