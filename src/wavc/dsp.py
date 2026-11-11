"""Audio analysis: multi-resolution FFT -> log-spaced bars -> CAVA-style smoothing.

Pipeline
--------
``Analyzer``   raw samples -> per-band level in dB (full-scale sine = 0 dB)
``Smoother``   autosens, monstercat, gravity + integral smoothing (ported from CAVA)
``Spectrum``   convenience wrapper tying both together, handles mono/stereo layout
"""

from __future__ import annotations

import numpy as np

# FFT window lengths. Low bands need long windows (frequency resolution), high
# bands use short ones (time resolution) - the same idea CAVA uses with 3 FFTs.
FFT_LONG = 8192
FFT_MID = 2048
FFT_SHORT = 1024
SILENCE_DB = -85.0


def band_edges(n: int, lower: float, upper: float) -> np.ndarray:
    """Geometrically spaced band edges (``n + 1`` values)."""
    return lower * (upper / lower) ** (np.arange(n + 1) / n)


class Analyzer:
    """Turns a stream of samples into per-band levels (dB)."""

    def __init__(
        self,
        rate: int,
        bands: int,
        lower: float = 50.0,
        upper: float = 10000.0,
        channels: int = 1,
        tilt_db: float = 2.0,
    ) -> None:
        if channels not in (1, 2):
            raise ValueError("channels must be 1 or 2")
        self.rate = int(rate)
        self.bands = int(bands)
        self.channels = channels
        upper = min(float(upper), self.rate / 2 * 0.98)
        lower = min(float(lower), upper / 2)
        self.edges = band_edges(self.bands, lower, upper)
        centers = np.sqrt(self.edges[:-1] * self.edges[1:])
        self.centers = centers
        self.weights = 10 ** (tilt_db * np.log2(centers / 1000.0) / 20.0)

        self._buf = np.zeros((channels, FFT_LONG), dtype=np.float64)
        self._windows = {n: np.hanning(n) for n in (FFT_LONG, FFT_MID, FFT_SHORT)}
        # Choose which FFT feeds which band (by center frequency).
        sizes = np.where(centers < 250, FFT_LONG, np.where(centers < 2500, FFT_MID, FFT_SHORT))
        self._groups: list[tuple[int, np.ndarray, dict]] = []
        for size in (FFT_LONG, FFT_MID, FFT_SHORT):
            idx = np.nonzero(sizes == size)[0]
            if idx.size:
                self._groups.append((size, idx, self._plan(size, idx)))

    # -- planning --------------------------------------------------------
    def _plan(self, size: int, idx: np.ndarray) -> dict:
        res = self.rate / size
        nbins = size // 2 + 1
        lo = np.clip(self.edges[idx] / res + 0.5, 0, nbins)
        hi = np.clip(self.edges[idx + 1] / res + 0.5, 0, nbins)
        wide = (hi - lo) >= 1.0
        centre = np.clip(self.centers[idx] / res, 0, nbins - 1.001)
        c0 = np.floor(centre).astype(int)
        return {
            "lo": lo, "hi": hi, "wide": wide,
            "c0": c0, "cf": centre - c0,
            "lo0": np.floor(lo).astype(int), "lof": lo - np.floor(lo),
            "hi0": np.minimum(np.floor(hi).astype(int), nbins - 1), "hif": hi - np.floor(hi),
            "norm": 2.0 / (size * float(np.sum(self._windows[size] ** 2))),
        }

    # -- API -------------------------------------------------------------
    def push(self, samples: np.ndarray) -> None:
        """Append samples of shape ``(n, ch)`` (or ``(n,)``) to the ring buffer."""
        x = np.asarray(samples, dtype=np.float64)
        if x.size == 0:
            return
        if x.ndim == 1:
            x = x[:, None]
        if self.channels == 1:
            x = x.mean(axis=1, keepdims=True)
        else:
            x = x[:, :2] if x.shape[1] >= 2 else np.repeat(x[:, :1], 2, axis=1)
        x = x.T  # (ch, n)
        n = x.shape[1]
        if n >= FFT_LONG:
            self._buf[:] = x[:, -FFT_LONG:]
        else:
            self._buf[:, :-n] = self._buf[:, n:]
            self._buf[:, -n:] = x

    def levels_db(self) -> np.ndarray:
        """Return ``(channels, bands)`` array of band levels in dB."""
        out = np.empty((self.channels, self.bands))
        for size, idx, p in self._groups:
            seg = self._buf[:, -size:] * self._windows[size]
            power = np.abs(np.fft.rfft(seg, axis=1)) ** 2 * p["norm"]  # (ch, bins)
            csum = np.concatenate(
                [np.zeros((self.channels, 1)), np.cumsum(power, axis=1)], axis=1
            )
            # energy inside fractional bin range [lo, hi] via the cumulative sum
            c_lo = csum[:, p["lo0"]] * (1 - p["lof"]) + csum[:, np.minimum(p["lo0"] + 1, csum.shape[1] - 1)] * p["lof"]
            c_hi = csum[:, p["hi0"]] * (1 - p["hif"]) + csum[:, np.minimum(p["hi0"] + 1, csum.shape[1] - 1)] * p["hif"]
            wide_power = np.maximum(c_hi - c_lo, 0.0)
            # bands narrower than one bin: interpolate the spectrum at the band centre
            narrow_power = power[:, p["c0"]] * (1 - p["cf"]) + power[:, p["c0"] + 1] * p["cf"]
            band_power = np.where(p["wide"], wide_power, narrow_power)
            out[:, idx] = band_power
        level = np.sqrt(2.0 * out) * self.weights  # amplitude, full-scale sine ~ 1.0
        return 20.0 * np.log10(level + 1e-9)


