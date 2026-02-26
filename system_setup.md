# System Setup

This guide condenses the WiFi/WebSocket protocol, module firmware expectations, and frontend stack into a single reference so you can provision every layer of Pickle Reef without jumping between documents.

## WiFi Protocol

### WebSocket Packet Summary
- Every module speaks JSON over a single socket: `ws://<display-ip>/ws`. Each frame uses the envelope `{ "module": "<module_id>", "type": "<message_type>", ...payload }`, which lets the backend multiplex multiple devices and forward them to the Svelte UI unchanged.
- Core message types the dashboard consumes:
  - `status`: 1 Hz heartbeat containing nested `motor`, `floats`, `ato`, `system`, `spool`, and optional `heater` objects.
  - `config`: persisted parameter block mirrored after boot or any `set_param` change.
  - `module_manifest`: declares submodules/kinds so the UI knows whether to render Filter, ATO, Heater, or Sensor cards.
  - `cycle_log`, `spool_activations`, `ato_activations`: historical deltas for charts and usage counters.
  - `alarm`: assert/clear transitions with severity, message, and metadata.
- `status` payload fields the UI expects when data exists:
  - `motor.state`, `motor.speed`, `motor.runtime_ms`, `motor.mode`.
  - `floats.main`, `floats.min`, `floats.max` booleans.
  - `ato.pump_running`, `manual_mode`, `paused`, `timeout_alarm`, `tank_level_ml`, `tank_capacity_ml`, `tank_percent`, `activations`.
  - `system.uptime_s`, `chirp_enabled`, `alarm_chirp_interval_ms`, `pump_timeout_ms`.
  - `spool.full_edges`, `used_edges`, `percent_remaining`, `empty_alarm`, `calibrating`, `total_length_mm`, `sample_length_mm`, `core_diameter_mm`, `media_thickness_um`, `activations`.
  - Heater payloads now include both probes plus derived metrics: surface `heater.setpoint_c`, `heater.setpoint_min_c`, `heater.setpoint_max_c`, `heater.heater_on` (or `output`/`duty_cycle`), a `heater.thermistors_c` array with the raw primary/secondary temperatures, convenience mirrors (`heater.primary_temp_c`, `heater.secondary_temp_c`), and the analytics fields `heater.average_temp_c`, `heater.thermistor_delta_c`, `heater.thermistor_alarm` so dashboards can show disagreements immediately.
- The UI degrades gracefully if a field is missing, but providing the full set unlocks charts (spool usage, tank trend), float pills, heater badges, and control presets with zero extra configuration.

### Hardware Requirements
- ESP32 or ESP32-S3 module with built-in WiFi (D1 R32 form factor works out of the box).
- No external CAN transceiver or RS485 hardware is required—the radio replaces the entire bus layer.
- ReefNet WiFi access point supplied by the display controller (ESP32-S3 handheld or Raspberry Pi host) running on 2.4 GHz.

### Network Architecture
```
Display Controller (ESP32-S3 or Raspberry Pi)
  ├── WiFi Access Point (AP mode)
  │     SSID: "ReefNet"
  │     Password: "ReefController2026"
  │     IP: 192.168.4.1/24
  └── WebSocket Server (port 80, path /ws)
        ↑  WiFi STA connection
        ↓
PickleSump Module (ESP32)
  └── WiFi Station client → WebSocket client
```

### Credentials & Constants
Reference definitions inside `src/main.cpp`:
```cpp
const char* WIFI_SSID = "ReefNet";
const char* WIFI_PASSWORD = "ReefController2026";
const char* WS_SERVER_IP = "192.168.4.1";
const uint16_t WS_SERVER_PORT = 80;
const char* MODULE_NAME = "PickleSump";
```
Update both the module and display firmware together if you change SSID, password, or AP addressing.

### Module Identity & Submodules
- The physical enclosure now reports itself as **PickleSump**. All status/config payloads continue to use `module = "PickleSump"` while we keep the combined telemetry model intact.
- PickleSump exposes two logical submodules that the UI should render as independent cards: `PickleSump.Filter` (roller, spool, alarms) and `PickleSump.ATO` (reservoir, pump, alarms).
- A new `module_manifest` broadcast advertises those submodules, their human-readable labels, and capability tags so dashboards can auto-provision cards without hardcoding layouts. See the message catalog below for the schema.
- Future firmware updates will allow per-submodule telemetry streams; introducing the manifest now provides a forward-compatible discovery surface without breaking existing status consumers.

### Broadcast Cadence & Envelope
- Status broadcasts fire every 1 s (reduced from the 100 ms CAN era to keep WiFi airtime low) as soon as the WebSocket is online.
- All payloads adopt the same envelope:
  ```json
  {
    "module": "PickleSump",
    "type": "<message_type>",
    ...additional fields...
  }
  ```
- The `module` field lets dashboards multiplex multiple devices over one socket.

