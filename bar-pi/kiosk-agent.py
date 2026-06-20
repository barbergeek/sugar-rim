#!/usr/bin/env python3
"""
kiosk-agent — tiny localhost-only helper for the sugar-rim bar-pi kiosk.

The kiosk page is served from a remote host (gimli), but actions like
"reboot this display" or "exit the kiosk browser" must run *here*, on the
Pi. This agent exposes a couple of localhost endpoints the kiosk page can
call from JavaScript:

    GET  /ping     -> {"ok": true}                 (transport / health check)
    GET  /info     -> host facts (uptime, temp, mem, wifi, …)
    POST /reboot   -> reboots the host
    POST /shutdown -> powers off the host
    POST /exit     -> stops the kiosk restart loop and quits Chromium

It binds to 127.0.0.1 only, so nothing off-box can reach it. As defence in
depth it also rejects requests whose Origin header isn't the kiosk site.
"""

import glob
import json
import os
import shutil
import socket
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

AGENT_VERSION = "1.1"
HOST = "127.0.0.1"
PORT = int(os.environ.get("KIOSK_AGENT_PORT", "8765"))

# Browser origins allowed to drive the agent. The kiosk only ever loads the
# remote site; a local reverse-proxy fallback would be http://localhost.
ALLOWED_ORIGINS = {
    "https://sugar.scotthoge.com",
    "http://localhost",
    "http://127.0.0.1",
}

# Sentinel the labwc autostart loop watches: when present, it stops relaunching
# Chromium. Lives in XDG_RUNTIME_DIR (tmpfs) so it clears on reboot/logout and a
# power-cycle always brings the kiosk back.
RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
STOP_SENTINEL = os.path.join(RUNTIME_DIR, "kiosk-stop")


def _origin_ok(origin):
    # No Origin header => not a browser fetch (curl, health probe): allow.
    return origin is None or origin in ALLOWED_ORIGINS


def _read(path, default=""):
    try:
        with open(path) as fp:
            return fp.read().strip()
    except OSError:
        return default


def _os_pretty():
    for line in _read("/etc/os-release").splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


def _wifi():
    """SSID / signal / band for wlan0, via `iw` (best-effort)."""
    out = {}
    try:
        link = subprocess.run(
            ["iw", "dev", "wlan0", "link"],
            capture_output=True, text=True, timeout=4,
        ).stdout
    except Exception:
        return out
    for line in link.splitlines():
        s = line.strip()
        if s.startswith("SSID:"):
            out["ssid"] = s.split(":", 1)[1].strip()
        elif s.startswith("signal:"):
            out["signal_dbm"] = s.split(":", 1)[1].strip().split()[0]
        elif s.startswith("freq:"):
            out["freq_mhz"] = s.split(":", 1)[1].strip()
        elif s.startswith("rx bitrate:"):
            out["rx_bitrate"] = s.split(":", 1)[1].strip()
    return out


def _ipv4():
    try:
        out = subprocess.run(
            ["ip", "-4", "-br", "addr", "show", "wlan0"],
            capture_output=True, text=True, timeout=4,
        ).stdout.split()
        return out[2].split("/")[0] if len(out) >= 3 else ""
    except Exception:
        return ""


def _host_info():
    info = {
        "agent_version": AGENT_VERSION,
        "hostname": socket.gethostname(),
        "model": _read("/proc/device-tree/model").replace("\x00", "").strip(),
        "os": _os_pretty(),
        "kernel": os.uname().release,
    }
    try:
        info["uptime_seconds"] = int(float(_read("/proc/uptime").split()[0]))
    except (ValueError, IndexError):
        pass
    try:
        info["load"] = [round(x, 2) for x in os.getloadavg()]
    except OSError:
        pass
    # CPU temperature (first thermal zone).
    zones = glob.glob("/sys/class/thermal/thermal_zone0/temp")
    if zones:
        raw = _read(zones[0])
        if raw.isdigit():
            info["cpu_temp_c"] = round(int(raw) / 1000, 1)
    # Memory (kB → MB).
    mem = {}
    for line in _read("/proc/meminfo").splitlines():
        if line.startswith(("MemTotal:", "MemAvailable:")):
            k, v = line.split(":")
            mem[k] = int(v.strip().split()[0])
    if "MemTotal" in mem and "MemAvailable" in mem:
        info["mem_total_mb"] = round(mem["MemTotal"] / 1024)
        info["mem_used_mb"] = round((mem["MemTotal"] - mem["MemAvailable"]) / 1024)
    # Root filesystem (bytes → GB).
    try:
        du = shutil.disk_usage("/")
        info["disk_total_gb"] = round(du.total / 1e9, 1)
        info["disk_used_gb"] = round(du.used / 1e9, 1)
    except OSError:
        pass
    info["wifi"] = _wifi()
    info["ip"] = _ipv4()
    return info


class Handler(BaseHTTPRequestHandler):
    server_version = f"kiosk-agent/{AGENT_VERSION}"

    # ---- helpers -------------------------------------------------------
    def _cors(self):
        origin = self.headers.get("Origin")
        self.send_header(
            "Access-Control-Allow-Origin",
            origin if origin in ALLOWED_ORIGINS else "https://sugar.scotthoge.com",
        )
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        # Private/Local Network Access preflight: let a public-origin page reach
        # this loopback service.
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write("kiosk-agent: " + (fmt % args) + "\n")

    # ---- routes --------------------------------------------------------
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path == "/ping":
            self._json(200, {"ok": True, "agent": "kiosk-agent"})
        elif self.path == "/info":
            self._json(200, {"ok": True, "host": _host_info()})
        else:
            self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if not _origin_ok(self.headers.get("Origin")):
            self._json(403, {"ok": False, "error": "forbidden origin"})
            return

        if self.path == "/reboot":
            # Respond first; the connection dies once the box goes down.
            self._json(200, {"ok": True, "action": "reboot"})
            self.wfile.flush()
            subprocess.Popen(["sudo", "systemctl", "reboot"])

        elif self.path == "/shutdown":
            # Respond first; the connection dies once the box powers off.
            self._json(200, {"ok": True, "action": "shutdown"})
            self.wfile.flush()
            subprocess.Popen(["sudo", "systemctl", "poweroff"])

        elif self.path == "/exit":
            # Drop the sentinel so the autostart loop won't relaunch, then kill
            # Chromium. A reboot/power-cycle clears the sentinel.
            try:
                open(STOP_SENTINEL, "w").close()
            except OSError as e:
                self._json(500, {"ok": False, "error": str(e)})
                return
            subprocess.Popen(["pkill", "chromium"])
            # Leave the Pi touch-usable: bring up an on-screen keyboard + a
            # terminal (the kiosk hides both while it's running).
            helper = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "kiosk-exit.sh"
            )
            if os.path.exists(helper):
                subprocess.Popen(["/bin/sh", helper])
            self._json(200, {"ok": True, "action": "exit"})

        else:
            self._json(404, {"ok": False, "error": "not found"})


def main():
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    sys.stderr.write(f"kiosk-agent: listening on http://{HOST}:{PORT}\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
