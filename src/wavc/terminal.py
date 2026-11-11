"""Terminal setup/teardown: VT sequences, alt screen, UTF-8, timer resolution."""

from __future__ import annotations

import os
import shutil
import sys

ALT_ON = "\x1b[?1049h"
ALT_OFF = "\x1b[?1049l"
HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"
WRAP_OFF = "\x1b[?7l"
WRAP_ON = "\x1b[?7h"
RESET = "\x1b[0m"
CLEAR = "\x1b[2J"


def enable_windows_vt() -> bool:
    """Turn on ANSI escape processing for the Windows console. Returns success."""
    if sys.platform != "win32":
        return True
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel32.GetStdHandle.restype = wintypes.HANDLE
    kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetConsoleMode.restype = wintypes.BOOL
    kernel32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.SetConsoleMode.restype = wintypes.BOOL

    invalid = ctypes.c_void_p(-1).value
    ok = True
    for std in (-11, -12):  # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
        handle = kernel32.GetStdHandle(std & 0xFFFFFFFF)
        if not handle or handle == invalid:
            continue
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            continue  # not a console (redirected) - nothing to do
        # ENABLE_PROCESSED_OUTPUT | ENABLE_VIRTUAL_TERMINAL_PROCESSING
        if not kernel32.SetConsoleMode(handle, mode.value | 0x0001 | 0x0004):
            ok = False
    try:
        kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass
    return ok


def set_timer_resolution(ms: int = 1) -> None:
    """Ask Windows for ~1 ms sleep granularity (default is ~15.6 ms)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.winmm.timeBeginPeriod(ms)  # type: ignore[attr-defined]
    except Exception:
        pass


def restore_timer_resolution(ms: int = 1) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.winmm.timeEndPeriod(ms)  # type: ignore[attr-defined]
    except Exception:
        pass


def ensure_utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass


class Terminal:
    """Context manager owning the full-screen terminal session."""

    def __init__(self) -> None:
        self._active = False

    def __enter__(self) -> Terminal:
        ensure_utf8_stdout()
        enable_windows_vt()
        set_timer_resolution(1)
        self.write(ALT_ON + HIDE_CURSOR + WRAP_OFF + RESET + CLEAR)
        self._active = True
        return self

    def __exit__(self, *exc) -> None:
        if self._active:
            self.write(RESET + WRAP_ON + SHOW_CURSOR + ALT_OFF)
            restore_timer_resolution(1)
            self._active = False

    @staticmethod
    def size() -> tuple[int, int]:
        try:
            sz = os.get_terminal_size()
            return max(sz.columns, 1), max(sz.lines, 1)
        except OSError:
            sz = shutil.get_terminal_size((80, 24))
            return sz.columns, sz.lines

    @staticmethod
    def write(text: str) -> None:
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
        except (BrokenPipeError, OSError):
            pass

    def clear(self) -> None:
        self.write(RESET + CLEAR)
