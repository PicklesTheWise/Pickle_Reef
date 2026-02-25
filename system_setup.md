# System Setup

This guide condenses the WiFi/WebSocket protocol, module firmware expectations, and frontend stack into a single reference so you can provision every layer of Pickle Reef without jumping between documents.

## WiFi Protocol

### ReefNet Topology
- **Display/AP role**: The ESP32/S3 (or Raspberry Pi host) broadcasts the `ReefNet` SSID (`ReefController2026`) on `192.168.4.1/24` and exposes a WebSocket server on port `80` at `/ws`.
- **Module role**: Each PickleRoller boots in STA mode, joins the ReefNet AP, and dials `ws://192.168.4.1/ws`. Local control loops run uninterrupted even if WiFi drops.
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
| `config_request` | Display → Module | Ask for the persisted parameter block; usually sent once after UI load.
| `config` | Module → Display | Full parameter snapshot (motor window, ATO mode, chirp cadence, spool geometry) pushed after connect or any change.
| `set_param` | Display → Module | Mutate a single setting (speed, runtime, pump timeout, ATO mode, spool calibration helpers, alarm cadence, etc.).
| `cycle_log` | Module → Display | Emits immediately when a roller or pump cycle ends so historical charts never miss short events.
| `spool_activations` | Module → Display | 1 Hz counter of float-triggered advances since the last `spool_reset`; piggybacks on every status broadcast so dashboards never miss increments.
| `alarm` | Module → Display | Raised/cleared for `pump_timeout` and `roller_empty`; carries severity, message copy, and optional metadata (timeout runtime, floats, etc.).

> **Reminder cadence**: Every alarm feeds the universal chirp loop. `system.alarm_chirp_interval_ms` (30 000–600 000 ms) defines how often the buzzer repeats until the alarm clears.

### Spool + Calibration Workflow
- Spool telemetry exposes encoder-derived `full_edges`, `used_edges`, `percent_remaining`, and a `calibrating` flag so the UI can gate controls per spool.
- `spool.activations` increments only when the float switch triggers an automatic advance (manual button jogs are ignored) and resets with every `spool_reset`. Firmware mirrors that counter inside each `status` payload and also emits a `spool_activations` frame alongside the heartbeat so UI logs capture every change even if a prior frame was missed.
- `spool_reset` clears usage counters the second a new roll is installed.
- Calibration uses a 10 m pull (`spool_calibrate_start` → operator pulls sample → `spool_calibrate_finish` with the full-roll length). Firmware snapshots encoder deltas, recomputes `full_edges`, and republishes config/status to show the new baseline. `spool_calibrate_cancel` or a 5-minute timeout aborts gracefully.

### Reliability and Watchdogs
- **Module side**: WiFi + WebSocket reconnection timers (5 s) keep telemetry streaming without user action.
- **Display/AP side**: Install `infrastructure/scripts/reefnet-watchdog.sh` and `infrastructure/systemd/reefnet-watchdog.service` on the Pi so `wlan1`, hostapd, dnsmasq, and Docker services are relaunched whenever the USB NIC resets.
- **UGREEN CM762 / AIC8800**: After installing the DKMS package and running `usb_modeswitch`, the helper scripts prefer the `aic8800_fdrv` module and fall back to `88XXau` only if needed. Monitor stability with `journalctl -fu reefnet-watchdog` while power-cycling modules.

### Testing Without Hardware
Use the mock helpers in the reference firmware (`sendTestStatusMessage()`) to inject representative JSON payloads and validate dashboards, or publish ad-hoc frames through `ws.textAll()` when iterating on the UI.

## Module Info

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
- `status.ato`: `pump_running`, `manual_mode`, `paused`, `timeout_alarm`.
- `status.system`: `chirp_enabled`, `uptime_s`, `alarm_chirp_interval_ms`.
- `status.spool`: Encoder-derived usage, calibration flags, geometry (core diameter, media thickness, total/sample length).
- `config.motor`: `max_speed`, `run_time_ms`, `ramp_up_ms`, `ramp_down_ms`.
- `config.ato`: `mode`, `timeout_ms`, `pump_speed`, `pump_running`.
- `config.system`: `pump_timeout_ms`, `startup_delay_ms`, `chirp_enabled`, `alarm_chirp_interval_ms`.
- `config.spool`: Persisted `full_edges`, `total_length_mm`, `sample_length_mm`, `core_diameter_mm`, `media_thickness_um`.

### Parameter Surface (`set_param`)
- Motor: `motor_speed`, `motor_max_speed`, `motor_runtime`, `ramp_up`, `ramp_down`.
- Pump: `pump_speed`, `pump_timeout_ms`, `ato_mode` (0=auto, 1=manual, 2=paused).
- Alerts: `chirp_enabled`, `alarm_chirp_interval_ms`.
- Spool: `spool_reset`, `spool_length_mm`, `spool_core_diameter_mm`, `spool_media_thickness_um`, `spool_calibrate_start/finish/cancel`.
- All setters reply with a fresh `config`, so the dashboard never displays stale values.

### Cycle Logging & Alarms
- Every pump/roller cycle emits `cycle_log` with `timestamp_s`, `cycle_type`, `duration_ms`, `trigger`, and an optional `timeout` flag for pump overrun events.
- `alarm` payloads surface both asserts and clears with `code`, `severity`, `active`, `timestamp_s`, `message`, and optional structured `meta` data (e.g., runtime vs timeout values).
- Firmware also records alarm context inside the next `cycle_log` entry for later audits while the alarm channel keeps the UI responsive.

### Build & Deployment
1. `pio init --board esp32-s3-devkitc-1` (or your hardware).
2. Drop the reference sketch into `src/main.cpp`.
3. `pio run --target upload` to flash, then `pio device monitor` for logs.
4. Confirm "WebSocket client connected" messages once the module hits the display/AP.

### Migration from CAN & Troubleshooting
- WiFi removes the CAN transceiver, lowers cabling requirements, delivers JSON visibility, and opens Web-based monitoring, at the cost of slightly higher latency and more radio management.
- If WiFi or WebSocket loops fail: verify SSID/password, ensure `WS_SERVER_IP` matches the AP, and watch for JSON parse errors (bump `StaticJsonDocument` sizes if payloads grow).
- Frequent disconnects usually mean weak 2.4 GHz signal—move the AP closer or reduce interference.

## Frontend & Display

### Raspberry Pi Access Point
- `wlan1` hosts the AP (`hostapd`, `dnsmasq`) while `wlan0`/`eth0` stays on WAN for Docker pulls.
- `infrastructure/scripts/reefnet-startup.sh` is the idempotent bring-up helper: reloads the WiFi driver, reapplies `192.168.4.1/24`, refreshes NAT rules, and launches `docker compose up -d`.
- Install the watchdog service so any NIC reset restarts hostapd/dnsmasq and re-runs the startup script automatically.

### Display Controller (ESP32)
- Runs the AP + WebSocket server when you want an all-in-one handheld controller.
- Sample firmware (`onWebSocketEvent`, `handleStatusMessage`, `setParameter`, etc.) in the legacy WiFi doc doubles as a template for TFT/OLED dashboards and button handlers (emergency stop, resume ATO, manual roller commands).
- Add modules by tracking `doc["module"]` and routing status/config/alarm handling per device struct.

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

---
Use this document as the canonical entry point: follow the WiFi protocol contract, keep firmware fields in sync, and rely on the frontend/backend commands here when bootstrapping a new controller or dashboard environment.
