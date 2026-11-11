"""Native window front-end (tkinter, ships with Python on Windows)."""

from __future__ import annotations

import sys
import time

import numpy as np

from .audio import AudioSource
from .colors import THEMES, build_gradient, parse_color, parse_gradient, to_hex
from .session import Session

TRANSPARENT_KEY = "#010203"  # color treated as see-through when gui_transparent is on


class GuiApp:
    def __init__(self, cfg, source: AudioSource, max_frames: int | None = None) -> None:
        import tkinter as tk

        self.tk = tk
        self.cfg = cfg
        self.session = Session(cfg, source)
        self.max_frames = max_frames
        self.frames = 0
        self.root = tk.Tk()
        self.root.title("wavc")
        self.root.geometry(f"{cfg.gui_width}x{cfg.gui_height}")
        self.root.minsize(120, 60)
        self.bg = TRANSPARENT_KEY if cfg.gui_transparent else self._bg_hex()
        self.canvas = tk.Canvas(self.root, bg=self.bg, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self._items: list[int] = []
        self._overlay_id = None
        self._layout_bars = 0
        self._palette: np.ndarray | None = None
        self._palette_key = None
        self._last = time.perf_counter()
        self._drag = (0, 0)

        if cfg.gui_topmost:
            self.root.attributes("-topmost", True)
        if cfg.gui_borderless:
            self.root.overrideredirect(True)
        if cfg.gui_transparent:
            try:
                self.root.attributes("-transparentcolor", TRANSPARENT_KEY)
            except Exception:
                pass  # only supported on Windows

        self.root.bind("<Key>", self._on_key)
        self.root.bind("<Escape>", lambda e: self._quit())
        self.canvas.bind("<ButtonPress-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<Button-3>", lambda e: self._quit())
        self.canvas.bind("<Double-Button-1>", lambda e: self._toggle_borderless())
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.root.protocol("WM_DELETE_WINDOW", self._quit)

    # -- helpers ---------------------------------------------------------------
    def _bg_hex(self) -> str:
        if self.cfg.background == "default":
            return "#0b0b12"
        return to_hex(parse_color(self.cfg.background))

    def _quit(self) -> None:
        self.session.quit = True

    def _toggle_borderless(self) -> None:
        self.cfg.gui_borderless = not self.cfg.gui_borderless
        self.root.overrideredirect(self.cfg.gui_borderless)

    def _drag_start(self, e) -> None:
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _drag_move(self, e) -> None:
        self.root.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _wheel(self, e) -> None:
        self.session.on_key("up" if e.delta > 0 else "down")

    def _on_key(self, e) -> None:
        names = {"Up": "up", "Down": "down", "Left": "left", "Right": "right",
                 "space": "space", "Escape": "esc"}
        key = names.get(e.keysym) or (e.char if e.char else e.keysym)
        self.session.on_key(key)

    # -- drawing ---------------------------------------------------------------------
    def _bars_for_width(self, width: int) -> int:
        cfg = self.cfg
        unit = cfg.bar_width * 4 + cfg.bar_spacing * 2  # GUI pixels: scale terminal units
        fit = max(1, (width + cfg.bar_spacing * 2) // max(unit, 1))
        n = fit if cfg.bars == 0 else min(cfg.bars, fit)
        if cfg.channels == "stereo" and n > 1:
            n -= n % 2
        return max(1, n)

    def _ensure_items(self, bars: int) -> None:
        if bars == self._layout_bars:
            return
        self.canvas.delete("all")
        self._items = [self.canvas.create_rectangle(0, 0, 0, 0, width=0, fill="#ffffff")
                       for _ in range(bars)]
        self._overlay_id = self.canvas.create_text(8, 8, anchor="nw", fill="#ffffff",
                                                   font=("Consolas", 10), text="")
        self._layout_bars = bars

    def _colors(self, bars: int) -> np.ndarray:
        cfg = self.cfg
        key = (cfg.theme, tuple(cfg.gradient), cfg.gradient_direction, bars)
        if key != self._palette_key:
            stops = parse_gradient(cfg.gradient) if cfg.gradient else parse_gradient(THEMES[cfg.theme])
            n = bars if cfg.gradient_direction == "horizontal" else 256
            self._palette = build_gradient(stops, n)
            self._palette_key = key
        return self._palette

    def _tick(self) -> None:
        s = self.session
        if s.quit or (self.max_frames is not None and self.frames >= self.max_frames):
            self.root.quit()
            return
        cfg = self.cfg
        t0 = time.perf_counter()
        dt = min(max(t0 - self._last, 1e-4), 0.25)
        self._last = t0

        w = max(self.canvas.winfo_width(), 2)
        h = max(self.canvas.winfo_height(), 2)
        bars = self._bars_for_width(w)
        values = s.step(dt, bars)
        self._ensure_items(bars)
        pal = self._colors(bars)

        bw = max(cfg.bar_width * 4, 1)
        gap = cfg.bar_spacing * 2
        total = bars * bw + (bars - 1) * gap
        x0 = max((w - total) // 2, 0) if cfg.align == "center" else 0
        for i, v in enumerate(values):
            x = x0 + i * (bw + gap)
            bh = max(v * h, 1 if v > 0.002 else 0)
            if cfg.orientation == "bottom":
                y1, y2 = h - bh, h
            elif cfg.orientation == "top":
                y1, y2 = 0, bh
            else:
                y1, y2 = (h - bh) / 2, (h + bh) / 2
            col = pal[i] if cfg.gradient_direction == "horizontal" else pal[min(int(v * 255), 255)]
            self.canvas.coords(self._items[i], x, y1, x + bw, y2)
            self.canvas.itemconfigure(self._items[i], fill=to_hex(col),
                                      state="normal" if bh > 0 else "hidden")
        lines = s.overlay()
        self.canvas.itemconfigure(self._overlay_id, text="\n".join(lines))
        self.canvas.tag_raise(self._overlay_id)
        self.frames += 1
        delay = max(int(1000 / cfg.framerate - (time.perf_counter() - t0) * 1000), 1)
        self.root.after(delay, self._tick)

    def run(self) -> None:
        self.session.start()
        try:
            self.root.after(10, self._tick)
            self.root.mainloop()
        finally:
            self.session.stop()
            try:
                self.root.destroy()
            except Exception:
                pass


def run_gui(cfg, source: AudioSource, max_frames: int | None = None) -> None:
    try:
        import tkinter  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "tkinter is not available. On Windows reinstall Python with 'tcl/tk' enabled, "
            "or use method = terminal."
        ) from e
    if sys.platform != "win32" and cfg.gui_transparent:
        cfg.gui_transparent = False
    GuiApp(cfg, source, max_frames).run()
