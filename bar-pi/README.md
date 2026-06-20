# bar-pi kiosk host files

These files live on the **bar-pi** Raspberry Pi (the dedicated touchscreen
running the kiosk), *not* in the Flask app container on gimli. The kiosk page
is served remotely from `https://sugar.scotthoge.com/kiosk`, but its
JavaScript runs on bar-pi — so actions that affect the Pi itself (reboot,
exit the browser) need a small local helper here.

| File | Installs to | Purpose |
|------|-------------|---------|
| `kiosk-agent.py` | `~/.local/bin/kiosk-agent.py` | localhost-only HTTP helper (`/ping`, `/reboot`, `/exit`) |
| `kiosk-agent.service` | `~/.config/systemd/user/kiosk-agent.service` | runs the agent under the user session |
| `autostart` | `~/.config/labwc/autostart` | Chromium kiosk restart loop + sentinel exit + starts the agent |

## How it works

The kiosk's **Maintenance** tab calls the agent over `http://localhost:8765`:

- **Refresh** — pure client-side `location.reload()`, no agent needed.
- **Reboot** — `POST /reboot` → `sudo systemctl reboot` (relies on the host's
  existing passwordless sudo).
- **Exit** — `POST /exit` → drops `$XDG_RUNTIME_DIR/kiosk-stop` and kills the
  kiosk Chromium. The `autostart` loop sees the sentinel and stops relaunching.
  The sentinel is on tmpfs, so a **reboot or power-cycle clears it** and the
  kiosk comes back automatically.

The agent binds to `127.0.0.1` only and rejects browser requests whose `Origin`
isn't the kiosk site. The https→localhost fetch works because `localhost` is a
"potentially trustworthy" origin (no mixed-content block) and Chromium 144 did
not require a Private/Local Network Access preflight in testing; the agent still
sends the PNA headers defensively.

> **Note:** after **Exit** there is no on-screen way back (touch-only, no
> on-screen keyboard) — recover via SSH or a power-cycle.

## Install / update

From a machine that can reach bar-pi:

```sh
scp bar-pi/kiosk-agent.py        bar-pi.home:~/.local/bin/kiosk-agent.py
scp bar-pi/kiosk-agent.service   bar-pi.home:~/.config/systemd/user/kiosk-agent.service
scp bar-pi/autostart             bar-pi.home:~/.config/labwc/autostart

ssh bar-pi.home '
  chmod +x ~/.local/bin/kiosk-agent.py ~/.config/labwc/autostart
  systemctl --user daemon-reload
  systemctl --user enable --now kiosk-agent.service
  curl -s http://127.0.0.1:8765/ping
'
```

The `autostart` change takes effect on next reboot/login.
