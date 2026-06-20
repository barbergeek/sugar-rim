#!/bin/sh
# wifi-boot-check — record how long WiFi takes to associate after each boot,
# for diagnosing bar-pi's intermittent slow-association issue. Appends one line
# per boot to LOG. Started at boot by wifi-boot-check.service.
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

LOG=/var/log/wifi-boot-check.log
IFACE=wlan0
DEADLINE=600   # stop waiting after 10 minutes

uptime_s() { awk '{print int($1)}' /proc/uptime; }

# Wait until the interface has a global IPv4 address (i.e. fully connected),
# or until the deadline.
connected=no
while :; do
  if ip -4 addr show "$IFACE" 2>/dev/null | grep -q 'inet '; then
    connected=yes
    break
  fi
  [ "$(uptime_s)" -ge "$DEADLINE" ] && break
  sleep 1
done

now=$(date '+%Y-%m-%d %H:%M:%S')
secs=$(uptime_s)
# Association problems seen so far this boot (from the kernel/NM journal).
rejects=$(journalctl -b 2>/dev/null | grep -c 'CTRL-EVENT-ASSOC-REJECT')
timeouts=$(journalctl -b 2>/dev/null | grep -c 'association took too long')

if [ "$connected" = yes ]; then
  link=$(iw dev "$IFACE" link 2>/dev/null)
  ip=$(ip -4 -br addr show "$IFACE" 2>/dev/null | awk '{print $3}')
  bssid=$(printf '%s\n' "$link" | awk '/Connected to/{print $3}')
  ssid=$(printf '%s\n' "$link" | awk -F': ' '/[[:space:]]SSID:/{print $2}')
  freq=$(printf '%s\n' "$link" | awk '/freq:/{print $2}')
  signal=$(printf '%s\n' "$link" | awk '/signal:/{print $2}')
  printf '%s  CONNECTED in %ss  ssid=%s bssid=%s freq=%sMHz signal=%sdBm ip=%s assoc_rejects=%s assoc_timeouts=%s\n' \
    "$now" "$secs" "${ssid:-?}" "${bssid:-?}" "${freq:-?}" "${signal:-?}" "${ip:-?}" "$rejects" "$timeouts" >> "$LOG"
else
  printf '%s  TIMEOUT after %ss (no IPv4 on %s) assoc_rejects=%s assoc_timeouts=%s\n' \
    "$now" "$secs" "$IFACE" "$rejects" "$timeouts" >> "$LOG"
fi
