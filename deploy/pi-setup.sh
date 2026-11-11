#!/usr/bin/env bash
# One-time setup for the Raspberry Pi hub. Safe to run again.
#
# Before running: flash 64-bit Raspberry Pi OS Lite to the USB SSD with Raspberry Pi
# Imager (set hostname, user, WiFi/SSH there), boot the Pi from the SSD, clone this
# repo, then:   sudo deploy/pi-setup.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo deploy/pi-setup.sh" >&2
  exit 1
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="${SUDO_USER:-$(logname)}"

echo "==> Updating the system"
apt-get update
apt-get -y upgrade
apt-get -y install git curl openssl

echo "==> Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
usermod -aG docker "$RUN_USER"

echo "==> Tailscale (remote access without opening router ports)"
if ! command -v tailscale >/dev/null; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi

echo "==> Hardware watchdog (reboots the Pi if it locks up)"
CONFIG_TXT=/boot/firmware/config.txt
if [[ -f $CONFIG_TXT ]] && ! grep -q '^dtparam=watchdog=on' "$CONFIG_TXT"; then
  echo 'dtparam=watchdog=on' >>"$CONFIG_TXT"
fi
mkdir -p /etc/systemd/system.conf.d
cat >/etc/systemd/system.conf.d/growshed-watchdog.conf <<'CONF'
[Manager]
RuntimeWatchdogSec=15
RebootWatchdogSec=5min
CONF

echo "==> Limit log size (protects the SSD)"
mkdir -p /etc/systemd/journald.conf.d
cat >/etc/systemd/journald.conf.d/growshed.conf <<'CONF'
[Journal]
SystemMaxUse=200M
CONF
mkdir -p /etc/docker
if [[ ! -f /etc/docker/daemon.json ]]; then
  cat >/etc/docker/daemon.json <<'CONF'
{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }
CONF
  systemctl restart docker
fi

echo "==> Passwords (.env)"
if [[ ! -f "$REPO_DIR/.env" ]]; then
  cat >"$REPO_DIR/.env" <<ENV
MQTT_BACKEND_PASSWORD=$(openssl rand -hex 16)
MQTT_NODE_PASSWORD=$(openssl rand -hex 16)
GROWSHED_NTFY_URL=https://ntfy.sh/growshed-$(openssl rand -hex 12)
GROWSHED_NTFY_TOKEN=
GROWSHED_HEALTHCHECK_URL=
GROWSHED_PORT=8000
ENV
  chown "$RUN_USER": "$REPO_DIR/.env"
  chmod 600 "$REPO_DIR/.env"
  echo "    created $REPO_DIR/.env"
else
  echo "    $REPO_DIR/.env already exists, left unchanged"
fi

cat <<DONE

Setup finished. Next steps:
  1. sudo reboot                       (activates the watchdog and docker group)
  2. sudo tailscale up                 (log in once to enable remote access)
  3. cd $REPO_DIR && docker compose up -d --build
  4. Open http://$(hostname).local:8000 on your phone or tablet.
  5. Phone alerts: install the ntfy app and subscribe to the topic at the end of
     GROWSHED_NTFY_URL in $REPO_DIR/.env, then use the test button on the Alerts page.
DONE