### ReefNet Topology
- **Display/AP role**: The ESP32/S3 (or Raspberry Pi host) broadcasts the `ReefNet` SSID (`ReefController2026`) on `192.168.4.1/24` and exposes a WebSocket server on port `80` at `/ws`.
- **Module role**: Each PickleSump module boots in STA mode, joins the ReefNet AP, and dials `ws://192.168.4.1/ws`. Local control loops run uninterrupted even if WiFi drops.
- **Backend bridge**: The FastAPI app mirrors the `/ws` endpoint so Raspberry Pi–hosted modules and the Svelte dashboard can consume the same real-time feed.

### Connection Lifecycle
1. Module joins the ReefNet AP and opens the WebSocket.
2. Firmware immediately pushes a `config` payload followed by the first `status` update.
3. The UI hydrates controls from that config, then optionally issues a single `config_request` to confirm connectivity.
4. After every operator change (`set_param`), firmware persists the value and republishes `config`, guaranteeing the UI and EEPROM never diverge.
5. On disconnect, WiFi and WebSocket clients retry every 5 seconds; once reconnected, 1 Hz status broadcasting resumes automatically.

### Message Catalog
| Type | Direction | Purpose |
| --- | --- | --- |
| `status` | Module → Display | 1 Hz heartbeat covering motor/floats/ATO/system/spool state so dashboards mirror reality.
| `module_manifest` | Module → Display | Announces the PickleSump submodules (Filter, ATO) plus their categories/capabilities so the UI can create cards dynamically.
| `config_request` | Display → Module | Ask for the persisted parameter block; usually sent once after UI load.
| `module_manifest_request` | Display → Module | Optional probe that forces another `module_manifest` broadcast.
| `config` | Module → Display | Full parameter snapshot (motor window, ATO mode, chirp cadence, spool geometry) pushed after connect or any change.
| `set_param` | Display → Module | Mutate a single setting (speed, runtime, pump timeout, ATO mode, spool calibration helpers, alarm cadence, etc.).
| `cycle_log` | Module → Display | Emits immediately when a roller or pump cycle ends so historical charts never miss short events.
| `spool_activations` | Module → Display | 1 Hz counter of float-triggered advances since the last `spool_reset`; piggybacks on every status broadcast so dashboards never miss increments.
| `ato_activations` | Module → Display | 1 Hz counter of automatic reservoir fills since the last `ato_tank_refill`, mirrors every status broadcast for redundancy.
| `alarm` | Module → Display | Raised/cleared for `pump_timeout` and `roller_empty`; carries severity, message copy, and optional metadata (timeout runtime, floats, etc.).

> **Reminder cadence**: Every alarm feeds the universal chirp loop. `system.alarm_chirp_interval_ms` (30 000–600 000 ms) defines how often the buzzer repeats until the alarm clears.

### Message Details

#### `status` (Module → Display)
```json
{
  "type": "status",
  "motor": { "state": "running", "speed": 200, "runtime_ms": 3500, "mode": "auto" },
  "floats": { "main": true, "min": false, "max": false },
  "ato": {
    "pump_running": false,
    "manual_mode": false,
    "paused": false,
    "timeout_alarm": false,
    "tank_level_ml": 11250,
    "tank_capacity_ml": 15000,
    "tank_percent": 75,
    "activations": 12
  },
  "system": {
    "chirp_enabled": true,
    "uptime_s": 1234,
    "alarm_chirp_interval_ms": 120000
  },
  "spool": {
    "full_edges": 528000,
    "used_edges": 1200,
    "percent_remaining": 99,
    "empty_alarm": false,
    "calibrating": false,
    "total_length_mm": 50000,
    "sample_length_mm": 10000,
    "core_diameter_mm": 19,
    "media_thickness_um": 100,
    "activations": 8
  }
}
```
- `motor.state` enumerates `stopped`, `ramping_up`, `running`, `ramping_down`; dashboards can gate buttons per phase.
- `floats.main/min/max` echo the roller float, reservoir minimum, and maximum switches.
- `ato.*` mirrors pump runtime state plus the tank estimator (`tank_level_ml`, `tank_capacity_ml`, `tank_percent`) and a monotonic `activations` counter that increments every automatically triggered fill and resets on the next `ato_tank_refill` command.
- `system.*` exposes uptime and the audible reminder cadence so settings panels stay bidirectionally synced.
- `spool.*` contains encoder-derived usage as well as calibration helpers and the `activations` counter used for float-driven advances.
- `heater.*` is mandatory for heater modules and must include both raw probes (`thermistors_c[0/1]`), mirrored `primary_temp_c` & `secondary_temp_c`, the active hysteresis band (`setpoint_min_c`, `setpoint_max_c`, and the midpoint `setpoint_c`), `heater_on` (or `output`), the derived `average_temp_c`, `thermistor_delta_c`, and a boolean `thermistor_alarm` flag that trips whenever the probe delta exceeds the configured mismatch threshold. Clamp both `setpoint_min_c` and `setpoint_max_c` to 10–40 °C and publish whichever values the firmware actually uses so the UI can plot the shaded “enabled” band accurately.

