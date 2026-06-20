#!/usr/bin/env python3
"""
kiosk-agent — tiny localhost-only helper for the sugar-rim bar-pi kiosk.

The kiosk page is served from a remote host (gimli), but actions like
"reboot this display" or "exit the kiosk browser" must run *here*, on the
Pi. This agent exposes a couple of localhost endpoints the kiosk page can
call from JavaScript:

    GET  /ping     -> {"ok": true}                 (transport / health check)
    POST /reboot   -> reboots the host
    POST /exit     -> stops the kiosk restart loop and quits Chromium

It binds to 127.0.0.1 only, so nothing off-box can reach it. As defence in
depth it also rejects requests whose Origin header isn't the kiosk site.
"""

import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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


class Handler(BaseHTTPRequestHandler):
    server_version = "kiosk-agent/1.0"

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

        elif self.path == "/exit":
            # Drop the sentinel so the autostart loop won't relaunch, then kill
            # the kiosk Chromium. A reboot/power-cycle clears the sentinel.
            try:
                open(STOP_SENTINEL, "w").close()
            except OSError as e:
                self._json(500, {"ok": False, "error": str(e)})
                return
            subprocess.Popen(["pkill", "-f", "chromium.*--kiosk"])
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
