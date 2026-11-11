"""Audio sources.

* ``LoopbackSource``  - WASAPI loopback: captures what you hear (Windows only)
* ``InputSource``     - microphone / line-in via PortAudio (Windows only)
* ``DemoSource``      - synthetic music, works anywhere (great for testing/themes)

``AudioFeeder`` wraps a source and handles two real-world quirks:

* WASAPI loopback delivers *no packets at all* while nothing is playing, so the
  feeder injects silence after a short gap.
* The default output device can change at runtime (headphones plugged in...),
  so a stalled source is periodically re-opened.
"""

from __future__ import annotations

import collections
import threading
import time
from abc import ABC, abstractmethod

import numpy as np


class AudioError(RuntimeError):
    """Raised when an audio device cannot be opened."""


class AudioSource(ABC):
    rate: int = 44100
    channels: int = 2
    name: str = "audio"

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def read(self) -> np.ndarray:
        """Return all samples captured since the last call, shape ``(n, channels)``."""

    def restart(self) -> None:
        self.stop()
        self.start()


# --------------------------------------------------------------------------
# Demo source
# --------------------------------------------------------------------------
class DemoSource(AudioSource):
    """Synthetic 'music': kick drum, hats, bass line, arpeggio and a slow sweep."""

    name = "demo (synthetic)"

    def __init__(self, rate: int = 44100) -> None:
        self.rate = rate
        self.channels = 2
        self._t0 = 0.0
        self._last = 0
        self._noise = np.random.default_rng(1)

    def start(self) -> None:
        self._t0 = time.perf_counter()
        self._last = 0

    def stop(self) -> None:
        pass

    def read(self) -> np.ndarray:
        now = int((time.perf_counter() - self._t0) * self.rate)
        n = now - self._last
        if n <= 0:
            return np.zeros((0, 2), dtype=np.float32)
        n = min(n, self.rate)  # never produce more than a second at once
        out = self.render(self._last, n)
        self._last = now
        return out

    def render(self, start: int, n: int) -> np.ndarray:
        """Synthesize samples ``[start, start+n)`` (hi-hat noise aside, a pure function of time)."""
        t = (np.arange(start, start + n)) / self.rate
        beat = 0.5  # 120 BPM
        ph = np.mod(t, beat)
        kick = 0.9 * np.sin(2 * np.pi * (55 * ph + 80 * (1 - np.exp(-35 * ph)) / 35)) * np.exp(-ph * 8)
        hat_env = np.exp(-np.mod(t + beat / 2, beat) * 60)
        hat = self._noise.standard_normal(n) * hat_env * 0.12
        notes = np.array([55.0, 55.0, 65.41, 49.0])  # bass line, 1 note per bar
        bar_idx = (t / (4 * beat)).astype(int) % len(notes)
        bass = 0.35 * np.sin(2 * np.pi * notes[bar_idx] * t)
        arp_notes = np.array([261.63, 329.63, 392.0, 523.25, 659.25, 523.25, 392.0, 329.63])
        step = (t / (beat / 2)).astype(int) % len(arp_notes)
        arp_env = np.exp(-np.mod(t, beat / 2) * 6)
        arp = 0.18 * np.sin(2 * np.pi * arp_notes[step] * t) * arp_env
        sweep = 0.06 * np.sin(2 * np.pi * (300 + 2500 * (0.5 + 0.5 * np.sin(t * 0.4))) * t)
        mono = kick + hat + bass + arp + sweep
        pan = 0.5 + 0.35 * np.sin(t * 1.3)
        left = mono * (1 - pan) * 1.4 + arp * 0.5
        right = mono * pan * 1.4 + sweep * 0.5
        return (np.stack([left, right], axis=1) * 0.5).astype(np.float32)


# --------------------------------------------------------------------------
# PortAudio-backed sources (Windows)
# --------------------------------------------------------------------------
def _import_pyaudio():
    try:
        import pyaudiowpatch as pyaudio  # type: ignore
    except ImportError as e:  # pragma: no cover - depends on platform
        raise AudioError(
            "PyAudioWPatch is not installed (it is only available on Windows).\n"
            "Install it with:  pip install PyAudioWPatch\n"
            "Tip: run with --demo to try the visualiser without an audio device."
        ) from e
    return pyaudio


