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
