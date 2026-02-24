#!/usr/bin/env bash
set -euo pipefail

log(){ printf '[reefnet] %s\n' "$*"; }

need_cmd(){
  if ! command -v "$1" &>/dev/null; then
    log "missing required command: $1"
    exit 1
  fi
}

DEFAULT_REPO_ROOT="/home/fluff/PickleReef"

if [[ -z ${PROJECT_ROOT:-} ]]; then
  CANDIDATE_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
  if [[ -f "$CANDIDATE_ROOT/docker-compose.yml" ]]; then
    PROJECT_ROOT=$CANDIDATE_ROOT
  else
    PROJECT_ROOT=$DEFAULT_REPO_ROOT
  fi
fi

FRONTEND_DIR=${FRONTEND_DIR:-"$PROJECT_ROOT/frontend"}
DOCKER_DIR=${DOCKER_DIR:-$PROJECT_ROOT}
COMPOSE_FILE=${COMPOSE_FILE:-"$DOCKER_DIR/docker-compose.yml"}

export PROJECT_ROOT FRONTEND_DIR DOCKER_DIR COMPOSE_FILE

cd "$PROJECT_ROOT"

build_frontend(){
  if [[ ${SKIP_FRONTEND_BUILD:-0} -eq 1 ]]; then
    log "SKIP_FRONTEND_BUILD=1, skipping frontend build"
    return
  fi

  if [[ ! -d "$FRONTEND_DIR" ]]; then
    log "frontend directory $FRONTEND_DIR missing; skipping build"
    return
  fi

  if ! command -v npm &>/dev/null; then
    log "npm not available; skipping frontend build"
    return
  fi

  log "building frontend assets"
  if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
    log "installing frontend dependencies"
    (cd "$FRONTEND_DIR" && npm install)
  fi
  (cd "$FRONTEND_DIR" && npm run build)
}

sync_rtc(){
  if [[ ${SKIP_RTC_SYNC:-0} -eq 1 ]]; then
    log "SKIP_RTC_SYNC=1, skipping RTC sync"
    return
  fi

  local rtc_device=${HWCLOCK_DEVICE:-/dev/rtc0}
  if [[ ! -e "$rtc_device" ]]; then
    log "RTC device $rtc_device not present; skipping clock sync"
    return
  fi

  if ! command -v hwclock &>/dev/null; then
    log "hwclock utility missing; cannot sync RTC"
    return
  fi

  if hwclock --rtc "$rtc_device" --hctosys; then
    log "system clock primed from RTC ($rtc_device)"
  else
    log "failed to sync system clock from $rtc_device"
  fi
}

enable_rtc_charging(){
  if [[ ${ENABLE_RTC_CHARGING:-1} -ne 1 ]]; then
    log "ENABLE_RTC_CHARGING=0, skipping RTC charger setup"
    return
  fi

  local sysfs_base=${RTC_SYSFS_PATH:-/sys/class/rtc/rtc0}
  local ctrl_file="$sysfs_base/charging_voltage"
  if [[ ! -w $ctrl_file ]]; then
    chmod u+w "$ctrl_file" 2>/dev/null || true
  fi
  if [[ ! -w $ctrl_file ]]; then
    log "RTC charging voltage control $ctrl_file unavailable"
    return
  fi

  local target=${RTC_CHARGE_VOLTAGE_UV:-3000000}
  local min_file="$sysfs_base/charging_voltage_min"
  local max_file="$sysfs_base/charging_voltage_max"
  local min=$(cat "$min_file" 2>/dev/null || echo 0)
  local max=$(cat "$max_file" 2>/dev/null || echo 0)
  if (( target < min || (max > 0 && target > max) )); then
    log "RTC charge target ${target}uV outside ${min}-${max}uV window"
    return
  fi

  local current=$(cat "$ctrl_file" 2>/dev/null || echo 0)
  if [[ $current == "$target" ]]; then
    log "RTC charger already set to ${target}uV"
    return
  fi

  if printf '%s' "$target" >"$ctrl_file"; then
    log "RTC charger voltage set to ${target}uV"
  else
    log "failed to set RTC charger voltage"
  fi
}

# Ensure we are root (sudo preserves env vars like WAN_IFACE if exported)
if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  build_frontend
  export FRONTEND_BUILD_DONE=1
  exec sudo -E "$0" "$@"
fi

if [[ ${FRONTEND_BUILD_DONE:-0} -ne 1 ]]; then
  build_frontend
