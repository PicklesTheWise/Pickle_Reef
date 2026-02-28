# WebSocket Message Reference

This document summarizes every outbound message that the heater firmware currently publishes over the WebSocket connection so the front-end can deserialize and react appropriately.

## Common Envelope

All payloads share these top-level fields before their `payload` object:

```json
{
  "protocol": "reefnet.v1",
  "module_id": "PickleHeat.Heater",
  "submodule_id": "PickleHeat.Heater",
  "type": "status|alarm",
  "sent_at": "2026-02-27T21:15:10Z",
  "payload": { ... }
}
```

- `protocol`: Version string. Reject frames if this does not match what the UI supports.
- `module_id` / `submodule_id`: Identify the physical controller board and logical heater subsystem.
- `type`: Drives routing. Current values are `status` and `alarm`.
- `sent_at`: ISO-8601 UTC timestamp generated at send time.

## `status` Frames

Sent at boot, every second while connected, and whenever configuration/safety state changes (also on `config_request`, `module_manifest_request`, `status_request`, or `ping`). The payload shape is:

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
      "state": "heating|idle|locked",
      "badge": "ok|active|alarm",
      "safety_lockout": false,
      "visible_alarm": "" | "safety.probe_mismatch" | ..., 
      "setpoints": {
        "setpoint_c": 25.0,
        "setpoint_min_c": 24.9,
        "setpoint_max_c": 25.1,
        "hysteresis_span_c": 0.2,
        "hysteresis_half_c": 0.1,
        "probe_tolerance_c": 0.7,
        "thermistor_alarm": false,
        "duty_cycle_percent": 32.5
      },
      "safety": {
        "probe_timeout_s": 45,
        "runaway_delta_c": 2.0,
        "max_heater_on_min": 15,
        "stuck_relay_delta_c": 0.5,
        "stuck_relay_window_s": 60,
        "state": {
          "all_probes_offline": false,
          "thermal_runaway": false,
          "heater_overrun": false,
          "relay_stuck": false,
          "lockout": false,
          "visible_alarm": ""
        },
        "alarms": [
          {
            "code": "safety.thermal_runaway",
            "title": "Thermal runaway",
            "detail": "Optional human-readable detail",
            "triggered_at": "2026-02-27T21:02:00Z"
          }
        ]
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

Field notes:
- `network` block is present only when Wi-Fi is associated.
- `state` reflects live heater mode (`locked` overrides actual relay state when any safety lockout is active).
- `visible_alarm` mirrors the highest-priority active safety alarm code or empty string if none.
- `safety.alarms` contains only currently-active entries (one per code) with optional detail/timestamp metadata.

## `alarm` Frames

Two subsystems generate `type: "alarm"` payloads. Both reuse the common envelope plus an alarm-specific payload:

```json
{
  "severity": "critical|warning|info",
  "code": "safety.heater_overrun" | "thermistor_mismatch" | ...,
  "message": "Localized title",
  "category": "safety" | "sensors",
  "active": true,
  "detail": "Optional detail text",
  "triggered_at": "2026-02-27T21:02:00Z",
  "cleared_at": "2026-02-27T21:05:10Z",
  "meta": {
    // varies per alarm source
  }
}
```

### Safety alarms
- Raised via `sendSafetyAlarm()` whenever any `SafetyAlarmCode` toggles.
- `severity`: `critical` while active, `info` on clear.
- `code` values:
  - `safety.probe_mismatch`
  - `safety.probe_single_failure`
  - `safety.probe_dual_failure`
  - `safety.thermal_runaway`
  - `safety.heater_overrun`
  - `safety.relay_stuck`
- `category`: always `safety`.
- `meta` fields:
  - `avg_temp_c`
  - `setpoint_min_c`
  - `setpoint_max_c`
  - `lockout` (boolean)

### Thermistor mismatch alarms
- Raised via `sendThermistorAlarm()` when probe delta crosses the configured tolerance.
- `severity`: `warning` while active, `info` on clear.
- `code`: always `thermistor_mismatch`.
- `category`: `sensors` (implicit; can be treated separately from safety block).
- `meta` fields:
  - `delta_c`
  - `threshold_c`
  - `primary_temp_c`
  - `secondary_temp_c`

## Message Triggers Summary

| Message | Trigger(s) |
|---------|------------|
| `status` | Boot, periodic heartbeat, config requests, parameter changes, safety state changes |
| `alarm` (safety) | Any safety guard transitions in `setSafetyAlarmState()` |
| `alarm` (thermistor mismatch) | Thermistor delta crossing `probe_tolerance_c` thresholds |

Use these schemas to validate payloads, derive UI state, and wire up notifications on the front end.

## Inbound Messages (UI → Heater)

The controller expects the same common envelope (protocol/module/submodule/type/sent_at/payload). Unsupported `protocol` values are logged and ignored. Current message types are:

### `control`

```json
{
  "protocol": "reefnet.v1",
  "type": "control",
  "payload": {
    "command": "set_param|config_request|module_manifest_request|status_request|ping",
    ...
  }
}
```

- `set_param`
  - Either `parameters` (object map) or legacy `param` + `value` pair is required.
  - Recognized parameter keys: `setpoint_c`, `setpoint_min_c`, `setpoint_max_c`, `probe_tolerance_c` plus legacy aliases (`heater_setpoint_c`, `thermistor_delta_limit_c`, etc.). Unknown keys are ignored after logging.
  - When `parameters` is present, the firmware stages all updates then persists setpoints once; single `param/value` updates persist immediately.
- `config_request`, `module_manifest_request`, `status_request`, `ping`
  - No extra fields required.
  - Each command prompts an immediate `status` response so the UI can refresh.

### `config_request` (legacy direct type)

```json
{
  "type": "config_request"
}
```

Legacy peers may send these without wrapping in `control`. The firmware treats `config_request` and `module_manifest_request` (also `set_param`) at the top level exactly as it does via the `control` command and responds with `status`.

### `set_param` (legacy direct type)

```json
{
  "type": "set_param",
  "param": "setpoint_c",
  "value": 25.0
}
```

Processed through `handleLegacySetParam()`. Same parameter rules as the command variant.

### Error handling

- Malformed JSON frames are logged with their raw bytes and dropped.
- Missing `payload` or `command` fields in `control` frames result in a warning and no action.
- Unknown `type` values are logged and ignored.
