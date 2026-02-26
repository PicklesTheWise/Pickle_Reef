# Pickle Reef

Pickle Reef is a Raspberry Pi 5 control surface for tropical aquariums. Wi-Fi modules stream telemetry back to a FastAPI hub, data lands in SQLite via SQLModel, and a Svelte dashboard renders live status/controls. An MQTT bridge keeps edge modules coordinated when a broker is available.

## Features
- FastAPI backend with telemetry + module endpoints, MQTT bridge, a WebSocket server for hardware modules, and SQLite persistence.
- Responsive Svelte dashboard with live metrics, module roster, and graceful demo data when hardware is offline.
- Module config sync captures each module's reported settings so the dashboard controls always mirror reality.
- Roller/pump cycle history is persisted for trend analysis, with REST endpoints powering the new timeline charts.
- Docker Compose stack (API, frontend, Mosquitto) plus VS Code devcontainer + tasks for repeatable setups.
- Basic smoke test via `pytest` so CI/CD can evolve quickly.

## Prerequisites
- Python 3.11+
- Node.js 20+ (Vite 7 uses ESM features)
- npm (bundled with Node)
- Docker + Docker Compose (optional, for the containerized stack)
- MQTT broker (Eclipse Mosquitto works well) — optional during development because the backend degrades gracefully when the broker is unreachable.

## Local Development
```bash
# 1. Python environment + backend deps
python3 -m venv .venv
source .venv/bin/activate
pip install -e backend[dev]

# 2. Frontend deps
cd frontend && npm install && cd ..

# 3. Environment (optional overrides)
cp backend/.env.example backend/.env
```

### Running services
- **Backend** (FastAPI + reload)
	```bash
	cd backend
	../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
	```
- **Frontend** (Svelte dev server)
	```bash
	cd frontend
	npm run dev -- --host 0.0.0.0
	```
- The Vite dev server proxies `/api` to `http://localhost:8000`, so the dashboard immediately hits the FastAPI endpoints.

### Running tests
```bash
pytest backend/tests -q
```

### Docker Compose (optional)
```bash
docker compose up --build
```
The compose file brings up:
- `api`: FastAPI + uvicorn
- `frontend`: Static Svelte build served through NGINX
- `mqtt`: Eclipse Mosquitto (1883 + 9001)

## VS Code Tasks
`.vscode/tasks.json` defines:
- **Pickle Reef Dev Stack** → `docker compose up --build`
- **Pickle Reef Frontend** → `npm run dev -- --host`

## Configuration
All settings are handled via `pydantic-settings`. Common overrides:

| Variable | Description | Default |
| --- | --- | --- |
| `API_HOST` | Bind host for uvicorn | `0.0.0.0` |
| `API_PORT` | Bind port for uvicorn | `80` |
| `DATABASE_URL` | Async SQLAlchemy URL | `sqlite+aiosqlite:///backend/data/pickle_reef.db` |
| `MQTT_HOST` | Hostname for MQTT broker | `mqtt` (container) |
| `MQTT_PORT` | MQTT TCP port | `1883` |
| `MQTT_TOPIC_PREFIX` | Topic namespace | `pickle-reef` |

If the MQTT broker cannot be resolved, the backend logs a warning and keeps running so you can continue development without hardware.

## Project Structure
```
backend/
	app/
		api/          # FastAPI routers & dependencies
		core/         # Settings
		schemas/      # SQLModel tables + DTOs
		services/     # MQTT bridge + future controllers
	tests/          # Pytest suite
frontend/         # Vite + Svelte dashboard
infrastructure/   # Mosquitto config
.devcontainer/    # VS Code remote container config
.vscode/          # VS Code tasks
```

## Next Steps
- Flesh out telemetry ingestion (MQTT consumers, scheduler for retention policies).
- Add auth and remote command channels for actuators.
- Capture module provisioning workflows + UI controls.

## Hardware modules (ReefNet Wi-Fi)

