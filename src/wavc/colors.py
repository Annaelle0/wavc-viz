"""Color parsing, gradient themes and ANSI escape helpers."""

from __future__ import annotations

import re
from typing import Sequence

import numpy as np

# Gradients run from the low end of a bar (first stop) to its tip (last stop).
THEMES: dict[str, list[str]] = {
    "aurora": ["#00f5a0", "#00d9f5", "#7b61ff", "#ff3cac"],
    "classic": ["#33cc33", "#cccc33", "#cc3333"],
    "fire": ["#8b0000", "#ff4500", "#ffa500", "#ffff66"],
    "ocean": ["#0077be", "#00b4d8", "#90e0ef", "#caf0f8"],
    "sunset": ["#3a1c71", "#d76d77", "#ffaf7b"],
    "matrix": ["#003b00", "#00aa00", "#00ff41"],
    "rainbow": ["#ff0000", "#ffaa00", "#ffff00", "#00ff55", "#00aaff", "#aa00ff"],
    "synthwave": ["#2de2e6", "#a64dff", "#ff2a6d"],
    "ice": ["#e0f7ff", "#7fd4ff", "#2f80ff"],
    "mono": ["#ffffff"],
}

NAMED_COLORS: dict[str, tuple[int, int, int]] = {
    "black": (0, 0, 0),
    "white": (255, 255, 255),
    "red": (255, 0, 0),
    "green": (0, 200, 0),
    "blue": (0, 100, 255),
    "yellow": (255, 255, 0),
    "cyan": (0, 255, 255),
    "magenta": (255, 0, 255),
    "orange": (255, 165, 0),
    "purple": (150, 60, 220),
    "pink": (255, 105, 180),
    "gray": (128, 128, 128),
    "grey": (128, 128, 128),
}

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def parse_color(text: str) -> tuple[int, int, int]:
    """Parse ``#rgb``, ``#rrggbb``, ``rrggbb`` or a basic color name."""
    s = text.strip().lower()
    if s in NAMED_COLORS:
        return NAMED_COLORS[s]
    m = _HEX_RE.match(s)
    if not m:
        raise ValueError(f"invalid color {text!r} (use #rrggbb or a name like 'red')")
    h = m.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def parse_gradient(stops: Sequence[str]) -> list[tuple[int, int, int]]:
    out = [parse_color(s) for s in stops if s.strip()]
    if not out:
        raise ValueError("gradient needs at least one color")
    return out


def build_gradient(stops: Sequence[tuple[int, int, int]], n: int) -> np.ndarray:
    """Return an ``(n, 3)`` uint8 array interpolated across ``stops``."""
    n = max(1, int(n))
    arr = np.asarray(stops, dtype=np.float64)
    if len(arr) == 1 or n == 1:
        return np.tile(arr[0], (n, 1)).astype(np.uint8)
    xs = np.linspace(0.0, 1.0, len(arr))
    t = np.linspace(0.0, 1.0, n)
    cols = np.stack([np.interp(t, xs, arr[:, c]) for c in range(3)], axis=1)
    return np.clip(np.rint(cols), 0, 255).astype(np.uint8)


def rgb_to_256(r: int, g: int, b: int) -> int:
    """Nearest xterm-256 color index (6x6x6 cube or grayscale ramp)."""
    if r == g == b:
        if r < 8:
            return 16
        if r > 248:
            return 231
        return 232 + int(round((r - 8) / 247 * 24))
    return 16 + 36 * int(round(r / 255 * 5)) + 6 * int(round(g / 255 * 5)) + int(round(b / 255 * 5))


def fg_escape(rgb: tuple[int, int, int], mode: str) -> str:
    r, g, b = (int(v) for v in rgb)
    if mode == "truecolor":
        return f"\x1b[38;2;{r};{g};{b}m"
    if mode == "256":
        return f"\x1b[38;5;{rgb_to_256(r, g, b)}m"
    return ""


def bg_escape(rgb: tuple[int, int, int], mode: str) -> str:
    r, g, b = (int(v) for v in rgb)
    if mode == "truecolor":
        return f"\x1b[48;2;{r};{g};{b}m"
    if mode == "256":
        return f"\x1b[48;5;{rgb_to_256(r, g, b)}m"
    return ""


def to_hex(rgb: Sequence[int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(int(v) for v in rgb))
