#!/bin/sh
# Builds the broker's password file from the .env passwords on every start, so the
# passwords live in exactly one place (.env) and never in git.
set -eu
: "${MQTT_BACKEND_PASSWORD:?MQTT_BACKEND_PASSWORD is not set}"
: "${MQTT_NODE_PASSWORD:?MQTT_NODE_PASSWORD is not set}"
PASSWD=/mosquitto/passwd
rm -f "$PASSWD"
touch "$PASSWD"
chmod 0700 "$PASSWD"
mosquitto_passwd -b "$PASSWD" backend "$MQTT_BACKEND_PASSWORD"
mosquitto_passwd -b "$PASSWD" node "$MQTT_NODE_PASSWORD"
chown mosquitto:mosquitto "$PASSWD"
exec mosquitto -c /growshed/mosquitto.conf