- The Raspberry Pi hosts the (hidden) ReefNet AP on `wlan1` (e.g., USB RTL8812AU dongle) with SSID **ReefNet**, password **ReefController2026**, subnet `192.168.4.0/24`, and IP `192.168.4.1` as described in [system_setup.md](system_setup.md). Disable broadcasting via `ignore_broadcast_ssid=1` in your hostapd config so the network does not appear in nearby Wi-Fi scans.
- Run `hostapd` against `/etc/hostapd/hostapd.conf` (interface `wlan1`, channel 6, WPA2, `ignore_broadcast_ssid=1`) and `dnsmasq` with a DHCP range (`192.168.4.50-150`).

### Access Point stability


#### ReefNet AP watchdog

1. Copy the helper scripts into your PATH and make them executable:
	```bash
	sudo install -m 755 infrastructure/scripts/reefnet-startup.sh /usr/local/sbin/reefnet-startup.sh
	sudo install -m 755 infrastructure/scripts/reefnet-watchdog.sh /usr/local/sbin/reefnet-watchdog.sh
	```
2. Install the systemd unit and reload the daemon:
	```bash
	sudo install -m 644 infrastructure/systemd/reefnet-watchdog.service /etc/systemd/system/reefnet-watchdog.service
	sudo systemctl daemon-reload
	```
3. Enable + start the watchdog (override `AP_IFACE`, `AP_ADDR`, or `CHECK_INTERVAL` via a drop-in if needed):
	```bash
	sudo systemctl enable --now reefnet-watchdog.service
	```
The watchdog polls `wlan1` every few seconds and re-runs the startup sequence whenever the interface disappears, loses its static address, or either hostapd/dnsmasq exit unexpectedly. This keeps the hidden ReefNet SSID online even if the RTL8812AU driver collapses the radio after a module powers off.

#### UGREEN CM762 / AIC8800 Wi-Fi 6 dongle

1. Install prerequisites and the vendor driver package (verified on Raspberry Pi OS / Debian Bookworm):
	```bash
	sudo apt-get install -y usb-modeswitch usb-modeswitch-data build-essential dkms linux-headers-$(uname -r)
	cd /tmp
	wget -O UGREEN-CM762.zip "https://download.lulian.cn/2025-drive/UGREEN-CM762-35264_USB%E6%97%A0%E7%BA%BF%E7%BD%91%E5%8D%A1%E9%A9%B1%E5%8A%A8_V1.4.zip"
	unzip -q -o UGREEN-CM762.zip -d CM762
	sudo dpkg -i /tmp/CM762/Linux/linux_driver_package/aic8800d80fdrvpackage.deb
	```
2. Flip the adapter out of “flash drive” mode so the Wi-Fi interface appears (a udev rule from the `.deb` takes care of this on future boots):
	```bash
	sudo usb_modeswitch -v 0xa69c -p 0x5723 -KQ   # lsusb should now show a69c:8d80 (or 368b:8d85 once the driver loads)
	```
3. Verify the kernel module is loaded and the AP NIC exists:
	```bash
	lsmod | grep aic8800
	ip link show wlan1
	```
4. Deploy the latest bring-up scripts and watchdog, then enable the service (the helper now prefers `aic8800_fdrv` automatically and falls back to `88XXau` if needed):
	```bash
	sudo install -m 755 infrastructure/scripts/reefnet-startup.sh /usr/local/sbin/reefnet-startup.sh
	sudo install -m 755 infrastructure/scripts/reefnet-watchdog.sh /usr/local/sbin/reefnet-watchdog.sh
	sudo install -m 644 infrastructure/systemd/reefnet-watchdog.service /etc/systemd/system/reefnet-watchdog.service
	sudo systemctl daemon-reload
	sudo systemctl enable --now reefnet-watchdog.service
	```
5. Confirm the AP survives module power cycles by watching the logs while you unplug/replug hardware:
	```bash
	sudo journalctl -fu reefnet-watchdog.service
	```
	You should see the helper reload `aic8800_fdrv`, reapply `192.168.4.1/24` to `wlan1`, and leave hostapd/dnsmasq running without manual intervention.
