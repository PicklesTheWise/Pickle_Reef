#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  exec sudo -E "$0" "$@"
fi

AP_IFACE=${AP_IFACE:-wlan1}
AP_ADDR=${AP_ADDR:-192.168.4.1}
CHECK_INTERVAL=${CHECK_INTERVAL:-5}
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
STARTUP_SCRIPT=${STARTUP_SCRIPT:-"${SCRIPT_DIR}/reefnet-startup.sh"}
LOG_PREFIX="[reefnet-watchdog]"

log(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }

if [[ ! -x "$STARTUP_SCRIPT" ]]; then
  log "startup script $STARTUP_SCRIPT not found or not executable"
  exit 1
fi

log "watchdog online (iface=$AP_IFACE, interval=${CHECK_INTERVAL}s)"

check_health(){
  local unhealthy=0

  if ! ip link show "$AP_IFACE" &>/dev/null; then
    log "interface $AP_IFACE missing"
    unhealthy=1
  else
    local link_line flags
    link_line=$(ip -o link show "$AP_IFACE")
    flags=$(awk -F'[<>]' 'NR==1{print $2}' <<<"$link_line")
    if [[ $flags != *UP* ]]; then
      log "interface $AP_IFACE admin-down (flags=$flags)"
      unhealthy=1
    fi

    if [[ -n "${AP_ADDR}" ]] && ! ip -4 addr show "$AP_IFACE" | grep -q "$AP_ADDR"; then
      log "missing IPv4 ${AP_ADDR} on $AP_IFACE"
      unhealthy=1
    fi
  fi

  for svc in hostapd dnsmasq; do
    if ! systemctl is-active --quiet "$svc"; then
      log "$svc inactive"
      unhealthy=1
    fi
  done

  return $unhealthy
}

while true; do
  if ! check_health; then
    log "AP unhealthy; rerunning startup sequence"
    if "$STARTUP_SCRIPT"; then
      log "startup sequence completed"
    else
      local rc=$?
      log "startup script failed with status $rc"
    fi
  fi
  sleep "$CHECK_INTERVAL"
done
