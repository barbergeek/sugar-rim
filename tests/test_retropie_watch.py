import importlib.util
import struct
from pathlib import Path

SRC = Path(__file__).parent.parent / "retropie" / "menu-exit-watch.py"
spec = importlib.util.spec_from_file_location("menu_exit_watch", SRC)
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)

# The console's real es_input.cfg (Xinmotek arcade encoder).
ES_XML = """<?xml version="1.0"?>
<inputList>
  <inputAction type="onfinish"><command>x.sh</command></inputAction>
  <inputConfig type="keyboard" deviceName="Keyboard">
    <input name="select" type="key" id="1073742053" value="1"/>
    <input name="start" type="key" id="13" value="1"/>
  </inputConfig>
  <inputConfig type="joystick" deviceName="mo.com Xinmotek Controller">
    <input name="a" type="button" id="1" value="1"/>
    <input name="select" type="button" id="8" value="1"/>
    <input name="start" type="button" id="9" value="1"/>
    <input name="up" type="axis" id="1" value="-1"/>
  </inputConfig>
</inputList>"""


def ev(number, value, etype=w.JS_EVENT_BUTTON):
    return struct.pack("IhBB", 0, value, etype, number)


def test_es_buttons_reads_joysticks_only():
    assert w.es_buttons(ES_XML) == {
        "mo.com Xinmotek Controller": {"select": 8, "start": 9}
    }


def test_kernel_name_matches_es_name():
    cfg = w.es_buttons(ES_XML)
    assert w.buttons_for("xin-mo.com Xinmotek Controller", cfg) == {
        "select": 8,
        "start": 9,
    }


def test_unknown_device_falls_back():
    two = {"Pad A": {"select": 6, "start": 7}, "Pad B": {"select": 10, "start": 11}}
    assert w.buttons_for("Something Else", two) == w.DEFAULT_BUTTONS
    one = {"Pad A": {"select": 6, "start": 7}}
    assert w.buttons_for("Something Else", one) == {"select": 6, "start": 7}


def test_combo_needs_both_held_together():
    c = w.Combo({"select": 8, "start": 9})
    assert not c.feed(ev(8, 1))
    assert not c.feed(ev(8, 0) + ev(9, 1))  # select released before start
    assert c.feed(ev(8, 1))


def test_init_and_axis_events_are_ignored():
    c = w.Combo({"select": 8, "start": 9})
    # Initial-state events report buttons as "pressed" when a device opens.
    assert not c.feed(ev(8, 1, w.JS_EVENT_INIT | w.JS_EVENT_BUTTON) + ev(9, 1, 0x02))
    assert c.held == set()


def test_decode_handles_several_events_and_partial_tail():
    data = ev(1, 1) + ev(2, 1) + ev(1, 0) + b"\x00\x01"
    assert list(w.decode(data)) == [(True, 1), (True, 2), (False, 1)]
