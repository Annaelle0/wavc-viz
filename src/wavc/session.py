"""Shared runtime state for the terminal and GUI front-ends."""

from __future__ import annotations

import time
from dataclasses import replace

import numpy as np

from .audio import AudioFeeder, AudioSource
from .colors import THEMES
from .dsp import Spectrum

HELP_LINES = [
    "wavc - keys",
    "q / Esc   quit",
    "Up / Down sensitivity (disables autosens)",
    "a         toggle autosens",
    "Left/Right bar width",
    "c         next color theme",
    "g         gradient direction",
    "o         orientation (bottom/top/mirror)",
    "s         mono / stereo",
    "r         reverse",
    "m         monstercat smoothing",
    "n / N     smoothing more / less",
    "Space     pause",
    "f         fps counter",
    "h         this help",
]


class Session:
    """Owns the audio feeder + spectrum and applies runtime key commands."""

    def __init__(self, cfg, source: AudioSource) -> None:
        self.cfg = cfg
        self.feeder = AudioFeeder(source)
        self.spectrum: Spectrum | None = None
        self._spec_key = None
        self.paused = False
        self.show_help = False
        self.quit = False
        self._message = ""
        self._message_until = 0.0
        self._fps = 0.0
        self._last_values = np.zeros(1)

    # -- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        self.feeder.start()

    def stop(self) -> None:
        self.feeder.stop()

    # -- per-frame -------------------------------------------------------------
    def _key(self, bars: int):
        c = self.cfg
        return (bars, self.feeder.rate, c.channels, c.lower_cutoff, c.upper_cutoff, c.framerate,
                c.noise_reduction, c.monstercat, c.scale, c.tilt, tuple(c.eq), c.reverse)

    def step(self, dt: float, bars: int) -> np.ndarray:
        """Advance one frame and return ``bars`` values in ``[0, 1]``."""
        c = self.cfg
        key = self._key(bars)
        if self.spectrum is None or key != self._spec_key:
            old_gain = self.spectrum.smoother.gain_db if self.spectrum else None
            self.spectrum = Spectrum(
                self.feeder.rate, bars, channels=c.channels, lower=c.lower_cutoff,
                upper=c.upper_cutoff, framerate=c.framerate, noise_reduction=c.noise_reduction,
                monstercat=c.monstercat, autosens=c.autosens, sensitivity=c.sensitivity,
                scale=c.scale, tilt_db=c.tilt, eq=c.eq or None, reverse=c.reverse,
            )
            if old_gain is not None:  # keep the learned gain across rebuilds
                self.spectrum.smoother.gain_db = old_gain
            self._spec_key = key
        sm = self.spectrum.smoother
        sm.autosens, sm.sensitivity = c.autosens, c.sensitivity

        samples = self.feeder.read(dt)
        if self.paused:
            return self._last_values
        self.spectrum.push(samples)
        values = self.spectrum.update(dt)
        self._last_values = values
        if dt > 0:
            self._fps = 0.9 * self._fps + 0.1 / dt if self._fps else 1.0 / dt
        return values

    # -- overlay -----------------------------------------------------------------
    def notify(self, text: str, seconds: float = 1.8) -> None:
        self._message = text
        self._message_until = time.perf_counter() + seconds

    def overlay(self) -> list[str]:
        lines: list[str] = []
        if self.show_help:
            lines.extend(HELP_LINES)
        else:
            if time.perf_counter() < self._message_until:
                lines.append(self._message)
            if self.cfg.show_fps:
                lines.append(f"{self._fps:5.1f} fps  {self.feeder.source.name}")
            if self.paused:
                lines.append("paused")
        return lines

    # -- keys ----------------------------------------------------------------------
    def on_key(self, key: str) -> None:
        c = self.cfg
        k = key.lower() if len(key) == 1 and key not in "N" else key
        if k in ("q", "esc", "ctrl-c"):
            self.quit = True
        elif k == "up":
            c.autosens = False
            c.sensitivity = min(c.sensitivity + 10, 10000)
            self.notify(f"sensitivity {c.sensitivity}%  (autosens off)")
        elif k == "down":
            c.autosens = False
            c.sensitivity = max(c.sensitivity - 10, 1)
            self.notify(f"sensitivity {c.sensitivity}%  (autosens off)")
        elif k == "a":
            c.autosens = not c.autosens
            self.notify(f"autosens {'on' if c.autosens else 'off'}")
        elif k == "right":
            c.bar_width = min(c.bar_width + 1, 50)
            self.notify(f"bar width {c.bar_width}")
        elif k == "left":
            c.bar_width = max(c.bar_width - 1, 1)
            self.notify(f"bar width {c.bar_width}")
        elif k == "c":
            names = list(THEMES)
            c.gradient = []
            c.theme = names[(names.index(c.theme) + 1) % len(names)] if c.theme in names else names[0]
            self.notify(f"theme: {c.theme}")
        elif k == "g":
            c.gradient_direction = "horizontal" if c.gradient_direction == "vertical" else "vertical"
            self.notify(f"gradient: {c.gradient_direction}")
        elif k == "o":
            order = ["bottom", "top", "mirror"]
            c.orientation = order[(order.index(c.orientation) + 1) % 3]
            self.notify(f"orientation: {c.orientation}")
        elif k == "s":
            c.channels = "stereo" if c.channels == "mono" else "mono"
            self.notify(f"channels: {c.channels}")
        elif k == "r":
            c.reverse = not c.reverse
            self.notify(f"reverse {'on' if c.reverse else 'off'}")
        elif k == "m":
            c.monstercat = 0.0 if c.monstercat else 1.5
            self.notify(f"monstercat {'on' if c.monstercat else 'off'}")
        elif key == "n":
            c.noise_reduction = min(c.noise_reduction + 5, 100)
            self.notify(f"noise reduction {c.noise_reduction}")
        elif key == "N":
            c.noise_reduction = max(c.noise_reduction - 5, 0)
            self.notify(f"noise reduction {c.noise_reduction}")
        elif k == "space":
            self.paused = not self.paused
        elif k == "f":
            c.show_fps = not c.show_fps
        elif k in ("h", "?"):
            self.show_help = not self.show_help

    def snapshot_config(self):
        return replace(self.cfg)
