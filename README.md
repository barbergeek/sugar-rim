# Sugar Rim

Alternate web interface for [Bar Assistant](https://github.com/bar-assistant/bar-assistant), optimized for touch screens and the Raspberry Pi.

Sugar Rim is a small Flask app that proxies the Bar Assistant API (your token/session never reaches the browser) and serves two front ends from the same backend:

- **Phone / desktop UI** at `/` — full cocktail grid with infinite scroll, search, and management.
- **Kiosk UI** at `/kiosk` — a touch-first, full-screen layout designed for a wall- or bar-mounted Raspberry Pi display.

## Features

- Full-screen cocktail grid — dynamic layout fills your display
- Shelf availability per ingredient; filter to cocktails you can make
- Favorites, shopping list, and bar-shelf management
- Mobile-friendly with infinite scroll
- **Kiosk mode** (`/kiosk`): touch-first filtering, featured pick, drag-to-scroll, hidden cursor — see [Kiosk mode](#kiosk-mode)

---

## Docker (recommended)

### Quick start

```bash
docker run -d --name sugar-rim -p 5000:5000 \
  -e SECRET_KEY=please-change-me \
  -v sugar-rim-config:/config \
  scotthoge/sugar-rim:latest
```

Or with Docker Compose — create a `docker-compose.yml`:

```yaml
services:
  sugar-rim:
    image: scotthoge/sugar-rim:latest
    container_name: sugar-rim
    restart: unless-stopped
    ports:
      - "5000:5000"
    environment:
      # Set this to a fixed random string so logins survive restarts/updates.
      # If omitted, a key is generated on first start and LOST when the
      # container is recreated (e.g. on image update), logging everyone out.
      SECRET_KEY: please-change-me
    volumes:
      - sugar-rim-config:/config

volumes:
  sugar-rim-config:
```

```bash
docker compose up -d
```

Open `http://<host>:5000`, go to **Settings** to enter your Bar Assistant URL, then **log in** with your Bar Assistant account. Settings are written to the `sugar-rim-config` volume and survive restarts.

> **Set `SECRET_KEY` explicitly.** Authentication is session-based (a signed cookie). The signing key is auto-generated on first start if unset, but that generated key lives in the container's writable layer and is regenerated whenever the container is recreated — which invalidates every existing session and logs users out. Passing `SECRET_KEY` as an environment variable keeps logins stable across restarts and image updates.

### Running alongside Bar Assistant

If Bar Assistant runs via Docker Compose, put Sugar Rim on the same network so it can reach the API by container name:

```yaml
services:
  sugar-rim:
    image: scotthoge/sugar-rim:latest
    container_name: sugar-rim
    restart: unless-stopped
    ports:
      - "5000:5000"
    environment:
      SECRET_KEY: please-change-me
    volumes:
      - sugar-rim-config:/config
    networks:
      - bar-assistant-net   # same network as the bar-assistant service

volumes:
  sugar-rim-config:
```

Then set `BA_API_URL=http://bar-assistant:8080/api` in Settings (container name, not `localhost`).

### Updating

```bash
docker compose pull
docker compose up -d
```

---

## Manual install

Requires Python 3.10+.

```bash
git clone https://github.com/barbergeek/sugar-rim.git
cd sugar-rim
./run.sh          # creates venv, installs deps, starts on :5000
```

Open `http://localhost:5000`, set the Bar Assistant URL in **Settings**, and log in.

### Running as a systemd service (Raspberry Pi)

```ini
# /etc/systemd/system/sugar-rim.service
[Unit]
Description=Sugar Rim
After=network.target

[Service]
WorkingDirectory=/home/pi/sugar-rim
ExecStart=/home/pi/sugar-rim/.venv/bin/gunicorn --bind 0.0.0.0:5000 --workers 2 app:app
Restart=on-failure
User=pi

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now sugar-rim
```

---

## Kiosk mode

The kiosk UI lives at `/kiosk` and is a separate, touch-first layout (the phone UI at `/` is unchanged). It is built for a dedicated full-screen display and minimizes keyboard use:

- **Tap-to-filter pickers** — *Ingredients* and *Tags* buttons open near-full-width popups. Tap items to select (highlighted, no checkboxes); selected items pin to a bar at the top and drop out of the list below. Tap a chip to remove it.
- **Featured pick + results** — a random match is featured up top, with *all* matching cocktails listed below (the list pages through every match, not just the first page).
- **Shelf-only toggle** — on by default (and remembered): shows only ingredients on your bar shelf and cocktails you can actually make. Turn it off to browse everything.
- **Touch niceties** — drag-to-scroll anywhere (including over images), and the mouse cursor is hidden **on touchscreens only** (detected via `navigator.maxTouchPoints`, since the Pi reports a "fine"/"hover" pointer to CSS). Opening `/kiosk` in a desktop browser keeps its normal cursor.

The kiosk shares the backend, login, and Settings with the main UI.

### Maintenance tab

The kiosk has a **Maintenance** tab for managing the display itself, touch-only:

- **Refresh** — reload the kiosk page (client-side; always available).
- **Exit** — quit the kiosk browser and drop to an on-screen keyboard + terminal for hands-on maintenance.
- **Reboot** — restart the Raspberry Pi.
- **Shut down** — power off the Raspberry Pi.

Each destructive action is a two-tap confirm. It also shows **system info** — Sugar Rim and Bar Assistant API versions, and host facts (model, OS, kernel, uptime, CPU temp, memory, disk, Wi-Fi/IP) and client facts (browser, viewport, screen).

Reboot/Exit/Shut down act on the Pi, which the (remotely hosted) backend can't reach, so a tiny localhost-only helper runs on the Pi to perform them. Exit/Reboot/Shut down only appear when that helper is running. See [`bar-pi/`](bar-pi/) for the helper, its install steps, and the boot-time Wi-Fi diagnostics.

### Raspberry Pi touchscreen setup

Launch Chromium in kiosk mode pointing at the `/kiosk` route. On a Wayland session (e.g. labwc), an autostart entry such as:

```sh
chromium --kiosk \
  --force-device-scale-factor=1.5 \
  --disable-session-crashed-bubble \
  --disable-infobars --noerrdialogs --no-first-run \
  http://<host>:5000/kiosk
```

- `--kiosk` gives a locked, full-screen window.
- `--force-device-scale-factor` controls magnification — raise it on dense/high-DPI panels, lower it to fit more on screen. This is the single knob for the kiosk's physical size.
- A surrounding restart loop and `--disable-session-crashed-bubble` help the display recover cleanly after power cycles.

---

## Configuration

The Bar Assistant URL and active bar are set from the **Settings** tab in the UI (written to `.env` / the config volume, no restart needed). Authentication is done by **logging in** with your Bar Assistant account.

| Variable | Description |
|---|---|
| `BA_API_URL` | Bar Assistant API base URL, e.g. `http://localhost:8080/api` |
| `BA_BAR_ID` | Numeric ID of the active bar (set via Settings → Active Bar) |
| `SECRET_KEY` | Flask session signing key. **Set this explicitly** (especially in Docker) so logins persist across restarts and updates; auto-generated if blank. |
| `BA_API_TOKEN` | Optional. A personal access token can be stored here, but normal use is to log in through the UI. |

---

## Development

```bash
ruff check . && ruff format .   # Python lint/format
npm run format                  # Prettier for JS/CSS
```

- `app.py` — Flask backend; proxies all Bar Assistant API calls.
- `templates/index.html` — phone/desktop SPA shell.
- `templates/kiosk.html` — kiosk SPA shell (`window.KIOSK`, `.kiosk-mode`).
- `static/js/app.js` — shared frontend logic (vanilla JS, no build step).
- `static/css/style.css` — all styles; the `.kiosk-mode` block scopes kiosk overrides.
