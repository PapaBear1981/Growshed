# Node firmware (ESPHome)

Empty until **Phase 1**. It will hold one YAML file per node (`tent1.yaml`, `tent2.yaml`,
`tent3.yaml`, `water.yaml`, later `dosing.yaml`) sharing packages in `common/`.

Secrets (WiFi and the MQTT `node` password from `.env`) go in `firmware/secrets.yaml`, which
is gitignored.
