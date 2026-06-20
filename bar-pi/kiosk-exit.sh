#!/bin/sh
# kiosk-exit.sh — after the kiosk browser is closed (the "Exit kiosk"
# maintenance action), leave the Pi in a touch-usable state: an on-screen
# keyboard plus a terminal. Run by kiosk-agent.
#
# The on-screen keyboard (squeekboard) is masked from autostart because it
# renders nothing underneath the fullscreen kiosk Chromium. Once Chromium is
# gone there's no occluding layer, so we can launch it and force it visible.
RT="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export XDG_RUNTIME_DIR="$RT"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$RT/bus}"

# Let Chromium release the fullscreen layer before bringing up the OSK.
sleep 1

# On-screen keyboard.
pgrep -x squeekboard >/dev/null || setsid squeekboard </dev/null >/dev/null 2>&1 &

# A terminal to actually do maintenance with.
pgrep -x lxterminal >/dev/null || setsid lxterminal </dev/null >/dev/null 2>&1 &

# Terminals don't reliably trigger the OSK on their own; force it visible,
# retrying while squeekboard finishes starting up.
i=0
while [ "$i" -lt 5 ]; do
  sleep 1
  busctl --user call sm.puri.OSK0 /sm/puri/OSK0 sm.puri.OSK0 \
    SetVisible b true >/dev/null 2>&1 && break
  i=$((i + 1))
done
