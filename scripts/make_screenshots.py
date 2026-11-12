"""Generate the README screenshots by rendering frames of the demo signal.

Requires: pip install pyte pillow
Usage:    python scripts/make_screenshots.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pyte
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wavc.audio import DemoSource  # noqa: E402
from wavc.config import Config  # noqa: E402
from wavc.dsp import Spectrum  # noqa: E402
from wavc.render import BLOCKS, TerminalRenderer  # noqa: E402

CELL_W, CELL_H = 9, 18
DEFAULT_BG = (12, 12, 20)


def hex_to_rgb(h: str, default):
    if not h or h == "default":
        return default
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def frame_to_image(frame: str, cols: int, rows: int) -> Image.Image:
    screen = pyte.Screen(cols, rows)
    pyte.Stream(screen).feed(frame)
    img = Image.new("RGB", (cols * CELL_W, rows * CELL_H), DEFAULT_BG)
    d = ImageDraw.Draw(img)
    glyphs = list(BLOCKS)
    for y in range(rows):
        for x in range(cols):
            ch = screen.buffer[y][x]
            fg = hex_to_rgb(ch.fg, (230, 230, 230))
            bg = hex_to_rgb(ch.bg, DEFAULT_BG)
            if ch.reverse:
                fg, bg = bg, fg
            x0, y0 = x * CELL_W, y * CELL_H
            d.rectangle([x0, y0, x0 + CELL_W - 1, y0 + CELL_H - 1], fill=bg)
            if ch.data in glyphs and ch.data != " ":
                h = round(glyphs.index(ch.data) / 8 * CELL_H)
                d.rectangle([x0, y0 + CELL_H - h, x0 + CELL_W - 1, y0 + CELL_H - 1], fill=fg)
    return img


def shot(name: str, cols: int, rows: int, **cfg_kw) -> None:
    cfg = Config(color_mode="truecolor", **cfg_kw).validate()
    r = TerminalRenderer(cfg)
    bars = r.bars_for_width(cols)
    sp = Spectrum(44100, bars, channels=cfg.channels, noise_reduction=cfg.noise_reduction,
                  monstercat=cfg.monstercat, reverse=cfg.reverse)
    src = DemoSource()
    pos, step = int(44100 * 3.3), 735
    for _ in range(240):  # let autosens settle, then stop on a nice frame
        sp.push(src.render(pos, step))
        pos += step
        v = sp.update(1 / 60)
    out = Path(__file__).resolve().parents[1] / "docs" / name
    frame_to_image(r.render(v, cols, rows), cols, rows).save(out)
    print("wrote", out)


if __name__ == "__main__":
    shot("terminal-fire-mirror.png", 110, 24, theme="fire", orientation="mirror", channels="stereo",
         bar_width=1)
    shot("terminal-synthwave-horizontal.png", 110, 24, theme="synthwave",
         gradient_direction="horizontal", monstercat=1.5, bar_width=3, bar_spacing=1)
