# Sugar Rim

Alternate web interface for [Bar Assistant](https://github.com/bar-assistant/bar-assistant), optimized for touch screens and the Raspberry Pi.

## Features

- Full-screen cocktail grid — dynamic layout fills your display
- Shelf availability indicators per ingredient on every recipe
- Favorites, shopping list, and bar shelf management
- Mobile-friendly with infinite scroll

---

## Docker (recommended)

### Quick start

```bash
docker run -d --name sugar-rim -p 5000:5000 -v sugar-rim-config:/config scotthoge/sugar-rim:latest
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
    volumes:
      - sugar-rim-config:/config

volumes:
  sugar-rim-config:
```

```bash
docker compose up -d
```

Open `http://<host>:5000` in a browser, then go to **Settings** to enter your Bar Assistant URL and API token.

Settings are written to a named Docker volume (`sugar-rim-config`) and survive container restarts and updates.

### Pre-seed configuration (optional)

Create a `.env` file next to `docker-compose.yml` before first run:

```bash
BA_API_URL=http://bar-assistant:8000/api
BA_API_TOKEN=your-token-here
BA_BAR_ID=1
SECRET_KEY=change-me-to-a-random-string
```

Then run `docker compose up -d`. The values are picked up by `docker-compose.yml` and written into the config volume on first start.

### Running alongside Bar Assistant

If Bar Assistant is already running via Docker Compose, add Sugar Rim to the same network so it can reach the API by container name:

```yaml
# In your existing bar-assistant docker-compose.yml, add:
services:
  sugar-rim:
    image: scotthoge/sugar-rim:latest
    container_name: sugar-rim
    restart: unless-stopped
    ports:
      - "5000:5000"
    volumes:
      - sugar-rim-config:/config
    networks:
      - bar-assistant-net   # same network as bar-assistant service

volumes:
  sugar-rim-config:
```

Then set `BA_API_URL=http://bar-assistant:8000/api` in Settings (using the container name, not `localhost`).

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

Open `http://localhost:5000` and configure in **Settings**.

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

## Configuration

All settings are stored in `.env` and can be changed via the **Settings** tab in the UI without restarting.

| Variable | Description |
|---|---|
| `BA_API_URL` | Bar Assistant API base URL, e.g. `http://localhost:8000/api` |
| `BA_API_TOKEN` | Personal access token from Bar Assistant → Profile → Tokens |
| `BA_BAR_ID` | Numeric ID of the bar to use (set via Settings → Active Bar) |
| `SECRET_KEY` | Flask session key — auto-generated on first run |
