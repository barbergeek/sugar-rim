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
| `cocktail-menu-x.sh` | `~/.local/bin/` | inside X: turns off blanking, opens Chromium in kiosk mode on the menu link |
| `menu-exit-watch.py` | `~/.local/bin/` | reads `/dev/input/js*`; closes Chromium on Select + Start |
| `no-url.html` | `~/.local/share/cocktail-menu/` | shown when no menu link has been saved yet |

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

## The menu link

The script reads the board's address from `~/.config/cocktail-menu/url`
(one line). Copy it from sugar-rim **Manage → Holiday Menu → Display link**:

```sh
ssh retropie.home 'cat > ~/.config/cocktail-menu/url' <<< 'https://sugar.scotthoge.com/menu?key=…'
```

Pressing **New Link** in Manage → Holiday Menu invalidates the old link, so update this file
afterwards. Without a link, the port shows a "No menu link yet" screen.

The board keeps a 5% margin because this TV overscans (cuts off the edges) in
X. If you switch the TV's picture size to "Just Scan" / "Screen Fit", add
`&inset=0` to the end of the link to use the full screen.

## Install / update

```sh
retropie/install.sh            # defaults to retropie.home
```

It copies files only. The new entry appears under Ports after EmulationStation
restarts (Start → Quit → Restart EmulationStation, or reboot).