#### `module_manifest` (Module → Display)
```json
{
  "type": "module_manifest",
  "module": "PickleSump",
  "name": "PickleSump",
  "version": 1,
  "submodule_count": 2,
  "submodules": [
    {
      "id": "PickleSump.Filter",
      "label": "Filter Roller",
      "category": "filter",
      "capabilities": ["roller", "spool", "alarm"]
    },
    {
      "id": "PickleSump.ATO",
      "label": "ATO Reservoir",
      "category": "ato",
      "capabilities": ["pump", "reservoir", "alarm"]
    }
  ]
}
```
- Sent automatically on every WebSocket connect so dashboards immediately know how many cards to render and how to label them.
- Issue `{ "type": "module_manifest_request" }` any time you need to refresh the manifest (e.g., after a UI reload that did not see the connect event).
- Capability tags are intentionally broad so newer dashboards can group similar tooling without hardcoding PickleSump-specific knowledge.
- Runtime telemetry (`status`, `config`, etc.) still arrives as a combined PickleSump payload today; the manifest is the forward-compatible discovery surface for future submodule-specific feeds.

#### `config_request` (Display → Module)
- `{ "type": "config_request" }` may be issued after UI hydration or whenever a reconnect occurs.
- Firmware always responds immediately with a `config` payload and also auto-publishes `config` after boot or any `set_param` write, so most dashboards only need this once.

#### `config` (Module → Display)
- Mirrors persisted EEPROM values so sliders and toggles never drift.
- Key fields:
  - `motor.max_speed`, `run_time_ms`, `ramp_up_ms`, `ramp_down_ms` (valid ranges: 50–255 PWM, 1 000–30 000 ms runtime, 100–5 000 ms ramps).
  - `ato.mode` (0=auto, 1=manual, 2=paused), `timeout_ms`, `pump_speed`, `tank_capacity_ml`, and the latest `tank_level_ml` snapshot.
  - `system.pump_timeout_ms`, `startup_delay_ms`, `chirp_enabled`, `alarm_chirp_interval_ms`.
  - `spool.full_edges`, `total_length_mm`, `sample_length_mm`, `core_diameter_mm`, `media_thickness_um`.
  - `heater.setpoint_min_c`, `heater.setpoint_max_c` so dashboards know the persisted hysteresis band after boots or parameter writes.

#### `set_param` (Display → Module)
- Envelope: `{ "type": "set_param", "param": "<name>", "value": <number/bool> }`.
- Every successful write updates EEPROM, applies the new runtime behavior immediately, and causes firmware to broadcast a fresh `config` so the UI reflects the persisted state.
- See the parameter table below for accepted names, ranges, and semantics (aliases such as `motor_speed`/`motor_max_speed` remain supported for compatibility).
- Heater bands now use two helpers so firmware knows when to toggle output:
  - `heater_setpoint_min_c` · lower hysteresis bound in °C (clamped to 10–40 °C).
  - `heater_setpoint_max_c` · upper bound in °C (also 10–40 °C, must be ≥ the min value before firmware applies it).
- Firmware responsibilities when these arrive:
  1. Clamp each value to 10–40 °C, swap or reject if `min > max`, then persist both numbers together so restarts keep the same band.
  2. Republish `config` immediately with the stored `heater.setpoint_min_c` / `heater.setpoint_max_c` pair so UIs hydrate correctly.
  3. Echo the live band inside every `status.heater` payload via `setpoint_min_c` and `setpoint_max_c`; the frontend shades this range on the chart and exposes it in the heater drawer.
  4. Update the local control loop to energize the heater whenever `average_temp_c` (or your preferred control temperature) drops below `setpoint_min_c` and disengage when it crosses `setpoint_max_c`.

#### `cycle_log` (Module → Display)
```json
{
  "type": "cycle_log",
  "timestamp_s": 12345,
  "cycle_type": "roller_auto",
  "duration_ms": 5000,
  "trigger": "main_float",
  "timeout": false
}
```
- Streams immediately after every roller or pump cycle completes so history graphs never miss short events.
- `cycle_type` enumerates `roller_manual`, `roller_auto`, `pump_normal`, `pump_manual`.
- `trigger` highlights why the run started (`main_float`, `manual_button`, `auto_timer`, `min_float`).
- `timeout` only appears on pump entries and mirrors whether the pump exceeded `pump_timeout_ms`.

#### `spool_activations` (Module → Display)
- Mirrors the monotonic `spool.activations` counter (float-driven runs since the last `spool_reset`) once per second.
- Includes a convenience `percent_remaining` snapshot so lightweight collectors can trend roll usage without parsing the full `status` block.

#### `ato_activations` (Module → Display)
- Mirrors the monotonic `ato.activations` counter so dashboards know how many automatic reservoir fills fired since the last `ato_tank_refill`.
- Each frame repeats `tank_level_ml`, `tank_capacity_ml`, and `tank_percent` so collectors can trend refill frequency without parsing the main `status` payload.

