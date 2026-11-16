# RetroPie "Cocktail Menu" port

These files live on the **RetroPie console** (`retropie.home`, the Pi 4 that
drives the living-room TV), not in the Flask app. They add a **Cocktail Menu**
entry under **Ports** in EmulationStation that shows the holiday menu board
(`/menu?key=…`) full-screen on the TV. **Select + Start** on either controller
closes it and returns to the games.

| File | Installs to | Purpose |
|------|-------------|---------|
| `Cocktail Menu.sh` | `~/RetroPie/roms/ports/` | the Ports entry; hands off to RetroPie's `runcommand` |
| `emulators.cfg` | `/opt/retropie/configs/ports/cocktail-menu/` | tells `runcommand` to start X (`XINIT:`) and run the script below |
| `cocktail-menu-x.sh` | `~/.local/bin/` | inside X: switches to 1920x1080, turns off blanking, opens Chromium in kiosk mode on the menu |
| `menu-exit-watch.py` | `~/.local/bin/` | reads `/dev/input/js*`; closes Chromium on Select + Start |

## How it works

`Cocktail Menu.sh` → `runcommand.sh` → `xinit` → `cocktail-menu-x.sh`, the same
path the existing **Desktop** port uses. When Chromium exits, X ends and
RetroPie returns to EmulationStation.

Chromium in kiosk mode ignores the gamepad, so `menu-exit-watch.py` listens to
the joystick devices directly (stdlib only; `scott` is in the `input` group). It
takes the Select/Start button numbers from EmulationStation's
`~/.emulationstation/es_input.cfg` — on this console the Xinmotek encoder uses
buttons 8 and 9 — and falls back to those numbers if it can't match a device.

Chromium uses its own profile (`~/.config/cocktail-menu/chromium`), so the
menu never restores tabs or shows a "restore pages" prompt.

## What it shows

It always opens `https://sugar.scotthoge.com/menu`, which shows whatever
holiday menu is currently published (Manage → Holiday Menu in sugar-rim), so
there is nothing to set on the console. To point it somewhere else, put a
different address on the first line of `~/.config/cocktail-menu/url`.

The console boots the TV at 1280x768 (an old `video=` setting in the Pi's
`cmdline.txt`). While the menu is open the script switches X to 1920x1080 if
the TV offers it; closing the menu ends X, so EmulationStation and the boot
settings are untouched.

The board keeps a 5% margin because this TV overscans (cuts off the edges).
If you switch the TV's picture size to "Just Scan" / "Screen Fit", use
`https://sugar.scotthoge.com/menu?inset=0` as the override above.

## Install / update

```sh
retropie/install.sh            # defaults to retropie.home
```

It copies files only. The new entry appears under Ports after EmulationStation
restarts (Start → Quit → Restart EmulationStation, or reboot).
