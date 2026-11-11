"""Terminal renderer: turns bar heights into one ANSI string per frame.

Bars are drawn with the eight lower-block glyphs (U+2581..U+2588), giving 8
vertical sub-steps per character cell. Top-anchored bars (``top`` / ``mirror``)
have no matching upper-block glyphs, so they use reverse video: the glyph's ink
becomes the *background* color and the empty area becomes the bar color.
"""

from __future__ import annotations

import numpy as np

from .colors import THEMES, bg_escape, build_gradient, fg_escape, parse_color, parse_gradient

BLOCKS = np.array(list(" ▁▂▃▄▅▆▇█"))
ASCII = np.array([" ", " ", " ", ".", ":", ":", "|", "|", "#"])
REVERSE_ON = "\x1b[7m"
RESET = "\x1b[0m"


def _row(ink: np.ndarray | None, i: int) -> list[bool] | None:
    return None if ink is None else ink[i].tolist()


class TerminalRenderer:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.color_mode = cfg.resolved_color_mode()
        self._layout_key = None
        self._row_esc: list[str] = []
        self._runs: list[tuple[int, int, str]] = []

    # -- layout ------------------------------------------------------------
    def bars_for_width(self, cols: int) -> int:
        """How many bars to analyse for a given terminal width."""
        bw, sp = self.cfg.bar_width, self.cfg.bar_spacing
        fit = max(1, (cols + sp) // (bw + sp))
        n = fit if self.cfg.bars == 0 else min(self.cfg.bars, fit)
        if self.cfg.channels == "stereo" and n > 1:
            n -= n % 2
        return max(1, n)

    def _stops(self):
        cfg = self.cfg
        return parse_gradient(cfg.gradient) if cfg.gradient else parse_gradient(THEMES[cfg.theme])

    def _prepare(self, bars: int, cols: int, rows: int) -> None:
        cfg = self.cfg
        key = (bars, cols, rows, cfg.theme, tuple(cfg.gradient), cfg.gradient_direction,
               cfg.bar_width, cfg.bar_spacing, cfg.align, cfg.orientation, self.color_mode)
        if key == self._layout_key:
            return
        self._layout_key = key
        stops = self._stops()
        half = self._half_rows(rows)
        self._row_esc = []
        self._runs = []
        if cfg.gradient_direction == "vertical":
            grad = build_gradient(stops, max(half, 1))
            self._row_esc = [fg_escape(tuple(c), self.color_mode) for c in grad]
        else:
            grad = build_gradient(stops, max(bars, 1))
            bw, sp = cfg.bar_width, cfg.bar_spacing
            left = self._left_pad(bars, cols)
            for i in range(bars):
                start = left + i * (bw + sp)
                end = start + bw + (sp if i < bars - 1 else 0)
                self._runs.append((start, min(end, cols), fg_escape(tuple(grad[i]), self.color_mode)))

    def _half_rows(self, rows: int) -> int:
        return max(1, rows // 2) if self.cfg.orientation == "mirror" else rows

    def _left_pad(self, bars: int, cols: int) -> int:
        total = bars * self.cfg.bar_width + max(bars - 1, 0) * self.cfg.bar_spacing
        return max((cols - total) // 2, 0) if self.cfg.align == "center" else 0

    # -- rendering ---------------------------------------------------------
    def _fill_matrix(self, values: np.ndarray, rows: int, cols: int) -> np.ndarray:
        """Eighths filled per cell, shape ``(rows, cols)``; row 0 = nearest the anchor."""
        cfg = self.cfg
        bars = len(values)
        eighths = np.clip(np.rint(np.clip(values, 0, 1) * rows * 8), 0, rows * 8).astype(int)
        # per-bar column fill
        r = np.arange(rows)[:, None]
        per_bar = np.clip(eighths[None, :] - r * 8, 0, 8)  # (rows, bars)
        grid = np.zeros((rows, cols), dtype=int)
        left = self._left_pad(bars, cols)
        bw, sp = cfg.bar_width, cfg.bar_spacing
        for i in range(bars):
            s = left + i * (bw + sp)
            e = min(s + bw, cols)
            if s >= cols:
                break
            grid[:, s:e] = per_bar[:, i : i + 1]
        return grid

    def _line(self, fill_row: np.ndarray, ink: list[bool] | None, glyphs: np.ndarray,
              row_idx: int, reverse: bool, bg: str) -> str:
        idx = (8 - fill_row) if reverse else fill_row
        text = "".join(glyphs[idx])
        parts = [bg]
        if reverse:
            parts.append(REVERSE_ON)
        if self.cfg.gradient_direction == "vertical":
            parts.append(self._row_esc[min(row_idx, len(self._row_esc) - 1)])
            parts.append(text)
        else:
            cur = 0
            for k, (s, e, esc) in enumerate(self._runs):
                if s > cur:
                    parts.append(text[cur:s])
                if ink[k]:  # empty cells need no color escape
                    parts.append(esc)
                parts.append(text[s:e])
                cur = e
            if cur < len(text):
                parts.append(text[cur:])
        parts.append(RESET)
        return "".join(parts)

    def _ink_flags(self, fill: np.ndarray) -> np.ndarray | None:
        """``(rows, runs)`` booleans: does this bar have any ink on this row?"""
        if self.cfg.gradient_direction != "horizontal":
            return None
        starts = np.fromiter((s for s, _, _ in self._runs), dtype=int, count=len(self._runs))
        return fill[:, np.minimum(starts, fill.shape[1] - 1)] > 0

    def render(self, values: np.ndarray, cols: int, rows: int,
               overlay: list[str] | None = None) -> str:
        """Build the full frame string for a ``cols x rows`` terminal."""
        cfg = self.cfg
        bars = len(values)
        self._prepare(bars, cols, rows)
        glyphs = BLOCKS if cfg.charset == "blocks" else ASCII
        bg = "" if cfg.background == "default" else bg_escape(parse_color(cfg.background), self.color_mode)
        out: list[str] = []
        if cfg.orientation == "mirror":
            half = self._half_rows(rows)
            fill = self._fill_matrix(values, half, cols)
            ink = self._ink_flags(fill)
            for y in range(half):  # top half grows upward from the middle
                ridx = half - 1 - y
                out.append(f"\x1b[{y + 1};1H"
                           + self._line(fill[ridx], _row(ink, ridx), glyphs, ridx, False, bg))
            for y in range(half):  # bottom half grows downward
                out.append(f"\x1b[{half + y + 1};1H"
                           + self._line(fill[y], _row(ink, y), glyphs, y, True, bg))
            if rows > 2 * half:
                out.append(f"\x1b[{rows};1H" + RESET + bg + " " * cols + RESET)
        elif cfg.orientation == "top":
            fill = self._fill_matrix(values, rows, cols)
            ink = self._ink_flags(fill)
            for y in range(rows):
                out.append(f"\x1b[{y + 1};1H"
                           + self._line(fill[y], _row(ink, y), glyphs, y, True, bg))
        else:
            fill = self._fill_matrix(values, rows, cols)
            ink = self._ink_flags(fill)
            for y in range(rows):
                ridx = rows - 1 - y
                out.append(f"\x1b[{y + 1};1H"
                           + self._line(fill[ridx], _row(ink, ridx), glyphs, ridx, False, bg))
        if overlay:
            for i, text in enumerate(overlay[: max(rows, 1)]):
                out.append(f"\x1b[{i + 1};1H{RESET}\x1b[7m {text[: max(cols - 2, 1)]} {RESET}")
        return "".join(out)
