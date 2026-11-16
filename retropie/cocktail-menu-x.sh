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
