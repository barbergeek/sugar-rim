# bar-pi kiosk host files

These files live on the **bar-pi** Raspberry Pi (the dedicated touchscreen
running the kiosk), *not* in the Flask app container on gimli. The kiosk page
is served remotely from `https://sugar.scotthoge.com/kiosk`, but its
JavaScript runs on bar-pi — so actions that affect the Pi itself (reboot,
exit the browser) need a small local helper here.

| File | Installs to | Purpose |
|------|-------------|---------|
| `kiosk-agent.py` | `~/.local/bin/kiosk-agent.py` | localhost-only HTTP helper (`/ping`, `/info`, `/reboot`, `/shutdown`, `/exit`) |
| `kiosk-exit.sh` | `~/.local/bin/kiosk-exit.sh` | brings up a touch-usable desktop (on-screen keyboard + terminal) after Exit |
| `kiosk-agent.service` | `~/.config/systemd/user/kiosk-agent.service` | runs the agent under the user session |
| `autostart` | `~/.config/labwc/autostart` | Chromium kiosk restart loop + sentinel exit + starts the agent |
| `wifi-boot-check.sh` | `/usr/local/bin/wifi-boot-check.sh` | times WiFi association at each boot (diagnostics) |
| `wifi-boot-check.service` | `/etc/systemd/system/wifi-boot-check.service` | runs the check at boot (system service, root) |

## How it works

The kiosk's **Maintenance** tab calls the agent over `http://localhost:8765`:

- **Refresh** — pure client-side `location.reload()`, no agent needed.
- **System info** — `GET /info` returns host facts (model, OS, kernel, uptime,
  CPU temp, memory, disk, Wi-Fi/IP) shown on the Maintenance tab alongside the
  Sugar Rim / Bar Assistant API versions and browser/viewport details.
- **Reboot** — `POST /reboot` → `sudo systemctl reboot` (relies on the host's
  existing passwordless sudo).
- **Shut down** — `POST /shutdown` → `sudo systemctl poweroff`.
- **Exit** — `POST /exit` → drops `$XDG_RUNTIME_DIR/kiosk-stop`, kills Chromium,
  and runs `kiosk-exit.sh` to leave the Pi usable: it launches the on-screen
  keyboard (squeekboard) and a terminal (lxterminal). The `autostart` loop sees
  the sentinel and stops relaunching. The sentinel is on tmpfs, so a **reboot or
  power-cycle clears it** and the kiosk comes back automatically.

The Maintenance tab only shows **Exit** and **Reboot** when the agent answers
`/ping`; if it's not installed/running, those buttons are hidden and the tab
says the helper isn't running (Refresh still works).

The agent binds to `127.0.0.1` only and rejects browser requests whose `Origin`
isn't the kiosk site. The https→localhost fetch works because `localhost` is a
"potentially trustworthy" origin (no mixed-content block) and Chromium 144 did
not require a Private/Local Network Access preflight in testing; the agent still
sends the PNA headers defensively.

> **Squeekboard note:** it's masked from autostart because it renders nothing
> under the fullscreen kiosk Chromium; `kiosk-exit.sh` launches it explicitly
> (and force-shows it over DBus) only once Chromium is gone, where it works.
> After **Exit**, get back to the kiosk by rebooting (`reboot` in the terminal,
> or power-cycle).

## Install / update

From a machine that can reach bar-pi:

```sh
scp bar-pi/kiosk-agent.py        bar-pi.home:~/.local/bin/kiosk-agent.py
scp bar-pi/kiosk-exit.sh         bar-pi.home:~/.local/bin/kiosk-exit.sh
scp bar-pi/kiosk-agent.service   bar-pi.home:~/.config/systemd/user/kiosk-agent.service
scp bar-pi/autostart             bar-pi.home:~/.config/labwc/autostart

ssh bar-pi.home '
  chmod +x ~/.local/bin/kiosk-agent.py ~/.local/bin/kiosk-exit.sh ~/.config/labwc/autostart
  systemctl --user daemon-reload
  systemctl --user enable --now kiosk-agent.service
  curl -s http://127.0.0.1:8765/ping
'
```

The `autostart` change takes effect on next reboot/login.

## WiFi boot-time diagnostics

bar-pi has shown intermittent slow WiFi association at boot (one boot took ~4.5
min of `CTRL-EVENT-ASSOC-REJECT status_code=16` / "association took too long"
before connecting; surrounding boots were instant). `wifi-boot-check` records
one line per boot so recurrence can be quantified.

Install (system service, needs root):

```sh
scp bar-pi/wifi-boot-check.sh      bar-pi.home:/tmp/
scp bar-pi/wifi-boot-check.service bar-pi.home:/tmp/

ssh bar-pi.home '
  sudo install -m755 /tmp/wifi-boot-check.sh /usr/local/bin/wifi-boot-check.sh
  sudo install -m644 /tmp/wifi-boot-check.service /etc/systemd/system/wifi-boot-check.service
  sudo systemctl daemon-reload
  sudo systemctl enable wifi-boot-check.service
'
```

Review the history any time:

```sh
ssh bar-pi.home 'cat /var/log/wifi-boot-check.log'
# 2026-06-21 08:00:12  CONNECTED in 9s  ssid=hogedom bssid=… signal=-54dBm … assoc_rejects=0 assoc_timeouts=0
```

A consistently low `CONNECTED in Ns` with `assoc_rejects=0` means WiFi is
healthy; spikes (large N, non-zero rejects/timeouts) flag a recurrence — at
which point the fix is AP-side (band-steering/802.11r) or wiring Ethernet.
