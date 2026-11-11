import numpy as np
import pytest

from wavc.dsp import Analyzer, Smoother, Spectrum, band_edges

RATE = 48000


def tone(freq, amp=0.5, seconds=0.5, rate=RATE):
    t = np.arange(int(seconds * rate)) / rate
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_band_edges_are_geometric():
    e = band_edges(10, 50, 10000)
    assert e[0] == pytest.approx(50) and e[-1] == pytest.approx(10000)
    ratios = e[1:] / e[:-1]
    assert np.allclose(ratios, ratios[0])


@pytest.mark.parametrize("freq", [80, 440, 1000, 5000, 9000])
def test_tone_lands_in_correct_band_with_correct_level(freq):
    a = Analyzer(RATE, 60, 50, 10000, channels=1, tilt_db=0.0)
    a.push(tone(freq, amp=0.5))
    db = a.levels_db()[0]
    k = int(np.argmax(db))
    assert a.edges[k] * 0.8 <= freq <= a.edges[k + 1] * 1.25
    # amplitude 0.5 -> -6.02 dBFS (allow scalloping / band-edge splitting)
    assert -9.0 < db[k] < -5.0


def test_tilt_boosts_treble_relative_to_bass():
    flat = Analyzer(RATE, 30, tilt_db=0.0)
    tilted = Analyzer(RATE, 30, tilt_db=6.0)
    assert tilted.weights[-1] / tilted.weights[0] > flat.weights[-1] / flat.weights[0]
    assert np.isclose(flat.weights, 1.0).all()


def test_pink_noise_is_roughly_flat_across_log_bands():
    rng = np.random.default_rng(0)
    n = RATE * 4
    white = rng.standard_normal(n)
    spec = np.fft.rfft(white)
    f = np.fft.rfftfreq(n, 1 / RATE)
    f[0] = 1
    pink = np.fft.irfft(spec / np.sqrt(f), n)
    pink = (pink / np.abs(pink).max() * 0.5).astype(np.float32)
    a = Analyzer(RATE, 24, 100, 10000, tilt_db=0.0)
    a.push(pink)
    db = a.levels_db()[0]
    assert db.max() - db.min() < 9.0, db


def test_stereo_separates_channels():
    a = Analyzer(RATE, 40, channels=2, tilt_db=0.0)
    left = tone(300, 0.5)
    block = np.stack([left, np.zeros_like(left)], axis=1)
    a.push(block)
    db = a.levels_db()
    assert db[0].max() > db[1].max() + 40


def test_push_handles_short_and_huge_blocks():
    a = Analyzer(RATE, 20)
    a.push(np.zeros((0, 2)))
    a.push(np.ones(10))                     # 1-D input
    a.push(np.ones((100000, 2)) * 0.1)      # larger than the ring buffer
    assert np.isfinite(a.levels_db()).all()


def test_silence_yields_zero_bars():
    sp = Spectrum(RATE, 32)
    sp.push(np.zeros((4800, 2), dtype=np.float32))
    out = sp.update(1 / 60)
    assert np.all(out == 0)
    assert sp.smoother.gain_db == 0.0  # autosens must not run away on silence


def test_autosens_converges_and_stays_below_one():
    sp = Spectrum(RATE, 32)
    x = tone(1000, 0.05, seconds=3)
    peak = 0.0
    for i in range(0, 150):
        sp.push(x[i * 800 : (i + 1) * 800])
        v = sp.update(1 / 60)
        assert v.max() <= 1.0
        peak = v.max()
    assert 0.6 < peak <= 1.0


def test_manual_sensitivity_scales_output():
    def run(sens):
        sp = Spectrum(RATE, 32, autosens=False, sensitivity=sens, noise_reduction=0)
        x = tone(1000, 0.05, seconds=1)
        for i in range(30):
            sp.push(x[i * 800 : (i + 1) * 800])
            v = sp.update(1 / 60)
        return v.max()

    assert run(400) > run(100) > run(25)


def test_gravity_makes_bars_fall_gradually():
    sm = Smoother(4, noise_reduction=0.77, autosens=False)
    loud = np.full(4, -10.0)
    quiet = np.full(4, -120.0)
    for _ in range(30):
        top = sm.process(loud, 1 / 60)
    seq = [sm.process(quiet, 1 / 60)[0] for _ in range(40)]
    assert seq[0] > 0.3 * top[0]            # doesn't drop instantly
    assert all(a >= b - 1e-9 for a, b in zip(seq, seq[1:]))  # monotone fall
    assert seq[-1] < seq[0] * 0.5


def test_no_noise_reduction_is_passthrough():
    sm = Smoother(3, noise_reduction=0.0, autosens=False, sensitivity=100, scale="linear")
    out = sm.process(np.array([-20.0, -20.0, -20.0]), 1 / 60)
    assert np.allclose(out, 0.1, atol=1e-6)


def test_monstercat_spreads_peaks():
    base = Smoother(9, noise_reduction=0.0, autosens=False, scale="linear")
    mc = Smoother(9, noise_reduction=0.0, autosens=False, scale="linear", monstercat=1.5)
    db = np.full(9, -120.0)
    db[4] = -6.0
    a, b = base.process(db, 1 / 60), mc.process(db, 1 / 60)
    assert a[3] < 1e-3 and b[3] > 0.3 * b[4] and b[4] == pytest.approx(a[4])


def test_stereo_layout_puts_bass_in_the_middle_and_reverse_flips():
    x = np.stack([tone(100, 0.5), np.zeros(int(0.5 * RATE))], axis=1)

    def peak_index(**kw):
        sp = Spectrum(RATE, 20, channels="stereo", noise_reduction=0, **kw)
        sp.push(x)
        return int(np.argmax(sp.update(1 / 60))), sp

    idx, sp = peak_index()
    band = int(np.searchsorted(sp.analyzer.edges, 100) - 1)   # band holding 100 Hz
    assert idx == 9 - band              # left channel, bass nearest the centre
    assert idx < 10                     # ...and on the left half
    ridx, _ = peak_index(reverse=True)
    assert ridx == 19 - idx


def test_eq_curve_applies():
    sp = Spectrum(RATE, 16, eq=[1.0, 0.0], noise_reduction=0)
    assert sp.smoother.eq[0] == pytest.approx(1.0) and sp.smoother.eq[-1] == pytest.approx(0.0)


def test_low_sample_rate_does_not_break():
    a = Analyzer(8000, 16, 50, 10000)
    a.push(np.random.default_rng(1).standard_normal(8000) * 0.1)
    assert np.isfinite(a.levels_db()).all()
