"""Main loops: terminal front-end (the gui front-end lives in gui.py)."""

from __future__ import annotations

import time

from .audio import AudioSource
from .keys import KeyReader
from .render import TerminalRenderer
from .session import Session
from .terminal import Terminal


def run_terminal(cfg, source: AudioSource, max_frames: int | None = None) -> None:
    """Run the full-screen terminal visualiser until the user quits."""
    session = Session(cfg, source)
    session.start()
    renderer = TerminalRenderer(cfg)
    frame = 0
    try:
        with Terminal() as term, KeyReader() as keys:
            last = time.perf_counter()
            last_size = (0, 0)
            while not session.quit:
                target = 1.0 / cfg.framerate
                now = time.perf_counter()
                dt = max(now - last, 1e-4)
                last = now

                cols, rows = term.size()
                if (cols, rows) != last_size:
                    term.clear()
                    last_size = (cols, rows)
                bars = renderer.bars_for_width(cols)
                values = session.step(min(dt, 0.25), bars)
                term.write(renderer.render(values, cols, rows, session.overlay()))

                for k in keys.poll():
                    session.on_key(k)

                frame += 1
                if max_frames is not None and frame >= max_frames:
                    break
                spare = target - (time.perf_counter() - now)
                if spare > 0:
                    time.sleep(spare)
    except KeyboardInterrupt:
        pass
    finally:
        session.stop()
