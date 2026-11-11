"""Configuration: defaults, INI file parsing, validation and CLI overrides."""

from __future__ import annotations

import configparser
import os
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from .colors import THEMES, parse_color, parse_gradient


class ConfigError(ValueError):
    """Raised for invalid configuration values."""


@dataclass
class Config:
    # [general]
    bars: int = 0                    # 0 = fit to terminal width
    framerate: int = 60
    autosens: bool = True
    sensitivity: int = 100           # percent, used when autosens is off
    lower_cutoff: int = 50
    upper_cutoff: int = 10000
    # [input]
    source: str = "loopback"         # loopback | input | demo
    device: str = ""                 # device name substring or index; "" = default
    # [output]
    method: str = "terminal"         # terminal | gui
    orientation: str = "bottom"      # bottom | top | mirror
    channels: str = "mono"           # mono | stereo
    bar_width: int = 2
    bar_spacing: int = 1
    align: str = "center"            # center | left
    reverse: bool = False
    charset: str = "blocks"          # blocks | ascii
    show_fps: bool = False
    # [color]
    theme: str = "aurora"
    gradient: list = field(default_factory=list)   # custom stops override theme
    gradient_direction: str = "vertical"           # vertical | horizontal
    background: str = "default"
    color_mode: str = "auto"         # auto | truecolor | 256 | none
    # [smoothing]
    noise_reduction: int = 77        # 0-100 (CAVA scale)
    monstercat: float = 0.0          # 0 = off, >1 = spread factor (1.5 typical)
    scale: str = "sqrt"              # log | sqrt | linear
    tilt: float = 2.0                # dB/octave treble boost
    eq: list = field(default_factory=list)
    # [gui]
    gui_width: int = 900
    gui_height: int = 320
    gui_borderless: bool = False
    gui_topmost: bool = False
    gui_transparent: bool = False

    # ---- helpers -------------------------------------------------------
    def validate(self) -> Config:
        def need(cond: bool, msg: str) -> None:
            if not cond:
                raise ConfigError(msg)

        def choice(name: str, allowed: tuple) -> None:
            need(getattr(self, name) in allowed, f"{name} must be one of {', '.join(allowed)}")

        need(0 <= self.bars <= 1000, "bars must be between 0 and 1000")
        need(10 <= self.framerate <= 240, "framerate must be between 10 and 240")
        need(1 <= self.sensitivity <= 10000, "sensitivity must be between 1 and 10000")
        need(10 <= self.lower_cutoff < self.upper_cutoff, "need 10 <= lower_cutoff < upper_cutoff")
        need(self.upper_cutoff <= 22000, "upper_cutoff must be <= 22000")
        need(1 <= self.bar_width <= 50, "bar_width must be between 1 and 50")
        need(0 <= self.bar_spacing <= 50, "bar_spacing must be between 0 and 50")
        need(0 <= self.noise_reduction <= 100, "noise_reduction must be between 0 and 100")
        need(self.monstercat == 0 or self.monstercat > 1, "monstercat must be 0 or greater than 1")
        need(-12 <= self.tilt <= 12, "tilt must be between -12 and 12")
        need(self.gui_width >= 100 and self.gui_height >= 60, "gui window too small")
        choice("method", ("terminal", "gui"))
        choice("orientation", ("bottom", "top", "mirror"))
        choice("channels", ("mono", "stereo"))
        choice("align", ("center", "left"))
        choice("charset", ("blocks", "ascii"))
        choice("gradient_direction", ("vertical", "horizontal"))
        choice("color_mode", ("auto", "truecolor", "256", "none"))
        choice("scale", ("log", "sqrt", "linear"))
        need(self.theme in THEMES, f"unknown theme {self.theme!r} (see --list-themes)")
        if self.gradient:
            try:
                parse_gradient(self.gradient)
            except ValueError as e:
                raise ConfigError(str(e)) from e
        if self.background != "default":
            try:
                parse_color(self.background)
            except ValueError as e:
                raise ConfigError(str(e)) from e
        need(all(w >= 0 for w in self.eq), "eq weights must be >= 0")
        return self

    def resolved_color_mode(self) -> str:
        if self.color_mode != "auto":
            return self.color_mode
        if os.environ.get("NO_COLOR"):
            return "none"
        if (
            os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")
            or os.environ.get("WT_SESSION")
            or sys.platform == "win32"
        ):
            return "truecolor"
        return "256"


