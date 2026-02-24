# PickleRoller WiFi/WebSocket Protocol Documentation

## Overview
The PickleRoller ATO Controller now uses WiFi and WebSocket for communication with the reef aquarium display controller, replacing the previous CAN bus implementation. This provides longer range, easier setup, and human-readable JSON messages.

## Hardware Requirements
- **ESP32 with WiFi** (built-in to D1 R32)
- **No additional hardware needed** (no CAN transceiver required)
- **WiFi Network**: Display runs as Access Point, modules connect as clients

## Network Architecture

```
Display Controller (ESP32-S3)
  ├─ WiFi Access Point (AP Mode)
  │  SSID: "ReefNet"
  │  Password: "ReefController2026"
  │  IP: 192.168.4.1
  └─ WebSocket Server (Port 80, path /ws)
      ↑
      | WiFi Connection
      ↓
PickleRoller Module (ESP32)
  └─ WiFi Client (Station Mode)
      └─ WebSocket Client
```

## Configuration

### WiFi Credentials (in main.cpp)
```cpp
const char* WIFI_SSID = "ReefNet";           // Display's WiFi AP name
const char* WIFI_PASSWORD = "ReefController2026";   // WiFi password
const char* WS_SERVER_IP = "192.168.4.1";           // Display's IP (AP mode default)
const uint16_t WS_SERVER_PORT = 80;                 // WebSocket server port
const char* MODULE_NAME = "PickleRoller";            // Unique module identifier
```