#### `alarm` (Module → Display)
```json
{
  "type": "alarm",
  "alarm": {
    "code": "pump_timeout",
    "severity": "warning",
    "active": true,
    "timestamp_s": 12345,
    "message": "ATO pump exceeded pump_timeout_ms",
    "meta": { "timeout_ms": 120000, "runtime_ms": 130000 }
  }
}
```
- Emitted on both assert and clear events so banners and logs stay synchronized.
- Current alarm codes: `pump_timeout` and `roller_empty`.
- New alarm code: `thermistor_mismatch` asserts when the two heater probes differ beyond the configured delta. Include `delta_c`, `threshold_c`, `primary_temp_c`, and `secondary_temp_c` inside `alarm.meta` so the UI can display both readings.
- Firmware also records alarm context in the next `cycle_log` entry and inside the periodic `status` payload so late subscribers still see the latched state.

### Spool + Calibration Workflow
- Spool telemetry exposes encoder-derived `full_edges`, `used_edges`, `percent_remaining`, and a `calibrating` flag so the UI can gate controls per spool.
- `spool.activations` increments only when the float switch triggers an automatic advance (manual button jogs are ignored) and resets with every `spool_reset`. Firmware mirrors that counter inside each `status` payload and also emits a `spool_activations` frame alongside the heartbeat so UI logs capture every change even if a prior frame was missed.
- `spool_reset` clears usage counters the second a new roll is installed.
- Calibration uses a 10 m pull (`spool_calibrate_start` → operator pulls sample → `spool_calibrate_finish` with the full-roll length). Firmware snapshots encoder deltas, recomputes `full_edges`, and republishes config/status to show the new baseline. `spool_calibrate_cancel` or a 5-minute timeout aborts gracefully.

#### Spool Reset Workflow
1. UI sends `{ "type": "set_param", "param": "spool_reset", "value": 1 }` when an operator confirms a roll change.
2. Firmware treats any non-zero value as a momentary command, calls `resetSpoolEstimate()`, zeros `spool.used_edges`, recomputes remaining/percent fields, and clears `spool.empty_alarm`.
3. A fresh `status` (and usually `config`) payload is emitted immediately so dashboards update progress bars without waiting for the next 1 s tick.

#### Automatic Roll Calibration Steps
1. UI issues `{ "param": "spool_calibrate_start", "value": 1 }`; firmware snapshots the encoder count, sets `spool.calibrating = true`, chirps, and publishes updated status/config frames.
2. Operator manually pulls exactly 10 000 mm of media (UI can show instructions/progress).
3. UI completes the flow with `{ "param": "spool_calibrate_finish", "value": <roll_length_mm> }`. Supplying `0` reuses the stored `spool_length_mm`; any non-zero value (10 000–200 000 mm) is persisted as the new roll length.
4. Firmware computes `full_edges = measured_edges * (roll_length_mm / 10 000)`, stores the result, resets spool usage, and republishes status/config.
5. `{ "param": "spool_calibrate_cancel" }` or an automatic 5-minute timeout clears the flag without altering EEPROM; both cases push updated payloads so UI buttons re-enable.
6. Encoder inactivity while `spool.calibrating` is true will still abort after the timeout, accompanied by a chirp to alert the operator.
7. The derived `full_edges` value leverages the configured `spool_core_diameter_mm` (default 19 mm) and `spool_media_thickness_um` (default 100 µm) to compensate for the changing wrap circumference as the roll unwinds.

### ATO Reservoir Modeling & Refills
- The firmware integrates pump runtime using the characterized 750 ml per 20 s flow rate to maintain `ato.tank_level_ml` and persists the estimate whenever the pump stops.
- Default tank capacity is 15 000 ml; change it with `{ "param": "ato_tank_capacity_ml", "value": <5000-50000> }` to match your reservoir.
- After a full refill, issue `{ "param": "ato_tank_refill", "value": 1 }` to snap the estimate to 100 %. For partial top-ups, send `ato_tank_level_ml` with the measured volume (clamped to 0–capacity) so dashboards and the estimator stay aligned.
- `ato_tank_refill` also clears the `ato.activations` counter (and the mirrored `ato_activations` feed) so refill charts represent the new tank interval cleanly.
- UI “Tank Refilled” buttons should fire the refill command only on operator confirmation to avoid drift.

### Pump Timeout Slider Behavior
1. The UI hydrates its slider from `system.pump_timeout_ms` contained inside every `config` payload.
2. Moving the slider publishes `{ "param": "pump_timeout_ms", "value": <60000-600000> }`; firmware applies it immediately and writes the new ceiling to EEPROM.
3. While the pump runs, the elapsed runtime is compared to this limit. Exceeding it stops the pump, asserts `ato.timeout_alarm`, and marks the matching `cycle_log.timeout = true`.
4. Clearing the condition (float recovery or operator action) causes firmware to emit another `alarm` frame with `active: false`, keeping the UI state machine in sync.