fi

need_cmd ip
need_cmd iptables
need_cmd modprobe
need_cmd systemctl
need_cmd docker

sync_rtc
enable_rtc_charging

WAN_IFACE=${WAN_IFACE:-eth0}
AP_IFACE=${AP_IFACE:-wlan1}
AP_ADDR=${AP_ADDR:-192.168.4.1/24}
AP_NET=${AP_NET:-192.168.4.0/24}
# Try modern CM762 driver first, fall back to legacy RTL8812AU if present
AP_DRIVER_MODULES=${AP_DRIVER_MODULES:-"aic8800_fdrv 88XXau"}

wait_for_iface(){
  local iface=$1 timeout=${2:-15} waited=0
  while ! ip link show "$iface" &>/dev/null; do
    if (( waited >= timeout )); then
      log "interface $iface did not appear within ${timeout}s"
      exit 1
    fi
    sleep 1
    ((waited++))
  done
}

load_ap_driver(){
  local loaded=0
  for module in $AP_DRIVER_MODULES; do
    [[ -z $module ]] && continue
    if modprobe "$module" 2>/dev/null; then
      log "loaded driver module $module"
      loaded=1
      break
    else
      log "driver module $module not available"
    fi
  done

  if (( ! loaded )); then
    log "warning: no AP driver modules loaded"
  fi
}

load_ap_driver

log "waiting for ${AP_IFACE}"
wait_for_iface "$AP_IFACE"

log "setting static address ${AP_ADDR} on ${AP_IFACE}"
ip link set "$AP_IFACE" down || true
ip addr flush dev "$AP_IFACE" || true
ip addr add "$AP_ADDR" dev "$AP_IFACE"
ip link set "$AP_IFACE" up

log "enabling IPv4 forwarding"
sysctl -w net.ipv4.ip_forward=1 >/dev/null

ensure_rule(){
  if ! iptables -C "$@" 2>/dev/null; then
    iptables -A "$@"
  fi
}

restart_service(){
  local svc=$1
  if ! systemctl list-unit-files "$svc" &>/dev/null; then
    log "skipping $svc (unit not installed)"
    return
  fi

  if systemctl is-active --quiet "$svc"; then
    log "restarting $svc"
    systemctl restart "$svc"
  else
    log "starting $svc"
    systemctl start "$svc"
  fi
}

detect_compose(){
  if docker compose version &>/dev/null; then
    COMPOSE_BIN=(docker compose)
    return 0
  fi

  if command -v docker-compose &>/dev/null; then
    COMPOSE_BIN=(docker-compose)
    return 0
  fi

  log "docker compose not installed"
  return 1
}

ensure_compose_file(){
  if [[ ! -f "$COMPOSE_FILE" ]]; then
    log "docker compose file $COMPOSE_FILE not found"
    exit 1
  fi
}

start_container_stack(){
  if ! detect_compose; then
    log "docker compose is required but missing"
    exit 1
  fi

  ensure_compose_file
  pushd "$DOCKER_DIR" >/dev/null

  log "compose working dir: $(pwd)"
  log "compose file: ${COMPOSE_FILE}"
  ls -l docker-compose.* || true

  log "refreshing container images"
  if ! "${COMPOSE_BIN[@]}" pull; then
    log "Docker image pull skipped (offline?)"
  fi

  log "building and starting containers"
  "${COMPOSE_BIN[@]}" up --build -d

  log "Docker services"
  "${COMPOSE_BIN[@]}" ps

  popd >/dev/null
}

log "ensuring NAT + forwarding rules"
iptables -t nat -C POSTROUTING -s "$AP_NET" -o "$WAN_IFACE" -j MASQUERADE 2>/dev/null || \
  iptables -t nat -A POSTROUTING -s "$AP_NET" -o "$WAN_IFACE" -j MASQUERADE
ensure_rule FORWARD -i "$WAN_IFACE" -o "$AP_IFACE" -m state --state RELATED,ESTABLISHED -j ACCEPT
ensure_rule FORWARD -i "$AP_IFACE" -o "$WAN_IFACE" -j ACCEPT

ensure_service(){
  local svc=$1
  if systemctl is-active --quiet "$svc"; then
    log "$svc already active"
  else
    log "starting $svc"
    systemctl start "$svc"
  fi
}

restart_service hostapd.service
restart_service dnsmasq.service

log "starting Docker application stack"
start_container_stack

log "reefnet startup sequence complete"