# section, key, attribute, kind
_SCHEMA = [
    ("general", "bars", "bars", "int"),
    ("general", "framerate", "framerate", "int"),
    ("general", "autosens", "autosens", "bool"),
    ("general", "sensitivity", "sensitivity", "int"),
    ("general", "lower_cutoff_freq", "lower_cutoff", "int"),
    ("general", "higher_cutoff_freq", "upper_cutoff", "int"),
    ("input", "source", "source", "str"),
    ("input", "device", "device", "str"),
    ("output", "method", "method", "str"),
    ("output", "orientation", "orientation", "str"),
    ("output", "channels", "channels", "str"),
    ("output", "bar_width", "bar_width", "int"),
    ("output", "bar_spacing", "bar_spacing", "int"),
    ("output", "align", "align", "str"),
    ("output", "reverse", "reverse", "bool"),
    ("output", "charset", "charset", "str"),
    ("output", "show_fps", "show_fps", "bool"),
    ("color", "theme", "theme", "str"),
    ("color", "gradient", "gradient", "list"),
    ("color", "gradient_direction", "gradient_direction", "str"),
    ("color", "background", "background", "str"),
    ("color", "color_mode", "color_mode", "str"),
    ("smoothing", "noise_reduction", "noise_reduction", "int"),
    ("smoothing", "monstercat", "monstercat", "float"),
    ("smoothing", "scale", "scale", "str"),
    ("smoothing", "tilt", "tilt", "float"),
    ("eq", "eq", "eq", "floatlist"),
    ("gui", "width", "gui_width", "int"),
    ("gui", "height", "gui_height", "int"),
    ("gui", "borderless", "gui_borderless", "bool"),
    ("gui", "topmost", "gui_topmost", "bool"),
    ("gui", "transparent", "gui_transparent", "bool"),
]

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _convert(raw: str, kind: str, where: str) -> Any:
    s = raw.strip()
    try:
        if kind == "int":
            return int(float(s))
        if kind == "float":
            if s.lower() in _TRUE:
                return 1.5
            if s.lower() in _FALSE:
                return 0.0
            return float(s)
        if kind == "bool":
            if s.lower() in _TRUE:
                return True
            if s.lower() in _FALSE:
                return False
            raise ValueError("expected true/false")
        if kind == "list":
            return [p.strip() for p in s.replace(";", ",").split(",") if p.strip()]
        if kind == "floatlist":
            return [float(p) for p in s.replace(",", " ").split()]
        return s.lower() if where.split(".")[-1] not in ("device", "background") else s
    except ValueError as e:
        raise ConfigError(f"invalid value for [{where.replace('.', '] ')}: {raw!r} ({e})") from e


def default_config_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "wavc" / "config.ini"


def load_config(path: str | os.PathLike | None = None) -> Config:
    """Load a config. Explicit ``path`` must exist; the default path is optional."""
    cfg = Config()
    explicit = path is not None
    p = Path(path) if explicit else default_config_path()
    if not p.is_file():
        if explicit:
            raise ConfigError(f"config file not found: {p}")
        return cfg.validate()
    parser = configparser.ConfigParser(
        inline_comment_prefixes=(";",), comment_prefixes=("#", ";"), interpolation=None
    )
    try:
        parser.read(p, encoding="utf-8")
    except configparser.Error as e:
        raise ConfigError(f"could not parse {p}: {e}") from e
    for section, key, attr, kind in _SCHEMA:
        if parser.has_option(section, key):
            setattr(cfg, attr, _convert(parser.get(section, key), kind, f"{section}.{key}"))
    return cfg.validate()


def apply_overrides(cfg: Config, **overrides: Any) -> Config:
    """Apply non-None keyword overrides (e.g. from the CLI) and re-validate."""
    valid = {f.name for f in fields(Config)}
    for k, v in overrides.items():
        if v is None:
            continue
        if k not in valid:
            raise ConfigError(f"unknown option {k!r}")
        setattr(cfg, k, v)
    return cfg.validate()


DEFAULT_CONFIG_TEXT = """\
; wavc configuration
; Full-line comments start with '#' or ';'. Inline comments must use ';'
; (because '#' is used by hex colors).

[general]
; Number of bars. 0 = as many as fit in the terminal width.
bars = 0
framerate = 60
; Automatically adjust sensitivity so the loudest bar fills the screen.
autosens = true
; Manual sensitivity in percent (used when autosens = false).
sensitivity = 100
lower_cutoff_freq = 50
higher_cutoff_freq = 10000

[input]
; loopback = capture whatever you hear (WASAPI loopback of the default output)
; input    = capture a microphone / line-in
; demo     = built-in synthetic music, no audio device required
source = loopback
; Optional device name substring or index (see: wavc --list-devices).
device =

[output]
; terminal | gui
method = terminal
; bottom | top | mirror
orientation = bottom
; mono | stereo  (stereo: left channel on the left half, right on the right, bass in the middle)
channels = mono
bar_width = 2
bar_spacing = 1
; center | left
align = center
reverse = false
; blocks (smooth unicode) | ascii
charset = blocks
show_fps = false

[color]
; aurora classic fire ocean sunset matrix rainbow synthwave ice mono
theme = aurora
; Custom gradient (bottom -> top). Overrides theme when set. Example:
; gradient = #ff0080, #ffcc00, #ffffff
gradient =
; vertical = color depends on height, horizontal = color depends on bar position
gradient_direction = vertical
; default (terminal background) or a color such as #101018
background = default
; auto | truecolor | 256 | none
color_mode = auto

[smoothing]
; 0-100. Higher = smoother, slower bars (CAVA default is 77).
noise_reduction = 77
; 0 = off. Values > 1 (e.g. 1.5) spread peaks onto neighboring bars.
monstercat = 0
; log | sqrt | linear
scale = sqrt
; Treble boost in dB per octave, compensates music's natural spectral tilt.
tilt = 2.0

[eq]
; Per-frequency gain, interpolated across all bars (low -> high). Example: boost bass
; eq = 1.4 1.1 1 1 1

[gui]
width = 900
height = 320
borderless = false
topmost = false
; Make the window background see-through (Windows only).
transparent = false
"""


def write_default_config(path: str | os.PathLike | None = None, overwrite: bool = False) -> Path:
    p = Path(path) if path else default_config_path()
    if p.exists() and not overwrite:
        raise ConfigError(f"{p} already exists (use --force to overwrite)")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
    return p
