"""Command line interface."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .audio import AudioError, create_source, list_devices
from .colors import THEMES, parse_gradient, to_hex
from .config import (
    ConfigError,
    apply_overrides,
    default_config_path,
    load_config,
    write_default_config,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wavc",
        description="CAVA-style audio spectrum visualiser for Windows (WASAPI loopback).",
        epilog=f"Default config: {default_config_path()}",
    )
    p.add_argument("-c", "--config", metavar="FILE", help="path to a config file")
    p.add_argument("-s", "--source", choices=["loopback", "input", "demo"],
                   help="audio source (default: loopback)")
    p.add_argument("--demo", action="store_true", help="shortcut for --source demo")
    p.add_argument("-d", "--device", metavar="NAME|INDEX", help="device name substring or index")
    p.add_argument("-b", "--bars", type=int, metavar="N", help="number of bars (0 = auto-fit)")
    p.add_argument("-t", "--theme", help="color theme (see --list-themes)")
    p.add_argument("--gradient", metavar="C1,C2,...", help="custom gradient, e.g. '#f0f,#0ff'")
    p.add_argument("-o", "--orientation", choices=["bottom", "top", "mirror"])
    p.add_argument("--stereo", action="store_true", help="show left/right channels separately")
    p.add_argument("--gui", action="store_true", help="open a native window instead of the terminal")
    p.add_argument("--fps", type=int, metavar="N", help="target framerate")
    p.add_argument("--bar-width", type=int, metavar="N")
    p.add_argument("--bar-spacing", type=int, metavar="N")
    p.add_argument("--no-autosens", action="store_true", help="disable automatic sensitivity")
    p.add_argument("--sensitivity", type=int, metavar="PCT", help="manual sensitivity in percent")
    p.add_argument("--noise-reduction", type=int, metavar="0-100")
    p.add_argument("--monstercat", action="store_true", help="enable monstercat smoothing")
    p.add_argument("--ascii", action="store_true", help="plain ASCII glyphs instead of blocks")
    p.add_argument("--list-devices", action="store_true", help="list audio devices and exit")
    p.add_argument("--list-themes", action="store_true", help="list color themes and exit")
    p.add_argument("--init-config", nargs="?", const="", metavar="PATH",
                   help="write a commented default config (to PATH or the default location)")
    p.add_argument("--force", action="store_true", help="overwrite when used with --init-config")
    p.add_argument("--frames", type=int, metavar="N", help=argparse.SUPPRESS)  # for tests/CI
    p.add_argument("-V", "--version", action="version", version=f"wavc {__version__}")
    return p


def _print_devices() -> int:
    try:
        devs = list_devices()
    except AudioError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print("Loopback devices (source = loopback)  - capture what you hear:")
    for d in devs["loopback"] or []:
        print(f"  [{d['index']:>3}] {d['name']}  ({int(d['defaultSampleRate'])} Hz, {d['maxInputChannels']} ch)")
    if not devs["loopback"]:
        print("  (none found)")
    print("\nInput devices (source = input)  - microphones / line-in:")
    for d in devs["input"] or []:
        print(f"  [{d['index']:>3}] {d['name']}  ({int(d['defaultSampleRate'])} Hz, {d['maxInputChannels']} ch)")
    if not devs["input"]:
        print("  (none found)")
    print("\nUse -d <index or part of name> to pick one.")
    return 0


def _print_themes() -> None:
    for name, stops in THEMES.items():
        rgb = parse_gradient(stops)
        swatch = "".join(f"\x1b[48;2;{r};{g};{b}m  " for r, g, b in rgb) + "\x1b[0m"
        print(f"  {name:<10} {swatch}  {' '.join(to_hex(c) for c in rgb)}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_themes:
        from .terminal import enable_windows_vt

        enable_windows_vt()
        _print_themes()
        return 0
    if args.list_devices:
        return _print_devices()
    if args.init_config is not None:
        try:
            path = write_default_config(args.init_config or None, overwrite=args.force)
        except (ConfigError, OSError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"Wrote {path}")
        return 0

    try:
        cfg = load_config(args.config)
        apply_overrides(
            cfg,
            source="demo" if args.demo else args.source,
            device=args.device,
            bars=args.bars,
            theme=args.theme.lower() if args.theme else None,
            gradient=[g.strip() for g in args.gradient.split(",")] if args.gradient else None,
            orientation=args.orientation,
            channels="stereo" if args.stereo else None,
            method="gui" if args.gui else None,
            framerate=args.fps,
            bar_width=args.bar_width,
            bar_spacing=args.bar_spacing,
            autosens=False if args.no_autosens else None,
            sensitivity=args.sensitivity,
            noise_reduction=args.noise_reduction,
            monstercat=1.5 if args.monstercat else None,
            charset="ascii" if args.ascii else None,
        )
        source = create_source(cfg.source, cfg.device)
    except (ConfigError, AudioError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    try:
        if cfg.method == "gui":
            from .gui import run_gui

            run_gui(cfg, source, max_frames=args.frames)
        else:
            from .app import run_terminal

            if not sys.stdout.isatty() and args.frames is None:
                print("error: stdout is not a terminal (use --gui, or run in Windows Terminal)",
                      file=sys.stderr)
                return 2
            run_terminal(cfg, source, max_frames=args.frames)
    except AudioError as e:
        print(f"\nerror: {e}", file=sys.stderr)
        if cfg.source == "loopback":
            print("Hint: try `wavc --list-devices`, or `wavc --demo` to test without audio.",
                  file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
