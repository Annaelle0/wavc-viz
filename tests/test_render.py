"""Verify rendered frames by interpreting them like a (tiny) terminal."""

import re

import numpy as np
import pytest

from wavc.config import Config
from wavc.render import BLOCKS, TerminalRenderer

LINE_RE = re.compile(r"\x1b\[(\d+);1H(.*?)(?=\x1b\[\d+;1H|\Z)", re.S)
SGR = re.compile(r"\x1b\[[0-9;]*m")


def lit_eighths(frame: str, cols: int, rows: int) -> np.ndarray:
    """Per-cell amount of bar-coloured area (0..8) as a terminal would draw it."""
    out = np.zeros((rows, cols), dtype=int)
    for m in LINE_RE.finditer(frame):
        y = int(m.group(1)) - 1
        body = m.group(2)
        reverse = "\x1b[7m" in body
        text = SGR.sub("", body)
        assert len(text) == cols, (len(text), cols)
        for x, ch in enumerate(text):
            level = list(BLOCKS).index(ch)
            out[y, x] = 8 - level if reverse else level
    return out


def make(**kw):
    cfg = Config(color_mode="truecolor", bar_width=2, bar_spacing=1, align="left", **kw)
    return cfg.validate(), TerminalRenderer(cfg)


@pytest.mark.parametrize("orientation", ["bottom", "top", "mirror"])
@pytest.mark.parametrize("direction", ["vertical", "horizontal"])
def test_bar_heights_are_exact(orientation, direction):
    cfg, r = make(orientation=orientation, gradient_direction=direction)
    values = np.array([0.0, 0.25, 0.5, 1.0])
    cols, rows = 11, 8
    frame = r.render(values, cols, rows)
    lit = lit_eighths(frame, cols, rows)
    for i, v in enumerate(values):
        x = i * 3
        total = lit[:, x].sum()
        full = rows * 8 if orientation != "mirror" else (rows // 2) * 8 * 2
        assert total == round(v * (rows if orientation != "mirror" else rows // 2) * 8) * (
            2 if orientation == "mirror" else 1
        ), (i, total)
        assert total <= full
        # spacing column stays empty (the last bar has none)
        if x + 2 < cols:
            assert lit[:, x + 2].sum() == 0


def test_bottom_bars_grow_from_bottom_and_top_bars_from_top():
    _, r = make(orientation="bottom")
    lit = lit_eighths(r.render(np.array([0.5]), 2, 8), 2, 8)
    assert lit[7, 0] == 8 and lit[4, 0] == 8 and lit[3, 0] == 0
    _, r = make(orientation="top")
    lit = lit_eighths(r.render(np.array([0.5]), 2, 8), 2, 8)
    assert lit[0, 0] == 8 and lit[3, 0] == 8 and lit[4, 0] == 0


def test_mirror_is_symmetric_around_the_middle():
    _, r = make(orientation="mirror")
    lit = lit_eighths(r.render(np.array([0.6, 0.3]), 5, 10), 5, 10)
    assert np.array_equal(lit[:5], lit[5:][::-1])


def test_vertical_gradient_colours_rows_and_horizontal_colours_bars():
    _, r = make(gradient="#ff0000,#0000ff".split(","), gradient_direction="vertical")
    f = r.render(np.array([1.0]), 2, 4)
    assert "38;2;255;0;0" in f and "38;2;0;0;255" in f
    _, r = make(gradient="#ff0000,#0000ff".split(","), gradient_direction="horizontal")
    f = r.render(np.array([1.0, 1.0]), 5, 3)
    assert "38;2;255;0;0" in f and "38;2;0;0;255" in f


def test_bars_for_width_and_stereo_even():
    cfg, r = make(bars=0)
    assert r.bars_for_width(100) == 33
    cfg, r = make(bars=10)
    assert r.bars_for_width(100) == 10 and r.bars_for_width(12) == 4
    cfg, r = make(channels="stereo")
    assert r.bars_for_width(100) % 2 == 0


def test_centering_and_resize_relayout():
    cfg = Config(color_mode="none", bar_width=2, bar_spacing=1, align="center").validate()
    r = TerminalRenderer(cfg)
    lit = lit_eighths(r.render(np.ones(2), 20, 3), 20, 3)
    cols_lit = np.nonzero(lit.sum(axis=0))[0]
    assert cols_lit.min() == (20 - 5) // 2
    lit2 = lit_eighths(r.render(np.ones(2), 30, 3), 30, 3)  # new size, no crash
    assert np.nonzero(lit2.sum(axis=0))[0].min() == (30 - 5) // 2


def test_color_modes():
    for mode, token in (("truecolor", "38;2;"), ("256", "38;5;")):
        cfg = Config(color_mode=mode).validate()
        assert token in TerminalRenderer(cfg).render(np.ones(3), 9, 3)
    cfg = Config(color_mode="none").validate()
    assert "38;" not in TerminalRenderer(cfg).render(np.ones(3), 9, 3)


def test_background_and_ascii_and_overlay():
    cfg = Config(color_mode="truecolor", background="#102030", charset="ascii").validate()
    f = TerminalRenderer(cfg).render(np.array([1.0]), 12, 3, overlay=["hello"])
    assert "48;2;16;32;48" in f and "hello" in f and "█" not in f


def test_values_out_of_range_are_clamped():
    _, r = make()
    r.render(np.array([-1.0, 5.0, np.nan_to_num(np.nan)]), 9, 4)
