#!/usr/bin/env python3
"""Close the cocktail menu when someone presses Select+Start on a gamepad.

Chromium in kiosk mode ignores the controller, so without this the TV would be
stuck on the menu. Reads the Linux joystick devices (/dev/input/js*) with the
stdlib only, and takes the Select/Start button numbers from EmulationStation's
es_input.cfg so they match what the console already uses.

Usage: menu-exit-watch.py <pid-to-terminate>
"""

import glob
import os
import select
import signal
import struct
import sys
import xml.etree.ElementTree as ET

ES_INPUT = os.path.expanduser("~/.emulationstation/es_input.cfg")
DEFAULT_BUTTONS = {"select": 8, "start": 9}  # this console's Xinmotek encoder
JS_EVENT = struct.Struct("IhBB")  # time (ms), value, type, number
JS_EVENT_BUTTON = 0x01
JS_EVENT_INIT = 0x80


def es_buttons(xml_text):
    """{deviceName: {"select": n, "start": n}} for each configured joystick."""
    out = {}
    root = ET.fromstring(xml_text)
    for cfg in root.iter("inputConfig"):
        if cfg.get("type") != "joystick":
            continue
        ids = {}
        for inp in cfg.iter("input"):
            if inp.get("name") in ("select", "start") and inp.get("type") == "button":
                ids[inp.get("name")] = int(inp.get("id"))
        if len(ids) == 2:
            out[cfg.get("deviceName") or ""] = ids
    return out


def buttons_for(device_name, configs):
    """ES and the kernel name devices differently ("mo.com Xinmotek Controller"
    vs "xin-mo.com Xinmotek Controller"), so match either way round, then fall
    back to the only configured joystick, then to this console's defaults."""
    for name, ids in configs.items():
        if name and (name in device_name or device_name in name):
            return ids
    if len(configs) == 1:
        return next(iter(configs.values()))
    return DEFAULT_BUTTONS


def decode(data):
    """Yield (pressed, button_number) for each button event in raw js bytes;
    ignores axis and synthetic initial-state events."""
    for i in range(0, len(data) - JS_EVENT.size + 1, JS_EVENT.size):
        _, value, etype, number = JS_EVENT.unpack_from(data, i)
        if etype & JS_EVENT_INIT or not etype & JS_EVENT_BUTTON:
            continue
        yield bool(value), number


class Combo:
    """Tracks one device's held buttons; True once Select and Start are both down."""

    def __init__(self, ids):
        self.want = {ids["select"], ids["start"]}
        self.held = set()

    def feed(self, data):
        for pressed, number in decode(data):
            if pressed:
                self.held.add(number)
            else:
                self.held.discard(number)
        return self.want <= self.held


def device_name(path):
    sysname = os.path.join("/sys/class/input", os.path.basename(path), "device/name")
    try:
        with open(sysname) as f:
            return f.read().strip()
    except OSError:
        return ""


def main(target_pid):
    try:
        with open(ES_INPUT) as f:
            configs = es_buttons(f.read())
    except (OSError, ET.ParseError):
        configs = {}
    devices = {}
    for path in sorted(glob.glob("/dev/input/js*")):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            continue
        devices[fd] = Combo(buttons_for(device_name(path), configs))
    if not devices:
        return  # no controller: the menu is closed some other way
    while True:
        ready, _, _ = select.select(list(devices), [], [])
        for fd in ready:
            try:
                data = os.read(fd, JS_EVENT.size * 64)
            except BlockingIOError:
                continue
            except OSError:  # controller unplugged
                devices.pop(fd)
                if not devices:
                    return
                continue
            if devices[fd].feed(data):
                os.kill(target_pid, signal.SIGTERM)
                return


if __name__ == "__main__":
    main(int(sys.argv[1]))