class Smoother:
    """CAVA-style autosens + monstercat + gravity/integral smoothing."""

    def __init__(
        self,
        bands: int,
        framerate: int = 60,
        noise_reduction: float = 0.77,
        monstercat: float = 0.0,
        autosens: bool = True,
        sensitivity: float = 100.0,
        scale: str = "sqrt",
        eq: np.ndarray | None = None,
    ) -> None:
        self.bands = bands
        self.framerate = framerate
        self.noise_reduction = float(np.clip(noise_reduction, 0.0, 1.0))
        self.monstercat = monstercat
        self.autosens = autosens
        self.sensitivity = sensitivity
        self.scale = scale
        self.gain_db = 0.0
        self._overshot = False
        self._peak = np.zeros(bands)
        self._fall = np.zeros(bands)
        self._prev = np.zeros(bands)
        self._mem = np.zeros(bands)
        self.eq = np.ones(bands)
        if eq is not None and len(eq) > 0:
            xs = np.linspace(0, 1, len(eq))
            self.eq = np.interp(np.linspace(0, 1, bands), xs, eq)
        if monstercat > 1:
            d = np.abs(np.arange(bands)[:, None] - np.arange(bands)[None, :])
            self._mc = 1.0 / (monstercat ** d)
        else:
            self._mc = None

    def reset(self) -> None:
        self._peak[:] = self._fall[:] = self._prev[:] = self._mem[:] = 0.0

    # -- level mapping ---------------------------------------------------
    def _to_unit(self, db: np.ndarray) -> np.ndarray:
        gain = self.gain_db if self.autosens else 20 * np.log10(max(self.sensitivity, 1) / 100.0)
        amp = 10 ** ((db + gain) / 20.0) * self.eq
        if self.scale == "log":
            v = (20 * np.log10(amp + 1e-9) + 50.0) / 50.0
        elif self.scale == "linear":
            v = amp
        else:
            v = np.sqrt(amp)
        return np.clip(v, 0.0, None)

    def process(self, db: np.ndarray, dt: float) -> np.ndarray:
        """Convert dB levels into smoothed bar heights in ``[0, 1]``."""
        silent = bool(db.max() < SILENCE_DB)
        v = self._to_unit(db)
        if silent:
            v = np.zeros_like(v)

        if self._mc is not None:
            v = (v[:, None] * self._mc).max(axis=0)

        out = self._gravity(v, dt)

        if self.autosens and not silent:
            f = dt * 60.0
            if out.max() > 1.0:
                self._overshot = True
                self.gain_db -= 0.3 * f
            else:
                self.gain_db += (0.01 if self._overshot else 0.8) * f
            self.gain_db = float(np.clip(self.gain_db, -60.0, 90.0))
        return np.clip(out, 0.0, 1.0)

    def _gravity(self, v: np.ndarray, dt: float) -> np.ndarray:
        nr = self.noise_reduction
        if nr <= 0.001:
            return v
        gravity_mod = (60.0 / max(1.0 / max(dt, 1e-3), 1.0)) ** 2.5 * 1.54 / max(nr, 0.1)
        falling = v < self._prev
        fall_val = np.maximum(self._peak * (1.0 - self._fall ** 2 * gravity_mod), 0.0)
        out = np.where(falling, np.maximum(fall_val, v), v)
        self._peak = np.where(falling, self._peak, v)
        self._fall = np.where(falling, self._fall + 0.028, 0.0)
        self._prev = out
        self._mem = self._mem * nr + out * (1.0 - nr)
        return self._mem.copy()


class Spectrum:
    """Samples in, bar heights out. Handles mono/stereo layout."""

    def __init__(
        self,
        rate: int,
        bars: int,
        *,
        channels: str = "mono",
        lower: float = 50.0,
        upper: float = 10000.0,
        framerate: int = 60,
        noise_reduction: int = 77,
        monstercat: float = 0.0,
        autosens: bool = True,
        sensitivity: float = 100.0,
        scale: str = "sqrt",
        tilt_db: float = 2.0,
        eq: list | None = None,
        reverse: bool = False,
    ) -> None:
        self.stereo = channels == "stereo" and bars >= 2
        self.bars = bars - (bars % 2) if self.stereo else bars
        self.reverse = reverse
        per = self.bars // 2 if self.stereo else self.bars
        self.rate = rate
        self.analyzer = Analyzer(rate, per, lower, upper, 2 if self.stereo else 1, tilt_db)
        self.smoother = Smoother(
            per * (2 if self.stereo else 1),
            framerate=framerate,
            noise_reduction=noise_reduction / 100.0,
            monstercat=monstercat,
            autosens=autosens,
            sensitivity=sensitivity,
            scale=scale,
            eq=np.asarray(eq, dtype=float) if eq else None,
        )
        if self.stereo and eq:
            # EQ applies per channel, so tile the curve across both halves
            curve = np.interp(np.linspace(0, 1, per), np.linspace(0, 1, len(eq)), eq)
            self.smoother.eq = np.concatenate([curve, curve])

    def push(self, samples: np.ndarray) -> None:
        self.analyzer.push(samples)

    def update(self, dt: float) -> np.ndarray:
        db = self.analyzer.levels_db()
        flat = db.reshape(-1)  # [L low..high, R low..high] or [mono low..high]
        v = self.smoother.process(flat, dt)
        if self.stereo:
            half = self.bars // 2
            v = np.concatenate([v[:half][::-1], v[half:]])  # bass in the centre
        if self.reverse:
            v = v[::-1]
        return v