class _PortAudioSource(AudioSource):
    _MAX_BUFFER_SECONDS = 1.0

    def __init__(self, device: str = "") -> None:
        self.device = device.strip()
        self._pa = None
        self._stream = None
        self._queue: collections.deque = collections.deque()
        self._queued = 0
        self._lock = threading.Lock()
        self.last_data = 0.0
        self._continue = 0  # pyaudio.paContinue, set in start()

    # subclasses implement
    def _pick_device(self, pa, pyaudio) -> dict:  # pragma: no cover
        raise NotImplementedError

    def start(self) -> None:  # pragma: no cover - needs hardware
        pyaudio = _import_pyaudio()
        self._continue = pyaudio.paContinue
        self._pa = pyaudio.PyAudio()
        try:
            info = self._pick_device(self._pa, pyaudio)
            self.name = info["name"]
            self.rate = int(info["defaultSampleRate"])
            self.channels = max(1, min(int(info["maxInputChannels"]), 8))
            self._stream = self._pa.open(
                format=pyaudio.paFloat32,
                channels=self.channels,
                rate=self.rate,
                frames_per_buffer=max(256, self.rate // 100),
                input=True,
                input_device_index=info["index"],
                stream_callback=self._callback,
            )
            self._stream.start_stream()
        except AudioError:
            self._terminate()
            raise
        except Exception as e:
            self._terminate()
            raise AudioError(f"could not open audio device: {e}") from e

    def _callback(self, in_data, frame_count, time_info, status):  # pragma: no cover
        arr = np.frombuffer(in_data, dtype=np.float32).reshape(-1, self.channels).copy()
        with self._lock:
            self._queue.append(arr)
            self._queued += len(arr)
            limit = int(self.rate * self._MAX_BUFFER_SECONDS)
            while self._queued > limit and len(self._queue) > 1:
                self._queued -= len(self._queue.popleft())
        self.last_data = time.perf_counter()
        return (None, self._continue)

    def read(self) -> np.ndarray:
        with self._lock:
            if not self._queue:
                return np.zeros((0, self.channels), dtype=np.float32)
            data = np.concatenate(list(self._queue), axis=0)
            self._queue.clear()
            self._queued = 0
        return data

    def _terminate(self) -> None:
        try:
            if self._stream is not None:
                try:
                    self._stream.stop_stream()
                finally:
                    self._stream.close()
        except Exception:
            pass
        self._stream = None
        try:
            if self._pa is not None:
                self._pa.terminate()
        except Exception:
            pass
        self._pa = None

    def stop(self) -> None:
        self._terminate()


def _match(device: str, info: dict) -> bool:
    if not device:
        return True
    if device.isdigit():
        return int(device) == info["index"]
    return device.lower() in info["name"].lower()


class LoopbackSource(_PortAudioSource):
    """Capture the system mix via WASAPI loopback."""

    def _pick_device(self, pa, pyaudio) -> dict:  # pragma: no cover - needs hardware
        try:
            wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError as e:
            raise AudioError("WASAPI is not available on this system") from e
        loopbacks = list(pa.get_loopback_device_info_generator())
        if not loopbacks:
            raise AudioError("no WASAPI loopback devices found (is an output device enabled?)")
        if self.device:
            for lb in loopbacks:
                if _match(self.device, lb):
                    return lb
            names = ", ".join(lb["name"] for lb in loopbacks)
            raise AudioError(f"no loopback device matching {self.device!r}. Available: {names}")
        default_out = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
        for lb in loopbacks:
            if default_out["name"] in lb["name"]:
                return lb
        return loopbacks[0]


class InputSource(_PortAudioSource):
    """Capture a microphone or line-in device."""

    def _pick_device(self, pa, pyaudio) -> dict:  # pragma: no cover - needs hardware
        if not self.device:
            try:
                return pa.get_default_input_device_info()
            except OSError as e:
                raise AudioError("no default input device available") from e
        for info in _input_devices(pa, pyaudio):
            if _match(self.device, info):
                return info
        raise AudioError(f"no input device matching {self.device!r} (see --list-devices)")


def _input_devices(pa, pyaudio) -> list[dict]:  # pragma: no cover - needs hardware
    try:
        wasapi_idx = pa.get_host_api_info_by_type(pyaudio.paWASAPI)["index"]
    except OSError:
        wasapi_idx = None
    out = []
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if info["maxInputChannels"] > 0 and not info.get("isLoopbackDevice", False):
            if wasapi_idx is None or info["hostApi"] == wasapi_idx:
                out.append(info)
    return out


def list_devices() -> dict[str, list[dict]]:  # pragma: no cover - needs hardware
    """Return ``{"loopback": [...], "input": [...]}`` device info dicts."""
    pyaudio = _import_pyaudio()
    pa = pyaudio.PyAudio()
    try:
        loop = list(pa.get_loopback_device_info_generator())
        return {"loopback": loop, "input": _input_devices(pa, pyaudio)}
    finally:
        pa.terminate()


def create_source(kind: str, device: str = "") -> AudioSource:
    kind = kind.lower()
    if kind == "demo":
        return DemoSource()
    if kind == "loopback":
        return LoopbackSource(device)
    if kind == "input":
        return InputSource(device)
    raise AudioError(f"unknown source {kind!r} (use loopback, input or demo)")


# --------------------------------------------------------------------------
# Feeder
# --------------------------------------------------------------------------
class AudioFeeder:
    """Gives the render loop a steady sample stream, silence-filled when idle."""

    GAP_BEFORE_SILENCE = 0.08   # seconds without packets before injecting zeros
    RESTART_AFTER = 4.0         # seconds of stall before trying to reopen the device
    MAX_RESTART_INTERVAL = 15.0

    def __init__(self, source: AudioSource, auto_restart: bool = True) -> None:
        self.source = source
        self.auto_restart = auto_restart and not isinstance(source, DemoSource)
        self._last_data = time.perf_counter()
        self._next_restart = self._last_data + self.RESTART_AFTER
        self._backoff = self.RESTART_AFTER
        self.rate_changed = False

    def start(self) -> None:
        self.source.start()
        self._last_data = time.perf_counter()

    def stop(self) -> None:
        self.source.stop()

    @property
    def rate(self) -> int:
        return self.source.rate

    def read(self, dt: float) -> np.ndarray:
        now = time.perf_counter()
        data = self.source.read()
        if len(data):
            self._last_data = now
            self._backoff = self.RESTART_AFTER
            self._next_restart = now + self.RESTART_AFTER
            return data
        gap = now - self._last_data
        if gap > self.GAP_BEFORE_SILENCE:
            if self.auto_restart and now >= self._next_restart:
                self._try_restart(now)
            n = max(1, int(dt * self.source.rate))
            return np.zeros((n, self.source.channels), dtype=np.float32)
        return data

    def _try_restart(self, now: float) -> None:
        old_rate = self.source.rate
        try:
            self.source.restart()
            if self.source.rate != old_rate:
                self.rate_changed = True
        except AudioError:
            pass
        self._backoff = min(self._backoff * 2, self.MAX_RESTART_INTERVAL)
        self._next_restart = now + self._backoff
