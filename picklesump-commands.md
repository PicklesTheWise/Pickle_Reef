# PickleSump WebSocket Command Cheat Sheet

All commands use the `reefnet.v1` envelope and are sent as WebSocket text frames.

## Base Envelope

```json
{
  "protocol": "reefnet.v1",
  "module_id": "PickleSump",
  "type": "control",
  "payload": {
    "command": "request_status"
  }
}
```

## Control Commands

### 1) Request Current Status

```json
{
  "protocol": "reefnet.v1",
  "module_id": "PickleSump",
  "type": "control",
  "payload": {
    "command": "request_status"
  }
}
```

### 2) Request Config Snapshot (returned inside `status.payload.config`)

```json
{
  "protocol": "reefnet.v1",
  "module_id": "PickleSump",
  "type": "control",
  "payload": {
    "command": "request_config"
  }
}
```

### 3) Set ATO Mode (`0=auto`, `1=manual`, `2=paused`)

```json
{
  "protocol": "reefnet.v1",
  "module_id": "PickleSump",
  "type": "control",
  "payload": {
    "command": "set_ato_mode",
    "parameters": {
      "mode": 2
    }
  }
}
```

### 4) Spool Reset

```json
{
  "protocol": "reefnet.v1",
  "module_id": "PickleSump",
  "type": "control",
  "payload": {
    "command": "spool_reset"
  }
}
```

### 5) Start Spool Calibration

```json
{
  "protocol": "reefnet.v1",
  "module_id": "PickleSump",
  "type": "control",
  "payload": {
    "command": "spool_calibrate_start"
  }
}
```

### 6) Finish Spool Calibration

```json
{
  "protocol": "reefnet.v1",
  "module_id": "PickleSump",
  "type": "control",
  "payload": {
    "command": "spool_calibrate_finish",
    "parameters": {
      "roll_length_mm": 50000
    }
  }
}
```

### 7) Cancel Spool Calibration

```json
{
  "protocol": "reefnet.v1",
  "module_id": "PickleSump",
  "type": "control",
  "payload": {
    "command": "spool_calibrate_cancel"
  }
}
```

### 8) Mark ATO Tank Refilled

```json
{
  "protocol": "reefnet.v1",
  "module_id": "PickleSump",
  "type": "control",
  "payload": {
    "command": "ato_tank_refill"
  }
}
```

## Generic Parameter Setter

Use `set_parameter` for runtime tunables.

Compatibility note: firmware variants may read either `parameters.param` (legacy) or `parameters.name` (newer envelope). Sending both is safe.

```json
{
  "protocol": "reefnet.v1",
  "module_id": "PickleSump",
  "type": "control",
  "payload": {
    "command": "set_parameter",
    "parameters": {
      "name": "pump_timeout_ms",
      "param": "pump_timeout_ms",
      "value": 180000
    }
  }
}
```

## Supported `set_parameter` Keys

- `motor_speed` (firmware also accepts `motor_max_speed`)
- `pump_speed`
- `motor_runtime`
- `ramp_up`
- `ramp_down`
- `chirp_enabled`
- `pump_timeout_ms`
- `ato_mode`
- `ato_tank_capacity_ml`
- `ato_tank_level_ml`
- `ato_tank_refill`
- `spool_reset`
- `spool_calibrate_start`
- `spool_calibrate_finish`
- `spool_calibrate_cancel`
- `alarm_chirp_interval_ms`
- `spool_length_mm`
- `spool_core_diameter_mm`
- `spool_media_thickness_um`

## Common `set_parameter` Examples

### Roller Speed

```json
{
  "protocol": "reefnet.v1",
  "module_id": "PickleSump",
  "type": "control",
  "payload": {
    "command": "set_parameter",
    "parameters": {
      "name": "motor_speed",
      "param": "motor_speed",
      "value": 200
    }
  }
}
```

### Pump Timeout (ms)

```json
{
  "protocol": "reefnet.v1",
  "module_id": "PickleSump",
  "type": "control",
  "payload": {
    "command": "set_parameter",
    "parameters": {
      "name": "pump_timeout_ms",
      "param": "pump_timeout_ms",
      "value": 120000
    }
  }
}
```

### Alarm Chirp Interval (ms)

```json
{
  "protocol": "reefnet.v1",
  "module_id": "PickleSump",
  "type": "control",
  "payload": {
    "command": "set_parameter",
    "parameters": {
      "name": "alarm_chirp_interval_ms",
      "param": "alarm_chirp_interval_ms",
      "value": 120000
    }
  }
}
```

### Set ATO Tank Level

```json
{
  "protocol": "reefnet.v1",
  "module_id": "PickleSump",
  "type": "control",
  "payload": {
    "command": "set_parameter",
    "parameters": {
      "name": "ato_tank_level_ml",
      "param": "ato_tank_level_ml",
      "value": 10000
    }
  }
}
```

## Status Fields to Read (Roller)

From each `status` frame:

- `payload.motor.speed` → current roller speed (PWM value currently applied)
- `payload.motor.runtime_ms` → elapsed runtime for current roller cycle (`0` when stopped)
- `payload.motor.state` → `stopped | ramping_up | running | ramping_down`
- `payload.motor.mode` → `manual | auto`

Minimal example:

```json
{
  "protocol": "reefnet.v1",
  "module_id": "PickleSump",
  "type": "status",
  "payload": {
    "motor": {
      "state": "running",
      "speed": 200,
      "runtime_ms": 3512,
      "mode": "auto"
    }
  }
}
```

## What You Receive Back

- `status` frames (periodic + on-demand + after successful changes)
- `alarm` frames (assert/clear events)