### Alarm Reminder Loop
- All alarms feed the universal chirp loop. On assert, the buzzer plays once immediately and then repeats every `system.alarm_chirp_interval_ms` (30 000–600 000 ms) until the alarm clears.
- Adjust the cadence through `{ "param": "alarm_chirp_interval_ms", "value": <ms> }` so facilities can tailor reminder intensity.
- `roller_empty` automatically gates float-triggered advances until a manual jog produces encoder pulses again, ensuring the alarm can only clear once the obstruction is resolved.

### Reliability and Watchdogs
- **Module side**: WiFi + WebSocket reconnection timers (5 s) keep telemetry streaming without user action.
- **Display/AP side**: Install `infrastructure/scripts/reefnet-watchdog.sh` and `infrastructure/systemd/reefnet-watchdog.service` on the Pi so `wlan1`, hostapd, dnsmasq, and Docker services are relaunched whenever the USB NIC resets.
- **UGREEN CM762 / AIC8800**: After installing the DKMS package and running `usb_modeswitch`, the helper scripts prefer the `aic8800_fdrv` module and fall back to `88XXau` only if needed. Monitor stability with `journalctl -fu reefnet-watchdog` while power-cycling modules.

### Connection Management & Reconnection Logic
1. Module boots, joins `ReefNet`, and opens the WebSocket to `192.168.4.1:80/ws`.
2. Firmware immediately transmits a full `config` payload followed by the first `status` frame so dashboards can hydrate sliders before any user action.
3. UI optionally issues a single `config_request` to confirm the round-trip path, then listens for the 1 Hz heartbeat.
4. Every `set_param` write triggers another `config` broadcast, guaranteeing EEPROM and the UI never diverge.
5. If WiFi or WebSocket drops, both clients retry every 5 s; local control loops continue offline. Once the socket reestablishes, periodic status resumes automatically.
6. The ReefNet watchdog keeps hostapd/dnsmasq and the USB NIC healthy so reconnect storms do not require operator intervention.

### Testing Without Hardware
Use the mock helpers in the reference firmware (`sendTestStatusMessage()`) to inject representative JSON payloads and validate dashboards, or publish ad-hoc frames through `ws.textAll()` when iterating on the UI.

## Module Info

### Module Type Framework
- Every module now surfaces a high-level `module_type` so the backend and UI can render purpose-built controls. The platform currently recognizes four canonical types: **Heater**, **Filter**, **ATO**, and **Sensor** (fallback for telemetry-only devices).
- Declare intent explicitly inside `module_manifest.submodules[].category` or `kind`. Categories of `filter`, `roller`, `spool`, or `media` map to the Filter experience; `ato`, `pump`, `reservoir`, or `refill` map to the ATO experience; `heater` locks the Heater controls. Anything else that still publishes telemetry lands in the Sensor layout.
- If you cannot emit a manifest yet, the backend infers the type heuristically: heater keywords in the `module_id`/`label` or a `status.heater` payload mark the module as Heater, any `status.spool` metrics promote it to Filter, and any `status.ato` metrics promote it to ATO. Make sure your firmware includes at least one of those payloads so inference stays deterministic.
- The `module_type` value is stored with each module record and forwarded to `/api/modules`. Frontend cards display a colored badge that matches the type, so changing the manifest or payloads is the only required step—no Svelte changes per module are necessary.
- When adding a brand-new module, start by cloning the manifest template in this guide, assign meaningful `submodules`, and choose the category that best represents each card. That keeps the inference logic honest and prevents regressions when more module types roll out later.

### Hardware & Libraries
- Target: ESP32 or ESP32-S3 (built-in WiFi).
- Tooling: PlatformIO project with `framework = arduino` plus `ESP Async WebServer` and `ArduinoJson` (AsyncTCP auto-installs).
- Example `platformio.ini`:
  ```ini
  [env:esp32s3]
  platform = espressif32
  board = esp32-s3-devkitc-1
  framework = arduino

  lib_deps =
      me-no-dev/ESP Async WebServer@^1.2.4
      bblanchon/ArduinoJson@^6.21.3

  monitor_speed = 115200
  ```

### Runtime Payloads
- `status.motor`: `state`, `speed`, `runtime_ms`, `mode`.
- `status.floats`: `main`, `min`, `max` switches for roller and ATO thresholds.
- `status.ato`: `pump_running`, `manual_mode`, `paused`, `timeout_alarm`, plus the estimated `tank_level_ml`, `tank_capacity_ml`, and derived `tank_percent` computed from the 750 ml/20 s pump flow model.
- `status.system`: `chirp_enabled`, `uptime_s`, `alarm_chirp_interval_ms`.
- `status.spool`: Encoder-derived usage, calibration flags, geometry (core diameter, media thickness, total/sample length).
- `config.motor`: `max_speed`, `run_time_ms`, `ramp_up_ms`, `ramp_down_ms`.
- `config.ato`: `mode`, `timeout_ms`, `pump_speed`, `pump_running`.
- `config.system`: `pump_timeout_ms`, `startup_delay_ms`, `chirp_enabled`, `alarm_chirp_interval_ms`.
- `config.spool`: Persisted `full_edges`, `total_length_mm`, `sample_length_mm`, `core_diameter_mm`, `media_thickness_um`.

