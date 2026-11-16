#!/bin/bash
# Runs inside the X session that RetroPie's runcommand starts for the
# "Cocktail Menu" port (emulators.cfg: XINIT:). When Chromium exits, X ends
# and RetroPie returns to EmulationStation.

CONF="$HOME/.config/cocktail-menu"
URL_FILE="$CONF/url"
SHARE="$HOME/.local/share/cocktail-menu"

xset -dpms s off s noblank  # the menu sits on screen for hours

URL=""
[[ -s "$URL_FILE" ]] && URL=$(head -n1 "$URL_FILE" | tr -d '[:space:]')
[[ "$URL" == http* ]] || URL="file://$SHARE/no-url.html"

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
