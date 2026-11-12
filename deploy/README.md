# Deploying on the Raspberry Pi

> `pi-setup.sh` has been syntax-checked but **not yet run on a real Pi**. Read its output the
> first time and report anything that fails.

1. **Flash the SSD.** With Raspberry Pi Imager, write *Raspberry Pi OS Lite (64-bit)* to the
   USB SSD. In the imager's settings set a hostname (e.g. `growshed`), your user, WiFi if not
   using Ethernet, and enable SSH. A Pi 4 boots from USB with no SD card inserted.
2. **Get the code** (on the Pi):

   ```bash
   sudo apt-get install -y git && git clone https://github.com/PapaBear1981/Growshed.git && cd Growshed
   ```

3. **Run the setup script.** It installs Docker and Tailscale, turns on the hardware watchdog,
   caps log sizes, and creates `.env` with random MQTT passwords.

   ```bash
   sudo deploy/pi-setup.sh
   ```

4. **Reboot, then start the hub:**

   ```bash
   docker compose up -d --build
   ```

5. Open `http://growshed.local:8000` from a phone or the tablet on the same network. For
   access away from home, run `sudo tailscale up` once and install Tailscale on your phones.

## Phone notifications

Alerts are sent through [ntfy](https://ntfy.sh), a free push-notification service.

1. Install the **ntfy** app on both phones (Android or iPhone).
2. Look in `.env` for `GROWSHED_NTFY_URL`. The setup script generated a random topic, e.g.
   `https://ntfy.sh/growshed-3f9a…`. In the app, subscribe to the last part (`growshed-3f9a…`).
3. Open the **Alerts** page in Growshed and press **Send a test notification**.
4. In the app's settings for that topic, allow it to break through Do Not Disturb, so a leak
   at 3 a.m. wakes you.

Alert text passes through ntfy.sh's servers. It contains things like "Leak detected · Tent 1",
never passwords. Anyone who learns the topic name could read it, which is why it is random.

**If the Pi itself dies, it can't send alerts.** For that, create a free check at
healthchecks.io (period 5 minutes, grace 10), put its ping URL in `GROWSHED_HEALTHCHECK_URL`,
and restart with `docker compose up -d`. healthchecks.io then tells you when the hub goes silent.

## Backups and restoring

The hub saves a snapshot of its database and `config.yaml` every night into `data/backups/`
(the last 14 are kept). Those live on the same SSD, so they protect against mistakes and
corruption, not against the SSD dying.

- **Keep a copy elsewhere:** on the Settings page, press **Download full backup** now and then.
  It is one zip with the database, `config.yaml` and all journal photos.
- **Or point the nightly snapshots at another disk** (a USB stick or a network share mounted on
  the Pi): set `GROWSHED_BACKUP_DIR` in `.env` to a folder that is mounted into the backend
  container, and add that folder to the `volumes:` of the `backend` service.

To restore: stop the hub (`docker compose down`), put the saved `growshed.db` at
`data/growshed.db` (remove any `growshed.db-wal` and `growshed.db-shm` files next to it), put
photos back under `data/photos/`, and start it again (`docker compose up -d`).

## Updating

```bash
git pull && docker compose up -d --build
```

## Useful commands

| What | Command |
|---|---|
| See what's running | `docker compose ps` |
| Backend logs | `docker compose logs -f backend` |
| Broker logs | `docker compose logs -f mosquitto` |
| ESPHome dashboard (flashing nodes, Phase 1+) | `docker compose --profile esphome up -d`, then port 6052 |

The database lives in `data/` and the MQTT passwords in `.env`. Neither is in git: back them up.