### Parameter Surface (`set_param`)
| Parameter | Type | Range | Description |
| --- | --- | --- | --- |
| `motor_speed` / `motor_max_speed` | uint8 | 50–255 | Roller PWM ceiling (aliases accepted for compatibility). |
| `motor_runtime` | uint32 | 1 000–30 000 | Roller run time per activation in milliseconds. |
| `ramp_up` | uint16 | 100–5 000 | Motor acceleration window in milliseconds. |
| `ramp_down` | uint16 | 100–5 000 | Motor deceleration window in milliseconds. |
| `pump_speed` | uint8 | 0–255 | Live PWM duty for the ATO pump (updates immediately if the pump is running). |
| `pump_timeout_ms` | uint32 | 60 000–600 000 | Maximum continuous pump runtime before forcing a stop and asserting `ato.timeout_alarm`. |
| `chirp_enabled` | bool | 0–1 | Enables the buzzer feedback loop. |
| `alarm_chirp_interval_ms` | uint32 | 30 000–600 000 | Reminder cadence for active alarms. |
| `ato_mode` | uint8 | 0–2 | ATO state machine (0 = auto, 1 = manual force-on, 2 = paused/emergency stop). |
| `ato_tank_capacity_ml` | uint32 | 5 000–50 000 | Reservoir size baseline in millilitres. |
| `ato_tank_level_ml` | uint32 | 0–capacity | Manual override of the estimator after partial refills or visual inspections. |
| `ato_tank_refill` | uint8 | 0–1 | Momentary command to snap `tank_level_ml` to the configured capacity after a confirmed refill and reset `ato.activations`. |
| `spool_reset` | uint8 | 0–1 | Clears usage counters, marks the spool full, and releases `spool.empty_alarm`. |
| `spool_length_mm` | uint32 | 10 000–200 000 | Full-roll media length used during calibration. |
| `spool_core_diameter_mm` | uint16 | 12–80 | Mechanical core/shaft diameter in millimetres. |
| `spool_media_thickness_um` | uint16 | 40–400 | Media thickness in microns for the geometric wrap model. |
| `spool_calibrate_start` | uint8 | 0–1 | Snapshot encoder edges and enter calibration mode (UI prompts for 10 m pull). |
| `spool_calibrate_finish` | uint32 | 0 or 10 000–200 000 | Exit calibration, derive `full_edges`, and optionally overwrite the stored roll length (`0` reuses the previous value). |
| `spool_calibrate_cancel` | uint8 | 0–1 | Abort calibration and restore normal operation. |
| `heater_setpoint_min_c` | float | 10.0–40.0 | Lower heater hysteresis bound in °C; persist and mirror it in `status.heater.setpoint_min_c`. |
| `heater_setpoint_max_c` | float | 10.0–40.0 | Upper heater hysteresis bound in °C (must be ≥ the min before applying); mirror it in `status.heater.setpoint_max_c`. |

All setters publish an immediate `config` refresh so downstream sliders and toggles reflect the persisted value even if the WebSocket briefly disconnects.

### Cycle Logging & Alarms
- Every pump/roller cycle emits `cycle_log` with `timestamp_s`, `cycle_type`, `duration_ms`, `trigger`, and an optional `timeout` flag for pump overrun events.
- `alarm` payloads surface both asserts and clears with `code`, `severity`, `active`, `timestamp_s`, `message`, and optional structured `meta` data (e.g., runtime vs timeout values).
- Firmware also records alarm context inside the next `cycle_log` entry for later audits while the alarm channel keeps the UI responsive.

### Build & Deployment
1. `pio init --board esp32-s3-devkitc-1` (or your hardware).
2. Drop the reference sketch into `src/main.cpp`.
3. `pio run --target upload` to flash, then `pio device monitor` for logs.
4. Confirm "WebSocket client connected" messages once the module hits the display/AP.

## Module Troubleshooting
- **Module will not join WiFi**: Verify SSID/password constants, confirm the display/AP is broadcasting (check for "Starting WiFi AP" logs), and ensure the module is within 2.4 GHz range.
- **WebSocket refuses to connect**: Make sure WiFi is already connected, confirm `WS_SERVER_IP`/`WS_SERVER_PORT` match the display, and ensure the Async WebServer is running on `/ws`.
- **No status messages on the display**: Inspect serial logs on both sides for JSON errors, confirm the socket is connected, and check for bandwidth issues if many devices share the channel.
- **Frequent disconnects**: Measure RSSI, relocate the AP closer to the sump, and reduce 2.4 GHz interference; increase reconnect intervals if your environment is especially noisy.

