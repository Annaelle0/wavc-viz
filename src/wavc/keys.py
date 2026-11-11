"""Non-blocking keyboard input (msvcrt on Windows, termios elsewhere)."""

from __future__ import annotations

import sys

_WIN_SPECIAL = {"H": "up", "P": "down", "K": "left", "M": "right"}
_POSIX_SPECIAL = {"A": "up", "B": "down", "D": "left", "C": "right"}


class KeyReader:
    """``poll()`` returns key names: single characters, 'up', 'down', 'left',
    'right', 'esc', 'space', 'ctrl-c'."""

    def __init__(self) -> None:
        self._old = None
        self._fd = None

    def __enter__(self) -> KeyReader:
        if sys.platform != "win32" and sys.stdin.isatty():
            import termios
            import tty

            self._fd = sys.stdin.fileno()
            self._old = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        return self

    def __exit__(self, *exc) -> None:
        if self._old is not None and self._fd is not None:
            import termios

            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)

    def poll(self) -> list[str]:
        keys: list[str] = []
        if sys.platform == "win32":
            import msvcrt

            try:
                while msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    if ch in ("\x00", "\xe0"):
                        code = msvcrt.getwch()
                        if code in _WIN_SPECIAL:
                            keys.append(_WIN_SPECIAL[code])
                    else:
                        keys.append(self._name(ch))
            except OSError:  # no console attached (CI, redirected stdin)
                pass
            return keys
        if self._fd is None:
            return keys
        import os
        import select

        # Read raw bytes: text-mode stdin buffers internally, which hides pending
        # input from select() and would swallow multi-byte escape sequences.
        while select.select([self._fd], [], [], 0)[0]:
            try:
                data = os.read(self._fd, 1024).decode("utf-8", "ignore")
            except OSError:
                break
            if not data:
                break
            keys.extend(self._parse(data))
        return keys

    def _parse(self, data: str) -> list[str]:
        keys: list[str] = []
        i = 0
        while i < len(data):
            ch = data[i]
            if ch != "\x1b":
                keys.append(self._name(ch))
                i += 1
                continue
            if i + 1 >= len(data):          # a lone ESC press
                keys.append("esc")
                break
            if data[i + 1] in "[O":         # CSI / SS3 sequence: params then final byte
                j = i + 2
                while j < len(data) and data[j] in "0123456789;":
                    j += 1
                if j < len(data):
                    if data[j] in _POSIX_SPECIAL:
                        keys.append(_POSIX_SPECIAL[data[j]])
                    j += 1
                i = j
            else:                           # Alt+key etc.: ignore
                i += 2
        return keys

    @staticmethod
    def _name(ch: str) -> str:
        if ch == "\x03":
            return "ctrl-c"
        if ch == "\x1b":
            return "esc"
        if ch == " ":
            return "space"
        return ch
