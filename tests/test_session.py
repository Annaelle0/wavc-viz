import os
import sys

import numpy as np
import pytest

from wavc.audio import DemoSource
from wavc.config import Config
from wavc.session import Session


def make(**kw):
    cfg = Config(**kw).validate()
    s = Session(cfg, DemoSource())
    s.start()
    return cfg, s


def feed(s, bars=24, frames=20):
    v = None
    for _ in range(frames):
        s.feeder.source._last -= 800  # pretend wall-clock time advanced
        v = s.step(1 / 60, bars)
    return v


def test_step_returns_requested_bar_count_in_range():
    _, s = make()
    v = feed(s, 24)
    assert v.shape == (24,) and v.min() >= 0 and v.max() <= 1.0 and v.max() > 0


def test_spectrum_rebuilds_when_bar_count_or_channels_change_and_keeps_gain():
    cfg, s = make()
    feed(s, 24, 60)
    gain = s.spectrum.smoother.gain_db
    cfg.channels = "stereo"
    v = s.step(1 / 60, 30)
    assert len(v) == 30 and s.spectrum.stereo
    assert s.spectrum.smoother.gain_db == pytest.approx(gain, abs=2.0)


@pytest.mark.parametrize(
    "key,attr,expect",
    [
        ("c", "theme", "classic"),
        ("o", "orientation", "top"),
        ("s", "channels", "stereo"),
        ("r", "reverse", True),
        ("m", "monstercat", 1.5),
        ("g", "gradient_direction", "horizontal"),
        ("f", "show_fps", True),
        ("a", "autosens", False),
        ("right", "bar_width", 3),
        ("left", "bar_width", 1),
        ("up", "sensitivity", 110),
        ("down", "sensitivity", 90),
        ("n", "noise_reduction", 82),
        ("N", "noise_reduction", 72),
    ],
)
def test_key_bindings(key, attr, expect):
    cfg, s = make(theme="aurora")
    s.on_key(key)
    assert getattr(cfg, attr) == expect


def test_sensitivity_keys_disable_autosens_and_clamp():
    cfg, s = make()
    s.on_key("up")
    assert cfg.autosens is False
    for _ in range(2000):
        s.on_key("down")
    assert cfg.sensitivity == 1
    cfg.validate()


def test_quit_pause_help_and_overlay():
    cfg, s = make()
    s.on_key("space")
    assert s.paused and "paused" in s.overlay()
    before = s.step(1 / 60, 8).copy()
    assert np.array_equal(before, s.step(1 / 60, 8))
    s.on_key("h")
    assert s.overlay()[0].startswith("wavc")
    for k in ("q", "esc", "ctrl-c"):
        s.quit = False
        s.on_key(k)
        assert s.quit


def test_theme_key_clears_custom_gradient():
    cfg, s = make(gradient=["#ff0000", "#00ff00"])
    s.on_key("c")
    assert cfg.gradient == []


@pytest.mark.skipif(
    sys.platform != "win32" and not os.environ.get("DISPLAY"), reason="needs a display"
)
def test_gui_runs_a_few_frames_headless():
    pytest.importorskip("tkinter")
    from wavc.gui import run_gui

    cfg = Config(method="gui", gui_width=300, gui_height=120, framerate=120).validate()
    try:
        run_gui(cfg, DemoSource(), max_frames=10)
    except Exception as e:  # a runner without a usable display
        if "display" in str(e).lower():
            pytest.skip(str(e))
        raise


def test_posix_key_parser_handles_escape_sequences():
    from wavc.keys import KeyReader

    p = KeyReader()._parse
    assert p("\x1b[A\x1b[B\x1b[C\x1b[D") == ["up", "down", "right", "left"]
    assert p("\x1b[1;5A") == ["up"]            # modifier params
    assert p("\x1bOA") == ["up"]               # SS3 form
    assert p("\x1b") == ["esc"]
    assert p("q c") == ["q", "space", "c"]
    assert p("\x03") == ["ctrl-c"]