### Migration from CAN & Troubleshooting
- **Benefits vs CAN**: Built-in WiFi eliminates the external transceiver, extends range to room-scale deployments, exposes human-readable JSON, and unlocks browser-based dashboards.
- **Tradeoffs**: Expect slightly higher latency (10–50 ms), marginally higher power draw, and the need to maintain WiFi credentials/AP health—hence the watchdog tooling above.
- **What changed in firmware**: CAN drivers were removed, broadcast cadence relaxed to 1 Hz, WiFi/WebSocket reconnection loops added, and every binary CAN frame was replaced with the JSON schema documented here.
- **Common diagnostics**: If WiFi/WebSocket loops fail, confirm SSID/password, double-check `WS_SERVER_IP`, inspect serial logs for JSON parse errors (increase `StaticJsonDocument` sizes when payloads grow), and monitor RSSI; most disconnect storms are interference-related.

## Frontend & Display

### Raspberry Pi Access Point
- `wlan1` hosts the AP (`hostapd`, `dnsmasq`) while `wlan0`/`eth0` stays on WAN for Docker pulls.
- `infrastructure/scripts/reefnet-startup.sh` is the idempotent bring-up helper: reloads the WiFi driver, reapplies `192.168.4.1/24`, refreshes NAT rules, and launches `docker compose up -d`.
- Install the watchdog service so any NIC reset restarts hostapd/dnsmasq and re-runs the startup script automatically.

#### UGREEN CM762 / AIC8800 USB Adapter
1. Install prerequisites and the vendor DKMS bundle so the adapter leaves USB-mass-storage mode:
   ```bash
   sudo apt-get install -y usb-modeswitch usb-modeswitch-data build-essential dkms \
        linux-headers-$(uname -r)
   cd /tmp && wget -O UGREEN-CM762.zip "https://download.lulian.cn/2025-drive/UGREEN-CM762-35264_USB%E6%97%A0%E7%BA%BF%E7%BD%91%E5%8D%A1%E9%A9%B1%E5%8A%A8_V1.4.zip"
   unzip -q -o UGREEN-CM762.zip -d CM762
   sudo dpkg -i /tmp/CM762/Linux/linux_driver_package/aic8800d80fdrvpackage.deb
   ```
2. Force the mode switch once; udev rules from the `.deb` keep it persistent:
   ```bash
   sudo usb_modeswitch -v 0xa69c -p 0x5723 -KQ
   lsusb | grep -i aic   # expect a69c:8d80 (or 368b:8d85 after re-enumeration)
   ```
3. Deploy `reefnet-startup.sh` + `reefnet-watchdog.service` so `aic8800_fdrv` loads before any legacy `88XXau` fallback, reapply `192.168.4.1/24` to `wlan1`, and restart hostapd/dnsmasq whenever the USB NIC flaps. Monitor with `journalctl -fu reefnet-watchdog` while power-cycling modules.

### Display Controller (ESP32)
- Runs the AP + WebSocket server when you want an all-in-one handheld controller.
- Reference firmware centers around `onWebSocketEvent`, `handleStatusMessage`, `handleConfigMessage`, `handleCycleLogMessage`, `handleAlarmMessage`, `sendConfigRequest()`, and `setParameter()` helpers so UI elements (buttons, touch handlers, TFT widgets) can call strongly-typed functions instead of crafting raw JSON.
- Track `doc["module"]` in each handler if you intend to supervise multiple field devices from one display enclosure.

#### Quick Start
1. `pio init --board esp32-s3-devkitc-1` (or any ESP32 board you prefer).
2. Drop the sample display firmware into `src/main.cpp` and ensure `platformio.ini` lists `ESP Async WebServer` and `ArduinoJson` inside `lib_deps` (AsyncTCP auto-installs).
3. Flash with `pio run --target upload`, open `pio device monitor`, and wait for "WebSocket client connected" logs as modules join.

#### Reference Firmware Highlights
- WiFi AP bootstraps via `WiFi.softAP()`; the helper prints IP/MAC for quick sanity checks.
- `AsyncWebServer` + `AsyncWebSocket` handle concurrent modules; `ws.cleanupClients()` in `loop()` keeps memory tidy.
- `ModuleStatus` struct caches the latest telemetry so rendering code (TFT, OLED, serial) can reference a single snapshot.
- `setParameter()` centralizes outbound commands, automatically serializing JSON and broadcasting via `ws.textAll()`.
- Example helper methods (`setMotorSpeed`, `setAtoMode`, `emergencyStopATO`, `resumeATO`, `enableChirp`) simply call `setParameter()` with constrained values, making it trivial to wire UI buttons.