### Status Broadcast Interval
- **1 second** (reduced from CAN's 100ms to conserve WiFi bandwidth)
- Automatically sent when WebSocket is connected
- Includes all real-time system status

---

## WebSocket Message Format

All messages are JSON objects with the following structure:

```json
{
  "module": "PickleRoller",
  "type": "<message_type>",
  ...additional fields...
}
```

---

## Message Types

### 1. Status Broadcast (Module → Display)
**Type**: `status`  
**Frequency**: Every 1 second (automatic)  
**Direction**: PickleRoller → Display

#### Message Structure:
```json
{
  "module": "PickleRoller",
  "type": "status",
  "motor": {
    "state": "stopped|ramping_up|running|ramping_down",
    "speed": 0-255,
    "runtime_ms": 0,
    "mode": "manual|auto"
  },
  "floats": {
    "main": false,
    "min": false,
    "max": false
  },
  "ato": {
    "pump_running": false,
    "manual_mode": false,
    "paused": false,
    "timeout_alarm": false
  },
  "system": {
    "chirp_enabled": true,
                "sample_length_mm": 10000,
                "core_diameter_mm": 19,
                "media_thickness_um": 100
    },
    "spool": {
        "full_edges": 528000,
        "used_edges": 1200,
        "remaining_edges": 526800,
        "percent_remaining": 99,
                "empty_alarm": false,
                "core_diameter_mm": 58,
                "media_thickness_um": 100
  }
}
```

#### Field Descriptions:
- **motor.state**: Current roller motor state
  - `stopped`: Motor not running
  - `ramping_up`: Motor accelerating to max speed
  - `running`: Motor at full speed
  - `ramping_down`: Motor decelerating
- **motor.speed**: Current PWM speed (0-255)
- **motor.runtime_ms**: Milliseconds since motor started (0 when stopped)
- **motor.mode**: `manual` or `auto` operation
- **floats.main**: Main roller float switch active (true = triggered)
- **floats.min**: Minimum water level (true = tank empty)
- **floats.max**: Maximum water level (true = tank full)
- **ato.pump_running**: ATO pump currently running
- **ato.manual_mode**: ATO in manual override mode
- **ato.paused**: ATO auto mode paused (emergency stop)
- **ato.timeout_alarm**: ATO pump timeout alarm active (pump exceeded the Pump Timeout slider value without float confirmation)
- **system.chirp_enabled**: Buzzer feedback enabled
- **system.uptime_s**: Seconds since module boot
- **system.alarm_chirp_interval_ms**: Reminder chirp cadence (default 120 000 ms); applies to all active alarms
- **spool.full_edges**: Edge budget representing a brand-new filter roll (derived from encoder CPR × expected rotations)
- **spool.used_edges / remaining_edges**: Raw quadrature edges consumed vs. remaining since the last “full spool” reset
- **spool.percent_remaining**: Convenience percentage for dashboards
- **spool.empty_alarm**: `true` when the motor was running but the encoder stopped producing edges (empty/jammed spool)
- **spool.calibrating**: `true` while the user is performing the 10 m pull calibration sequence
- **spool.total_length_mm**: Firmware’s understanding of the full roll length in millimetres (defaults to 50 000 mm until calibrated)
- **spool.sample_length_mm**: Fixed calibration sample distance (10 000 mm)
- **spool.core_diameter_mm**: Mechanical core diameter in millimetres (defaults to 19 mm for the bare shaft)
- **spool.media_thickness_um**: Media thickness in microns (80 gsm copy paper ≈100 µm by default); used for the geometric wrap model

---

### 2. Config Request (Display → Module)
**Type**: `config_request`  
**Frequency**: On demand  
**Direction**: Display → PickleRoller

#### Message Structure:
```json
{
  "type": "config_request"
}
```

#### Response:
Module responds with Config Response message (type `config`). The module also auto-pushes a fresh `config` payload immediately after the WebSocket connection is established and any time a persisted parameter changes, so the display can sync UI controls without waiting for a manual request.

---

### 3. Config Response (Module → Display)
**Type**: `config`  
**Frequency**: In response to config_request or after parameter change  
**Direction**: PickleRoller → Display

#### Message Structure:
```json
{
    "module": "PickleRoller",
    "type": "config",
    "motor": {
        "max_speed": 255,
        "run_time_ms": 5000,
        "ramp_up_ms": 1000,
        "ramp_down_ms": 1000
    },
    "ato": {
        "mode": 0,
        "timeout_ms": 300000,
        "pump_running": false,
        "pump_speed": 255,
        "timeout_alarm": false
    },
    "system": {
        "chirp_enabled": true,
        "pump_timeout_ms": 120000,
        "startup_delay_ms": 5000,
        "alarm_chirp_interval_ms": 120000
    },
    "spool": {
        "full_edges": 528000,
        "total_length_mm": 50000,
        "sample_length_mm": 10000,
        "core_diameter_mm": 19,
        "media_thickness_um": 100
    }
}
```

#### Field Descriptions:
- **motor.max_speed**: Maximum roller motor speed (50-255)
- **motor.run_time_ms**: Roller run duration (1000-30000 ms = 1-30 seconds)
- **motor.ramp_up_ms**: Acceleration time (100-5000 ms)
- **motor.ramp_down_ms**: Deceleration time (100-5000 ms)
- **ato.mode**: ATO operating mode
  - `0` = Auto (normal operation)
  - `1` = Manual (pump manually ON)
  - `2` = Paused (auto mode disabled, emergency stop)
- **ato.timeout_ms**: ATO pump maximum run time before alarm (300000 ms = 5 min)
- **ato.pump_speed**: Current PWM duty (0-255) used when the pump runs; persisted in EEPROM
- **system.pump_timeout_ms**: Backing value for the Pump Timeout slider; defines the max continuous pump runtime before auto-stop/alarm (defaults to 120000 ms = 2 min, adjustable 60000-600000 ms = 1-10 min)
- **system.startup_delay_ms**: Delay before auto pump start after boot (5000 ms)
- **system.alarm_chirp_interval_ms**: Reminder chirp cadence (defaults to 120 000 ms = 2 minutes; UI may extend 30 000–600 000 ms)
- **spool.core_diameter_mm**: Shaft/core diameter parameter used in the wrap model (defaults to 19 mm but configurable 12–80 mm)
- **spool.media_thickness_um**: Media thickness in microns (defaults to 100 µm; valid range 40–400 µm) so the firmware can account for changing circumference as the roll unwinds

---

### 4. Set Parameter (Display → Module)
**Type**: `set_param`  
**Frequency**: When user changes settings  
**Direction**: Display → PickleRoller

#### Message Structure:
```json
{
  "type": "set_param",
  "param": "<parameter_name>",
  "value": <number>
}
```

#### Supported Parameters:

| Parameter Name(s) | Type | Range | Description |
|------------------|------|-------|-------------|
| `motor_speed` / `motor_max_speed` | uint8 | 50-255 | Roller maximum PWM speed (aliases accepted for backward compatibility) |
| `motor_runtime` | uint32 | 1000-30000 | Roller run time in milliseconds |
| `ramp_up` | uint16 | 100-5000 | Ramp up time in milliseconds |
| `ramp_down` | uint16 | 100-5000 | Ramp down time in milliseconds |
| `pump_speed` | uint8 | 0-255 | ATO pump PWM duty (updates live if pump is running) |
| `pump_timeout_ms` | uint32 | 60000-600000 | Backing value for the Pump Timeout slider; defines how long the pump may run before stopping and flagging `timeout_alarm` |
| `chirp_enabled` | bool | 0-1 | Enable/disable buzzer feedback |
| `ato_mode` | uint8 | 0-2 | ATO mode (0=Auto, 1=Manual, 2=Paused) |
| `spool_reset` | uint8 | 0-1 | When 1, clear the roller usage counters, mark the spool as full, and clear `spool.empty_alarm` |
| `spool_length_mm` | uint32 | 10000-200000 | Persisted full-roll length in millimetres; used as the baseline when calibrating |
| `spool_core_diameter_mm` | uint16 | 12-80 | Mechanical core/shaft diameter in millimetres; defaults to the 19 mm bare shaft |
| `spool_media_thickness_um` | uint16 | 40-400 | Media thickness in microns (80 gsm copy stock ≈100 µm); used to compensate for the growing spool diameter |
| `spool_calibrate_start` | uint8 | 0-1 | Snapshot encoder edges and set `spool.calibrating = true`; UI tells the user to pull exactly 10 000 mm |
| `spool_calibrate_finish` | uint32 | 0 or 10000-200000 | Complete calibration; firmware derives `spool.full_edges` from the measured edges and the supplied full-roll length (0 reuses `spool_length_mm`) |
| `spool_calibrate_cancel` | uint8 | 0-1 | Abort calibration and clear `spool.calibrating` |
| `alarm_chirp_interval_ms` | uint32 | 30000-600000 | Sets how often active alarms (pump timeout, roller empty) replay the reminder chirp |

#### Pump Timeout Slider Behavior
- The display hydrates the slider from `system.pump_timeout_ms` in every `config` payload so the UI always reflects the stored timeout.
- Moving the slider sends a `set_param` command with `param` = `pump_timeout_ms`; the module persists the value immediately.
- While the pump is running, the firmware compares the elapsed runtime against this value; if the pump exceeds it before floats clear, the module stops the pump, raises `ato.timeout_alarm`, and marks the corresponding `cycle_log.timeout` field.
- Clearing the alarm (by resolving the float condition or resuming auto mode) resets `ato.timeout_alarm`, so downstream UIs can reset the slider indicator.

#### Spool Reset Workflow
- The frontend sends `{ "type": "set_param", "param": "spool_reset", "value": 1 }` whenever the operator confirms a roll change.
- Firmware should treat any non-zero value as a momentary command: call `resetSpoolEstimate()`, zero `spool.used_edges`, recompute the remaining/percent fields, and clear `spool.empty_alarm`.
- Immediately emit a fresh `status` payload so dashboards update progress bars without waiting for the next 1 s tick. The module may still push `config` afterwards for symmetry.
- Ignore redundant `spool_reset` values of 0 and optionally debounce repeated `1`s if the UI jitters.

#### Automatic Roll Calibration Workflow
1. UI sends `{ "param": "spool_calibrate_start" }` to enter calibration mode. Firmware snapshots the current encoder edge count, sets `spool.calibrating = true`, chirps, and immediately echoes the new state via fresh `status` **and** `config` payloads so the screen can confirm that calibration really began.
2. Operator pulls exactly 10 000 mm (10 m) of media through the roller. The UI can show a progress dialog while this happens.
3. When the sample is complete, UI sends `{ "param": "spool_calibrate_finish", "value": <roll_length_mm> }`. If `value` is `0`, the firmware reuses the previously stored `spool_length_mm` setting. Otherwise, it persists the provided length (clamped to 10 000–200 000 mm).
4. Firmware multiplies the measured edge delta by `roll_length_mm / 10 000` to derive `spool.full_edges`, stores the result in EEPROM, calls `resetSpoolEstimate()`, and pushes fresh `status`/`config` payloads.
5. If the operator aborts, the UI sends `{ "param": "spool_calibrate_cancel" }`, which clears the flag without altering the stored calibration; the module again pushes `status`/`config` so the buttons can re-enable.
- Calibration mode automatically times out after 5 minutes if no finish command is received, clearing `spool.calibrating`, chirping, and emitting a status/config refresh so the UI sees the abort.
- `spool.calibrating` always initializes to `false` on boot; the UI should wait for the bit to flip `false → true` before showing "ready to pull" states.
- Behind the scenes, the firmware solves for the total number of wraps using the configured `spool.core_diameter_mm` (19 mm default) and `spool.media_thickness_um` (100 µm default), then maps the measured encoder edges over the 10 m sample to an accurate full-roll edge budget. Keeping those geometry inputs accurate is what compensates for the changing circumference as the spool unwinds.

#### Alarm Reminder Behavior
- Every alarm transition funnels through the universal reminder loop. When any alarm asserts (currently `roller_empty` and the ATO `pump_timeout`), the module plays an immediate alert chirp and then repeats a reminder every `system.alarm_chirp_interval_ms` (default 120 000 ms = 2 minutes) until the alarm clears.
- The display can adjust the cadence via `{ "type": "set_param", "param": "alarm_chirp_interval_ms", "value": <ms> }`, clamped to 30 000–600 000 ms. Set the value to taste so maintenance staff get periodic nudges without excessive noise.

##### Command Payload Examples (Display → Module)

```json
{ "type": "set_param", "param": "spool_calibrate_start", "value": true }
```

```json
{ "type": "set_param", "param": "spool_calibrate_finish", "value": 50000 }
```

```json
{ "type": "set_param", "param": "spool_calibrate_cancel", "value": true }
```

```json
{ "type": "set_param", "param": "spool_length_mm", "value": 60000 }
```

Send these from the display controller whenever the operator taps the corresponding on-screen buttons (Start, Finish, Cancel, Set Roll Length). The firmware mirrors the current state in the `status` payload’s `spool` object so the UI can disable buttons or show progress as needed.

#### Example Messages:

**Change motor speed to 200:**
```json
{
  "type": "set_param",
  "param": "motor_speed",
  "value": 200
}
```

**Set pump speed to 180:**
```json
{
    "type": "set_param",
    "param": "pump_speed",
    "value": 180
}
```

**Set pump timeout to 2 minutes:**
```json
{
    "type": "set_param",
    "param": "pump_timeout_ms",
    "value": 120000
}
```

**Enable ATO manual mode:**
```json
{
  "type": "set_param",
  "param": "ato_mode",
  "value": 1
}
```

**Pause ATO (emergency stop):**
```json
{
  "type": "set_param",
  "param": "ato_mode",
  "value": 2
}
```

#### Response:
Module responds with updated Config Response message showing new values

---

### 5. Cycle Log (Module → Display)
**Type**: `cycle_log`  
**Frequency**: Immediately when a roller or pump cycle completes (push-on-change, no polling delays)  
**Direction**: PickleRoller → Display

#### Message Structure:
```json
{
  "module": "PickleRoller",
  "type": "cycle_log",
  "timestamp_s": 12345,
  "cycle_type": "roller_manual|roller_auto|pump_normal|pump_manual",
  "duration_ms": 5000,
  "trigger": "main_float|manual_button|auto_timer|min_float",
  "timeout": false
}
```

#### Field Descriptions:
- **timestamp_s**: Seconds since module boot
- **cycle_type**: Type of cycle that completed
  - `roller_manual`: Roller activated manually
  - `roller_auto`: Roller activated automatically
  - `pump_normal`: ATO pump normal operation
  - `pump_manual`: ATO pump manual override
- **duration_ms**: Cycle duration in milliseconds
- **trigger**: What triggered the cycle
  - `main_float`: Main roller float switch
  - `manual_button`: Manual button press
  - `auto_timer`: Automatic timer after float release
  - `min_float`: Minimum water level float
- **timeout**: (optional, only for pump cycles) true if timeout alarm occurred

#### Use Cases:
- Track roller activation frequency
- Track ATO topup frequency
- Monitor for timeout alarms
- Log historical operation for diagnostics
- Preserve short-lived events by streaming every transition as it happens (prevents missed datapoints between UI refreshes)

---

### 6. Alarm Event (Module → Display)
**Type**: `alarm`  
**Frequency**: On every alarm transition (assert and clear)  
**Direction**: PickleRoller → Display

#### Message Structure:
```json
{
    "module": "PickleRoller",
    "type": "alarm",
    "alarm": {
        "code": "pump_timeout",
        "severity": "warning",
        "active": true,
        "timestamp_s": 12345,
        "message": "ATO pump exceeded pump_timeout_ms",
        "meta": {
            "timeout_ms": 120000,
            "runtime_ms": 130000
        }
    }
}
```

#### Field Descriptions:
- **alarm.code**: Stable identifier for the alarm condition. Current codes:
    - `pump_timeout`: Pump runtime exceeded the Pump Timeout slider value without float confirmation
    - `roller_empty`: Roller motor was commanded on but the encoder stopped producing pulses (empty/jammed roll)
- **alarm.severity**: `info`, `warning`, or `critical`. Pump timeout uses `warning` by default but can be promoted to `critical` if auto-retry fails.
- **alarm.active**: `true` when the alarm asserts, `false` when it clears. Send a new message each time the boolean changes so the display can remove banners.
- **alarm.timestamp_s**: Seconds since module boot when the transition occurred.
- **alarm.message**: Human-friendly summary the display can surface directly (toast/banner/log entry).
- **alarm.meta** *(optional)*: Structured context for the UI, e.g., pump `runtime_ms`, configured `timeout_ms`, float states, etc.

#### Behavior:
- When firmware sets `ato.timeout_alarm = true`, immediately push an `alarm` message with `active: true` before stopping the pump.
- When the alarm condition clears (float returns to normal or operator resumes auto mode), send the same `alarm.code` payload with `active: false`. This lets the display dismiss indicators without polling.
- Continue to reflect the current alarm bit inside the periodic `status` payload so dashboards that miss the push can recover on the next second tick.
- Record the alarm condition inside the next `cycle_log` entry’s `timeout` field for historical tracking; the `alarm` message is for immediate UX, while `cycle_log` remains the audit trail.
- When the roller motor is running and the encoder has been idle longer than `ROLLER_ENCODER_TIMEOUT_MS` (after a short spin-up grace), the firmware stops the motor, asserts `roller_empty`, and requires a triple-tap reset on the filter button before rollers can run again.

---

## Connection Management

### Initial Connection
1. Module boots and connects to WiFi AP (`ReefNet`)
2. Once WiFi connected, establishes WebSocket connection to `192.168.4.1:80/ws`
3. On successful WebSocket connection, the module immediately sends a full `config` payload with the persisted EEPROM settings followed by the first `status` broadcast
4. Begins periodic status broadcasts every 1 second

### Startup Configuration Sync
1. The display (or any controller UI) listens for the first `config` payload pushed by the module right after the WebSocket handshake and hydrates its sliders/toggles from those values.
2. After the UI is rendered, send a `config_request` once to confirm connectivity; the module replies with the same `config` structure so both sides stay in sync.
3. Every `set_param` command automatically triggers another `config` message, so the display always reflects the module's latest stored settings even after reconnects.

### Reconnection Logic
- **WiFi Reconnection**: If WiFi disconnects, attempts reconnect every 5 seconds
- **WebSocket Reconnection**: WebSocketsClient library handles automatic reconnection every 5 seconds
- Module continues local operation even when disconnected
- Status broadcasts resume automatically upon reconnection
- Display controller (Pi) should enable the ReefNet watchdog described below so hostapd/dnsmasq recover automatically when the USB radio drops after a module disconnects

### ReefNet AP Watchdog (Display Controller)
- Deploy `infrastructure/scripts/reefnet-watchdog.sh` + `infrastructure/systemd/reefnet-watchdog.service` on the Raspberry Pi that runs the AP
- Watchdog polls `wlan1`, hostapd, and dnsmasq every few seconds and reruns `reefnet-startup.sh` if any component disappears
- Keeps the ReefNet SSID online without manual intervention even when modules power-cycle aggressively
- Environment variables (`AP_IFACE`, `AP_ADDR`, `CHECK_INTERVAL`, `STARTUP_SCRIPT`) let you adapt the watchdog to different hardware

### Connection Status Indicators
- Check `WiFi.status()` for WiFi connection state
- Check `wsConnected` global variable for WebSocket connection state
- Serial monitor shows connection/disconnection events

---

## Display Controller Setup (Access Point & WebSocket Server)

This section provides complete implementation for the ESP32 display controller that acts as the WiFi Access Point and WebSocket server.

### Hardware Requirements
- ESP32 or ESP32-S3 (any variant with WiFi)
- No additional hardware needed

### Using the UGREEN CM762 / AIC8800 USB adapter on the display Pi
The CM762 enumerates as a USB flash drive (VID:PID `a69c:5723`) until you install the vendor driver and trigger a mode switch. To keep ReefNet online after swapping adapters:

1. Install dependencies and the AIC8800 driver bundle.
    ```bash
    sudo apt-get install -y usb-modeswitch usb-modeswitch-data build-essential dkms linux-headers-$(uname -r)
    cd /tmp && wget -O UGREEN-CM762.zip "https://download.lulian.cn/2025-drive/UGREEN-CM762-35264_USB%E6%97%A0%E7%BA%BF%E7%BD%91%E5%8D%A1%E9%A9%B1%E5%8A%A8_V1.4.zip"
    unzip -q -o UGREEN-CM762.zip -d CM762
    sudo dpkg -i /tmp/CM762/Linux/linux_driver_package/aic8800d80fdrvpackage.deb
    ```
2. Force the adapter into Wi-Fi mode once (udev eject rules from the `.deb` handle future boots):
    ```bash
    sudo usb_modeswitch -v 0xa69c -p 0x5723 -KQ
    lsusb | grep -i aic   # expect a69c:8d80 initially (it may reappear later as 368b:8d85 once the driver re-enumerates)
    ```
3. Deploy the latest bring-up scripts to `/usr/local/sbin` and install the watchdog unit so the Pi always reloads `aic8800_fdrv`, reapplies `192.168.4.1/24` to `wlan1`, and restarts hostapd/dnsmasq when the radio resets.
4. Verify `ip link show wlan1` reports the new MAC address and that `journalctl -fu reefnet-watchdog` stays clean while you power-cycle a module.

The helper now attempts `aic8800_fdrv` before falling back to the legacy `88XXau` module, so no additional configuration is required beyond these install steps.

### Library Requirements (platformio.ini)
```ini
[env:esp32s3]
platform = espressif32
board = esp32-s3-devkitc-1  ; or your ESP32 board
framework = arduino

lib_deps = 
    me-no-dev/ESP Async WebServer@^1.2.4
    bblanchon/ArduinoJson@^6.21.3
```

**Note**: ESP Async WebServer requires AsyncTCP, which will be installed automatically.

---

### Complete Working Example

```cpp
#include <Arduino.h>
#include <WiFi.h>
#include <AsyncTCP.h>
#include <ESPAsyncWebServer.h>
#include <ArduinoJson.h>

// WiFi Access Point Configuration
const char* AP_SSID = "ReefNet";
const char* AP_PASSWORD = "ReefController2026";

// Server & WebSocket
AsyncWebServer server(80);
AsyncWebSocket ws("/ws");

// Module status storage (updated from WebSocket messages)
struct ModuleStatus {
    String moduleName;
    unsigned long lastUpdate;
    
    // Motor status
    String motorState;
    uint8_t motorSpeed;
    uint32_t motorRuntime;
    String motorMode;
    
    // Float switches
    bool floatMain;
    bool floatMin;
    bool floatMax;
    
    // ATO status
    bool atoPumpRunning;
    bool atoManualMode;
    bool atoPaused;
    bool atoTimeoutAlarm;
    
    // System
    bool chirpEnabled;
    uint32_t uptime;
    
    // Connection
    bool connected;
};

ModuleStatus pickleRoller;

// Function declarations
void onWebSocketEvent(AsyncWebSocket *server, AsyncWebSocketClient *client, 
                       AwsEventType type, void *arg, uint8_t *data, size_t len);
void handleStatusMessage(JsonDocument& doc);
void handleConfigMessage(JsonDocument& doc);
void handleCycleLogMessage(JsonDocument& doc);
void handleAlarmMessage(JsonDocument& doc);
void sendConfigRequest();
void setParameter(const char* param, uint32_t value);
void printModuleStatus();

void setup() {
    Serial.begin(115200);
    delay(1000);
    
    Serial.println("\n\n========================================");
    Serial.println("  PICKLE REEF Display Controller");
    Serial.println("========================================\n");
    
    // Initialize module status
    pickleRoller.moduleName = "PickleRoller";
    pickleRoller.connected = false;
    pickleRoller.lastUpdate = 0;
    
    // Start WiFi Access Point
    Serial.print("Starting WiFi AP: ");
    Serial.println(AP_SSID);
    
    WiFi.mode(WIFI_AP);
    WiFi.softAP(AP_SSID, AP_PASSWORD);
    
    IPAddress IP = WiFi.softAPIP();
    Serial.print("AP IP address: ");
    Serial.println(IP);
    Serial.print("AP MAC: ");
    Serial.println(WiFi.softAPmacAddress());
    
    // Setup WebSocket server
    ws.onEvent(onWebSocketEvent);
    server.addHandler(&ws);
    
    // Start HTTP server
    server.begin();
    Serial.println("WebSocket server started on port 80, path /ws");
    
    Serial.println("\nWaiting for modules to connect...\n");
}

void loop() {
    // Clean up disconnected clients
    ws.cleanupClients();
    
    // Check for module timeout (no messages for 5 seconds)
    if (pickleRoller.connected) {
        if (millis() - pickleRoller.lastUpdate > 5000) {
            Serial.println("Module timeout - no status updates!");
            pickleRoller.connected = false;
        }
    }
    
    // Print status every 10 seconds
    static unsigned long lastPrint = 0;
    if (millis() - lastPrint > 10000) {
        printModuleStatus();
        lastPrint = millis();
    }
    
    delay(10);
}

void onWebSocketEvent(AsyncWebSocket *server, AsyncWebSocketClient *client, 
                       AwsEventType type, void *arg, uint8_t *data, size_t len) {
    switch(type) {
        case WS_EVT_CONNECT:
            Serial.printf("WebSocket client #%u connected from %s\n", 
                          client->id(), client->remoteIP().toString().c_str());
            
            // Request initial config from newly connected module
            delay(500);  // Brief delay to let module settle
            sendConfigRequest();
            break;
            
        case WS_EVT_DISCONNECT:
            Serial.printf("WebSocket client #%u disconnected\n", client->id());
            pickleRoller.connected = false;
            break;
            
        case WS_EVT_DATA: {
            // Handle incoming data
            AwsFrameInfo *info = (AwsFrameInfo*)arg;
            
            if (info->final && info->index == 0 && info->len == len) {
                // Single frame message - parse JSON
                data[len] = 0;  // Null terminate
                
                StaticJsonDocument<512> doc;
                DeserializationError error = deserializeJson(doc, (char*)data);
                
                if (error) {
                    Serial.print("JSON parse error: ");
                    Serial.println(error.c_str());
                    return;
                }
                
                // Check message type
                const char* msgType = doc["type"];
                if (msgType == nullptr) {
                    Serial.println("No message type");
                    return;
                }
                
                // Route message to appropriate handler
                if (strcmp(msgType, "status") == 0) {
                    handleStatusMessage(doc);
                } else if (strcmp(msgType, "config") == 0) {
                    handleConfigMessage(doc);
                } else if (strcmp(msgType, "cycle_log") == 0) {
                    handleCycleLogMessage(doc);
                } else if (strcmp(msgType, "alarm") == 0) {
                    handleAlarmMessage(doc);
                } else {
                    Serial.print("Unknown message type: ");
                    Serial.println(msgType);
                }
            }
            break;
        }
        
        case WS_EVT_ERROR:
            Serial.printf("WebSocket error #%u\n", client->id());
            break;
            
        default:
            break;
    }
}

void handleStatusMessage(JsonDocument& doc) {
    // Update module status
    pickleRoller.connected = true;
    pickleRoller.lastUpdate = millis();
    
    // Extract motor status
    if (doc.containsKey("motor")) {
        JsonObject motor = doc["motor"];
        pickleRoller.motorState = motor["state"].as<String>();
        pickleRoller.motorSpeed = motor["speed"];
        pickleRoller.motorRuntime = motor["runtime_ms"];
        pickleRoller.motorMode = motor["mode"].as<String>();
    }
    
    // Extract float switch status
    if (doc.containsKey("floats")) {
        JsonObject floats = doc["floats"];
        pickleRoller.floatMain = floats["main"];
        pickleRoller.floatMin = floats["min"];
        pickleRoller.floatMax = floats["max"];
    }
    
    // Extract ATO status
    if (doc.containsKey("ato")) {
        JsonObject ato = doc["ato"];
        pickleRoller.atoPumpRunning = ato["pump_running"];
        pickleRoller.atoManualMode = ato["manual_mode"];
        pickleRoller.atoPaused = ato["paused"];
        pickleRoller.atoTimeoutAlarm = ato["timeout_alarm"];
    }
    
    // Extract system status
    if (doc.containsKey("system")) {
        JsonObject system = doc["system"];
        pickleRoller.chirpEnabled = system["chirp_enabled"];
        pickleRoller.uptime = system["uptime_s"];
    }
    
    // Optional: Print status to serial for debugging
    // Serial.println("Status update received");
}

void handleConfigMessage(JsonDocument& doc) {
    Serial.println("\n=== Module Configuration ===");
    
    if (doc.containsKey("motor")) {
        JsonObject motor = doc["motor"];
        Serial.print("Motor Max Speed: ");
        Serial.println(motor["max_speed"].as<uint8_t>());
        Serial.print("Motor Run Time: ");
        Serial.print(motor["run_time_ms"].as<uint32_t>());
        Serial.println(" ms");
        Serial.print("Ramp Up: ");
        Serial.print(motor["ramp_up_ms"].as<uint16_t>());
        Serial.println(" ms");
        Serial.print("Ramp Down: ");
        Serial.print(motor["ramp_down_ms"].as<uint16_t>());
        Serial.println(" ms");
    }
    
    if (doc.containsKey("ato")) {
        JsonObject ato = doc["ato"];
        uint8_t mode = ato["mode"];
        Serial.print("ATO Mode: ");
        if (mode == 0) Serial.println("Auto");
        else if (mode == 1) Serial.println("Manual");
        else if (mode == 2) Serial.println("Paused");
        
        Serial.print("ATO Timeout: ");
        Serial.print(ato["timeout_ms"].as<uint32_t>() / 1000);
        Serial.println(" seconds");
    }
    
    if (doc.containsKey("system")) {
        JsonObject system = doc["system"];
        Serial.print("Chirp Enabled: ");
        Serial.println(system["chirp_enabled"].as<bool>() ? "Yes" : "No");
    }
    
    Serial.println("============================\n");
}

void handleCycleLogMessage(JsonDocument& doc) {
    Serial.println("\n=== Cycle Event ===");
    Serial.print("Timestamp: ");
    Serial.print(doc["timestamp_s"].as<uint32_t>());
    Serial.println(" s");
    
    Serial.print("Type: ");
    Serial.println(doc["cycle_type"].as<String>());
    
    Serial.print("Duration: ");
    Serial.print(doc["duration_ms"].as<uint16_t>());
    Serial.println(" ms");
    
    Serial.print("Trigger: ");
    Serial.println(doc["trigger"].as<String>());
    
    if (doc.containsKey("timeout") && doc["timeout"].as<bool>()) {
        Serial.println("⚠️ TIMEOUT ALARM!");
    }
    
    Serial.println("===================\n");
    
    // TODO: Store cycle data for historical tracking/display
}

void handleAlarmMessage(JsonDocument& doc) {
    if (!doc.containsKey("alarm")) {
        Serial.println("Alarm payload missing 'alarm' object");
        return;
    }

    JsonObject alarm = doc["alarm"];
    const char* code = alarm["code"] | "unknown";
    bool active = alarm["active"] | false;
    const char* severity = alarm["severity"] | "info";
    const char* message = alarm["message"] | "";
    uint32_t timestamp = alarm["timestamp_s"] | 0;

    Serial.println("\n=== Alarm Event ===");
    Serial.print("Code: ");
    Serial.println(code);
    Serial.print("State: ");
    Serial.println(active ? "ACTIVE" : "CLEARED");
    Serial.print("Severity: ");
    Serial.println(severity);
    Serial.print("Timestamp: ");
    Serial.print(timestamp);
    Serial.println(" s");
    Serial.print("Message: ");
    Serial.println(message);

    if (alarm.containsKey("meta")) {
        Serial.println("Meta:");
        serializeJsonPretty(alarm["meta"], Serial);
        Serial.println();
    }

    if (strcmp(code, "pump_timeout") == 0) {
        pickleRoller.atoTimeoutAlarm = active;  // keeps status banner in sync between pushes
    }

    Serial.println("====================\n");
}

void sendConfigRequest() {
    StaticJsonDocument<64> doc;
    doc["type"] = "config_request";
    
    String output;
    serializeJson(doc, output);
    ws.textAll(output);
    
    Serial.println("Config request sent to all modules");
}

void setParameter(const char* param, uint32_t value) {
    StaticJsonDocument<128> doc;
    doc["type"] = "set_param";
    doc["param"] = param;
    doc["value"] = value;
    
    String output;
    serializeJson(doc, output);
    ws.textAll(output);
    
    Serial.print("Parameter set: ");
    Serial.print(param);
    Serial.print(" = ");
    Serial.println(value);
}

void printModuleStatus() {
    if (!pickleRoller.connected) {
        Serial.println("Module: DISCONNECTED");
        return;
    }
    
    Serial.println("\n=== PickleRoller Status ===");
    Serial.print("Uptime: ");
    Serial.print(pickleRoller.uptime);
    Serial.println(" s");
    
    Serial.print("Motor: ");
    Serial.print(pickleRoller.motorState);
    Serial.print(" (");
    Serial.print(pickleRoller.motorSpeed);
    Serial.print(") [");
    Serial.print(pickleRoller.motorMode);
    Serial.println("]");
    
    Serial.print("Floats: Main=");
    Serial.print(pickleRoller.floatMain ? "ON" : "OFF");
    Serial.print(" Min=");
    Serial.print(pickleRoller.floatMin ? "ON" : "OFF");
    Serial.print(" Max=");
    Serial.println(pickleRoller.floatMax ? "ON" : "OFF");
    
    Serial.print("ATO: Pump=");
    Serial.print(pickleRoller.atoPumpRunning ? "ON" : "OFF");
    Serial.print(" Mode=");
    if (pickleRoller.atoManualMode) Serial.print("Manual");
    else if (pickleRoller.atoPaused) Serial.print("Paused");
    else Serial.print("Auto");
    if (pickleRoller.atoTimeoutAlarm) Serial.print(" ⚠️ALARM");
    Serial.println();
    
    Serial.println("===========================\n");
}

// ===================================================
// EXAMPLE CONTROL FUNCTIONS
// ===================================================
// Call these from your UI/button handlers/etc.

void setMotorSpeed(uint8_t speed) {
    setParameter("motor_speed", constrain(speed, 50, 255));
}

void setMotorRuntime(uint16_t milliseconds) {
    setParameter("motor_runtime", constrain(milliseconds, 1000, 30000));
}

void setAtoMode(uint8_t mode) {
    // 0=Auto, 1=Manual, 2=Paused
    setParameter("ato_mode", constrain(mode, 0, 2));
}

void enableChirp(bool enable) {
    setParameter("chirp_enabled", enable ? 1 : 0);
}

// Example: Emergency stop ATO
void emergencyStopATO() {
    Serial.println("EMERGENCY STOP - Pausing ATO");
    setAtoMode(2);  // Set to paused mode
}

// Example: Resume ATO from pause
void resumeATO() {
    Serial.println("Resuming ATO to auto mode");
    setAtoMode(0);  // Set to auto mode
}
```

---

### Quick Start Guide

#### 1. Create New PlatformIO Project
```bash
pio init --board esp32-s3-devkitc-1  # or your ESP32 board
```

#### 2. Update platformio.ini
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

#### 3. Copy Code Above
- Paste the complete example into `src/main.cpp`

#### 4. Upload & Test
```bash
pio run --target upload
pio device monitor
```

#### 5. Connect PickleRoller Module
- The PickleRoller will automatically connect to the AP
- Watch serial monitor for "WebSocket client connected"
- Status updates will appear every 1 second

---

### Customization Guide

#### Change WiFi Credentials
```cpp
const char* AP_SSID = "YourCustomSSID";
const char* AP_PASSWORD = "YourStrongPassword";
```
**Important**: Update the same credentials in PickleRoller's `main.cpp`

#### Add More Modules
The code supports multiple modules. Add more status structs:
```cpp
ModuleStatus pickleRoller;
ModuleStatus dosingPump;
ModuleStatus heaterController;
```

Route messages by checking `doc["module"]`:
```cpp
const char* moduleName = doc["module"];
if (strcmp(moduleName, "PickleRoller") == 0) {
    handleStatusMessage(doc, pickleRoller);
} else if (strcmp(moduleName, "DosingPump") == 0) {
    handleStatusMessage(doc, dosingPump);
}
```

#### Integrate with Display (TFT, OLED, etc.)
Replace `printModuleStatus()` with your display update code:
```cpp
void updateDisplay() {
    // Example for TFT display
    tft.fillScreen(TFT_BLACK);
    tft.setCursor(0, 0);
    
    tft.print("Motor: ");
    tft.println(pickleRoller.motorState);
    
    tft.print("Speed: ");
    tft.println(pickleRoller.motorSpeed);
    
    tft.print("ATO: ");
    tft.println(pickleRoller.atoPumpRunning ? "RUNNING" : "STOPPED");
    
    // Add level indicator
    if (pickleRoller.floatMax) {
        tft.println("Water Level: FULL");
    } else if (pickleRoller.floatMin) {
        tft.println("Water Level: LOW!");
    }
}
```

#### Add Touch/Button Controls
```cpp
void handleButtonPress(int button) {
    switch(button) {
        case BTN_ATO_STOP:
            emergencyStopATO();
            break;
        case BTN_ATO_RESUME:
            resumeATO();
            break;
        case BTN_SPEED_UP:
            setMotorSpeed(pickleRoller.motorSpeed + 10);
            break;
        case BTN_SPEED_DOWN:
            setMotorSpeed(pickleRoller.motorSpeed - 10);
            break;
    }
}
```

#### Store Historical Data
```cpp
#include <vector>

struct CycleRecord {
    uint32_t timestamp;
    String type;
    uint16_t duration;
    String trigger;
};

std::vector<CycleRecord> cycleHistory;

void handleCycleLogMessage(JsonDocument& doc) {
    CycleRecord record;
    record.timestamp = doc["timestamp_s"];
    record.type = doc["cycle_type"].as<String>();
    record.duration = doc["duration_ms"];
    record.trigger = doc["trigger"].as<String>();
    
    cycleHistory.push_back(record);
    
    // Keep only last 100 records
    if (cycleHistory.size() > 100) {
        cycleHistory.erase(cycleHistory.begin());
    }
    
    // Calculate topup frequency
    int topupsLastHour = 0;
    uint32_t oneHourAgo = (millis() / 1000) - 3600;
    for (auto& rec : cycleHistory) {
        if (rec.type == "pump_normal" && rec.timestamp > oneHourAgo) {
            topupsLastHour++;
        }
    }
    
    Serial.print("Topups in last hour: ");
    Serial.println(topupsLastHour);
}
```

---

### Network Configuration

#### Default AP Settings
- **SSID**: ReefNet
- **Password**: ReefController2026
- **IP Address**: 192.168.4.1 (automatic)
- **Subnet**: 255.255.255.0
- **Channel**: Auto (usually channel 1)
- **Max Connections**: 4 (ESP32 default)

#### Custom AP Configuration
```cpp
// More control over AP settings
WiFi.softAPConfig(
    IPAddress(192, 168, 10, 1),  // Custom IP
    IPAddress(192, 168, 10, 1),  // Gateway
    IPAddress(255, 255, 255, 0)  // Subnet mask
);

WiFi.softAP(AP_SSID, AP_PASSWORD, 6, false, 4);
//                                 ^   ^     ^
//                            channel  hidden  max_connections
```

**Note**: If you change the IP, update `WS_SERVER_IP` in PickleRoller code.

#### Check Connected Modules
```cpp
void printConnectedClients() {
    Serial.print("Connected stations: ");
    Serial.println(WiFi.softAPgetStationNum());
    
    wifi_sta_list_t stationList;
    esp_wifi_ap_get_sta_list(&stationList);
    
    for (int i = 0; i < stationList.num; i++) {
        Serial.printf("Station %d: MAC %02X:%02X:%02X:%02X:%02X:%02X\n",
                      i,
                      stationList.sta[i].mac[0],
                      stationList.sta[i].mac[1],
                      stationList.sta[i].mac[2],
                      stationList.sta[i].mac[3],
                      stationList.sta[i].mac[4],
                      stationList.sta[i].mac[5]);
    }
}
```

---

### Troubleshooting Display Side

#### AP Not Broadcasting
- Check serial monitor for "Starting WiFi AP" message
- Verify ESP32 WiFi is working: `WiFi.mode(WIFI_AP)` before `softAP()`
- Try different channel: `WiFi.softAP(ssid, pass, 6)`
- Check if another AP with same name exists

#### Modules Won't Connect
- Verify SSID and password match exactly
- Check WiFi signal strength (modules too far?)
- Try shorter password (some ESP32 have issues with long passwords)
- Check if AP reached max connections (default 4)

#### WebSocket Not Working
- Verify AsyncWebServer library installed correctly
- Check dependencies: AsyncTCP should auto-install
- Try accessing `http://192.168.4.1` from connected device
- Enable verbose WebSocket logging: `ws.setFilter([]{ return true; });`

#### JSON Parse Errors
- Check ArduinoJson version (6.21.x recommended)
- Increase `StaticJsonDocument` size if messages truncated
- Use `serializeJsonPretty(doc, Serial)` to debug incoming messages

#### Memory Issues
- ESP32-S3 has plenty of RAM for WebSocket server
- If using ESP32 classic, monitor free heap: `Serial.println(ESP.getFreeHeap())`
- Reduce `cycleHistory` size if storing many records
- Use `ws.cleanupClients()` regularly to free disconnected client memory

---

### Advanced Features

#### Password-Protected Parameters
```cpp
bool authenticated = false;

void setParameter(const char* param, uint32_t value, bool requireAuth = false) {
    if (requireAuth && !authenticated) {
        Serial.println("Authentication required!");
        return;
    }
    
    // Send parameter change...
}

void setMotorSpeed(uint8_t speed) {
    setParameter("motor_speed", speed, true);  // Requires auth
}
```

#### Watchdog for Module Health
```cpp
void checkModuleHealth() {
    unsigned long offline = millis() - pickleRoller.lastUpdate;
    
    if (offline > 30000) {  // 30 seconds no updates
        Serial.println("⚠️ Module appears offline!");
        // Trigger alarm, send notification, etc.
    }
}
```

#### Broadcast to Multiple Modules
```cpp
void broadcastEmergencyStop() {
    StaticJsonDocument<128> doc;
    doc["type"] = "set_param";
    doc["param"] = "ato_mode";
    doc["value"] = 2;  // Pause all modules
    
    String output;
    serializeJson(doc, output);
    ws.textAll(output);  // Sends to ALL connected modules
    
    Serial.println("EMERGENCY STOP sent to all modules!");
}
```

---

### Testing Without Hardware

You can test the display controller without physical modules by sending test messages:

```cpp
void sendTestStatusMessage() {
    const char* testMessage = R"({
        "module": "PickleRoller",
        "type": "status",
        "motor": {"state": "running", "speed": 200, "runtime_ms": 3500, "mode": "auto"},
        "floats": {"main": true, "min": false, "max": false},
        "ato": {"pump_running": false, "manual_mode": false, "paused": false, "timeout_alarm": false},
        "system": {"chirp_enabled": true, "uptime_s": 12345}
    })";
    
    StaticJsonDocument<512> doc;
    deserializeJson(doc, testMessage);
    handleStatusMessage(doc);
    printModuleStatus();
}

// Call from setup() or loop() for testing
```

---

## Migration from CAN Bus

### Benefits of WiFi/WebSocket vs CAN:
- ✅ **No hardware required** - Built-in WiFi, no CAN transceiver needed
- ✅ **Longer range** - Room-scale coverage vs short CAN bus cables
- ✅ **Easy to add modules** - Just connect to WiFi
- ✅ **JSON messages** - Human-readable, easy to debug
- ✅ **Web-based monitoring** - Can view from any device on network
- ✅ **Lower cost** - No additional hardware costs

### Tradeoffs:
- ⚠️ **Slightly higher latency** - 10-50ms vs <1ms for CAN (still acceptable for this application)
- ⚠️ **Higher power consumption** - WiFi uses more power than CAN
- ⚠️ **Network management** - Need to manage WiFi credentials and reconnection

### What Changed:
- Removed CAN library and transceiver
- Added WiFi and WebSocket libraries
- Converted binary CAN messages to JSON format
- Reduced status broadcast rate from 100ms to 1 second
- Added WiFi reconnection logic
- All functionality remains identical

---

## Troubleshooting

### Module won't connect to WiFi
- Check SSID and password in `WIFI_SSID` and `WIFI_PASSWORD` constants
- Ensure display is broadcasting AP (check display status)
- Check WiFi range - module must be within range of display
- Look for "WiFi connected!" message on serial monitor

### WebSocket won't connect
- Ensure WiFi is connected first
- Check `WS_SERVER_IP` matches display's IP (default 192.168.4.1 for AP mode)
- Check `WS_SERVER_PORT` matches display's WebSocket server port
- Verify display's WebSocket server is running
- Look for "WebSocket connected!" message on serial monitor

### Status messages not appearing on display
- Check WebSocket connection status
- Use display's serial monitor to see if messages are being received
- Verify JSON parsing on display side
- Check for network congestion (too many devices)

### Module disconnects frequently
- Check WiFi signal strength - may be too far from AP
- Check for 2.4GHz interference (microwaves, other WiFi networks)
- Increase `WIFI_RECONNECT_INTERVAL` if too aggressive
- Check display's AP stability

---

## Memory Usage

- **RAM**: 14.2% (46,436 bytes) - Increased from 6.7% due to WiFi/WebSocket libraries
- **Flash**: 70.4% (922,973 bytes) - Increased from 22% due to larger libraries
- Still well within ESP32 capacity
- No impact on real-time operation

---

## Future Enhancements

Possible additions:
- Multiple module support (each with unique MODULE_NAME)
- MQTT broker for more complex messaging
- HTTP REST API for web-based control
- mDNS for automatic server discovery
- OTA (Over-The-Air) firmware updates via WiFi
- Historical data logging to SPIFFS/SD card
- WiFi credentials stored in EEPROM/NVS
