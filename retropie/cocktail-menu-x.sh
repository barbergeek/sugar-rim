#!/bin/bash
# Runs inside the X session that RetroPie's runcommand starts for the
# "Cocktail Menu" port (emulators.cfg: XINIT:). When Chromium exits, X ends
# and RetroPie returns to EmulationStation.

CONF="$HOME/.config/cocktail-menu"
# Always the currently published holiday menu. A first line in
# ~/.config/cocktail-menu/url overrides it (optional; nothing to set up).
URL="https://sugar.scotthoge.com/menu"
if [[ -s "$CONF/url" ]]; then
  OVERRIDE=$(head -n1 "$CONF/url" | tr -d '[:space:]')
  [[ "$OVERRIDE" == http* ]] && URL="$OVERRIDE"
fi

xset -dpms s off s noblank  # the menu sits on screen for hours

# The console boots the TV at a low resolution (1280x768). For the menu
# only, switch X to 1920x1080 when the TV offers it; X ends when the menu
# closes, so EmulationStation and the boot settings are untouched.
OUT=$(xrandr --query | awk '/ connected/ {print $1; exit}')
if [[ -n "$OUT" ]] && xrandr --query | grep -qE '^ +1920x1080 '; then
  xrandr --output "$OUT" --mode 1920x1080
fi

# Select+Start ends Chromium with SIGTERM, which it records as a crash; mark
# the last exit clean so it never opens with a "Restore pages?" prompt
# (same fix as bar-pi/autostart).
python3 - "$CONF/chromium/Default/Preferences" <<'EOF' 2>/dev/null
import json, sys
f = sys.argv[1]
try:
    with open(f) as fp:
        d = json.load(fp)
    d.setdefault("profile", {}).update(exit_type="Normal", exited_cleanly=True)
    with open(f, "w") as fp:
        json.dump(d, fp)
except (OSError, ValueError):
    pass
EOF

chromium \
  --kiosk --start-fullscreen --window-position=0,0 \
  --user-data-dir="$CONF/chromium" \
  --password-store=basic --noerrdialogs --disable-session-crashed-bubble \
  --disable-infobars --no-first-run --check-for-update-interval=31536000 \
  "$URL" &
BROWSER=$!

python3 "$HOME/.local/bin/menu-exit-watch.py" "$BROWSER" &
WATCH=$!

wait "$BROWSER"
kill "$WATCH" 2>/dev/null