#### Customization & Extensions
- **WiFi Credentials**: Change `AP_SSID` / `AP_PASSWORD` and mirror those updates inside every PickleSump firmware build.
- **Multiple Modules**: Maintain one `ModuleStatus` struct per device, route incoming JSON via `doc["module"]`, and selectively update each dashboard card.
- **Display Rendering**: Replace `printModuleStatus()` with TFT/OLED drawing code; update on timers or WebSocket callbacks.
- **Button/Touch Input**: Map physical controls to helper calls (e.g., `BTN_ATO_STOP` → `emergencyStopATO()`); debounce as needed.
- **Historical Data**: Store `cycle_log` entries in a circular buffer to graph top-offs per hour/day; prune to avoid RAM pressure.
- **Authentication Hooks**: Require an unlock pin before mutating critical parameters by wrapping `setParameter()` with an `authenticated` guard.
- **Health Monitoring**: Periodically compare `millis()` to `lastUpdate`; after 30 s of silence, raise a local alarm or prompt the user to check the module.

#### Network Configuration Helpers
- Default AP settings (channel auto, max 4 stations) already work, but you can pin addresses:
  ```cpp
  WiFi.softAPConfig(IPAddress(192,168,10,1), IPAddress(192,168,10,1), IPAddress(255,255,255,0));
  WiFi.softAP(AP_SSID, AP_PASSWORD, 6, false, 4);
  ```
- Inspect connected modules for debugging:
  ```cpp
  wifi_sta_list_t stationList;
  esp_wifi_ap_get_sta_list(&stationList);
  ```

#### Troubleshooting – Display Side
- **AP not broadcasting**: Confirm `WiFi.mode(WIFI_AP)` precedes `WiFi.softAP`, experiment with different channels, and ensure no other AP uses the same SSID.
- **Modules cannot join**: Re-check credentials, RSSI, and connection limits; shorten the password if you suspect compatibility quirks.
- **WebSocket errors**: Verify `ESP Async WebServer`/`AsyncTCP`/`ArduinoJson` versions, ensure the server is running on `/ws`, and increase `StaticJsonDocument` sizes if payloads grow.
- **JSON parse failures**: Dump payloads via `serializeJsonPretty` to confirm structure, then bump document capacity.
- **Memory pressure**: Call `ws.cleanupClients()` regularly, trim history buffers, and monitor `ESP.getFreeHeap()`.

#### Advanced Utilities
- Broadcast emergency stops by calling `ws.textAll()` with `{ "param": "ato_mode", "value": 2 }` so every module pauses simultaneously.
- Build password-protected control panels by gating `setParameter()` calls behind an authentication flag.
- Implement local watchdogs that alert the operator if `lastUpdate` exceeds 30 s, complementing the module-side reconnection logic.

#### Testing Without Hardware (Display Side)
- Use helpers like:
  ```cpp
  void sendTestStatusMessage() {
    const char* payload = R"({...})";
    StaticJsonDocument<512> doc;
    deserializeJson(doc, payload);
    handleStatusMessage(doc);
  }
  ```
- Inject canned frames through `ws.textAll()` to observe UI responses before any field devices come online.

### Svelte Dashboard & Backend Bridge
- **Dependencies**: `python3 -m venv .venv && pip install -e backend[dev]`, `cd frontend && npm install`.
- **Dev servers**:
  - Backend: `cd backend && ../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`.
  - Frontend: `cd frontend && npm run dev -- --host` (Vite proxies `/api` to the backend).
- **Docker option**: `docker compose up --build` to launch FastAPI, the static Svelte build (via NGINX), and Mosquitto in one stack.
- **VS Code tasks**: `Pickle Reef Dev Stack` (Docker Compose) and `Pickle Reef Frontend` (Vite dev server) mirror the commands above.
- The dashboard consumes the backend’s `/api` telemetry plus `/ws` sockets, buffers spool usage per roll (localStorage helpers), and exposes time-window presets (1 h → 1 y) for usage charts.

### Monitoring & Testing
- `pytest backend/tests -q` covers smoke and telemetry flow.
- Frontend `npm run build` ensures Svelte + Vite compile cleanly before Docker image builds.
- When hardware is offline, the dashboard falls back to demo data; once modules reconnect, the stored spool baselines plus live `status` frames keep metrics accurate per roll.

## Memory Usage
- WiFi/WebSocket firmware consumes roughly 46 KB of RAM (≈14 %) and 923 KB of flash (≈70 %) on ESP32-S3 builds—well within headroom but higher than the legacy CAN sketch.
- Keep an eye on heap usage if you store large telemetry histories or expand the JSON schema; the Async stack prefers periodic `ws.cleanupClients()` calls.

## Future Enhancements
- Add OTA update hooks so modules can refresh firmware directly over ReefNet.
- Introduce MQTT bridges or REST endpoints on the display for broader integrations.
- Store WiFi credentials in NVS to support field provisioning without recompiling.
- Consider mDNS or SSDP discovery so new modules can locate the display automatically.
- Add SPIFFS/SD logging for long-term spool and ATO analytics when offline.

---
Use this document as the canonical entry point: follow the WiFi protocol contract, keep firmware fields in sync, and rely on the frontend/backend commands here when bootstrapping a new controller or dashboard environment.
