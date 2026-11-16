#!/bin/bash
# Install or update the Cocktail Menu port on the RetroPie console.
# Run from a machine that can ssh to it:  retropie/install.sh [host]
# Installs files only; restart EmulationStation (or reboot) to see the entry.
set -euo pipefail
HOST="${1:-retropie.home}"
DIR="$(cd "$(dirname "$0")" && pwd)"

ssh "$HOST" 'mkdir -p ~/.local/bin ~/.local/share/cocktail-menu ~/.config/cocktail-menu \
  /opt/retropie/configs/ports/cocktail-menu'
scp "$DIR/cocktail-menu-x.sh" "$DIR/menu-exit-watch.py" "$HOST:.local/bin/"
scp "$DIR/no-url.html" "$HOST:.local/share/cocktail-menu/"
scp "$DIR/emulators.cfg" "$HOST:/opt/retropie/configs/ports/cocktail-menu/emulators.cfg"
scp "$DIR/Cocktail Menu.sh" "$HOST:RetroPie/roms/ports/"
ssh "$HOST" 'chmod +x ~/.local/bin/cocktail-menu-x.sh ~/.local/bin/menu-exit-watch.py \
  ~/RetroPie/roms/ports/"Cocktail Menu.sh"'
echo "Installed on $HOST. Put the display link in ~/.config/cocktail-menu/url there."
