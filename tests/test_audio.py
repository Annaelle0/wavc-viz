import numpy as np
import pytest

from wavc.audio import AudioError, AudioFeeder, AudioSource, DemoSource, create_source


class FakeSource(AudioSource):
    rate = 48000
    channels = 2
    name = "fake"

    def __init__(self):
        self.pending = []
        self.restarts = 0
        self.fail = False

    def start(self):
        pass

    def stop(self):
        pass

    def read(self):
        if self.pending:
            return self.pending.pop(0)
        return np.zeros((0, 2), dtype=np.float32)

    def restart(self):
        self.restarts += 1
        if self.fail:
            raise AudioError("boom")


def test_demo_source_produces_audio_and_is_finite():
    d = DemoSource()
    block = d.render(0, 44100)
    assert block.shape == (44100, 2) and np.isfinite(block).all()
    assert 0.01 < np.abs(block).max() < 1.5
    d.start()
    assert d.read().shape[1] == 2


def test_create_source_validation():
    assert isinstance(create_source("demo"), DemoSource)
    with pytest.raises(AudioError):
        create_source("bluetooth")


def test_feeder_passes_data_through():
    src = FakeSource()
    f = AudioFeeder(src)
    src.pending.append(np.ones((100, 2), dtype=np.float32))
    assert len(f.read(1 / 60)) == 100


def test_feeder_injects_silence_after_gap(monkeypatch):
    src = FakeSource()
    f = AudioFeeder(src, auto_restart=False)
    f._last_data -= 1.0
    out = f.read(1 / 50)
    assert out.shape == (960, 2) and not out.any()


def test_feeder_returns_nothing_for_tiny_gaps():
    f = AudioFeeder(FakeSource(), auto_restart=False)
    assert len(f.read(1 / 60)) == 0


def test_feeder_restarts_stalled_device_with_backoff():
    src = FakeSource()
    f = AudioFeeder(src)
    f._last_data -= 10
    f._next_restart = 0
    f.read(1 / 60)
    assert src.restarts == 1
    f.read(1 / 60)                       # backoff: no immediate second restart
    assert src.restarts == 1
    assert f._backoff > AudioFeeder.RESTART_AFTER


def test_feeder_survives_failed_restart():
    src = FakeSource()
    src.fail = True
    f = AudioFeeder(src)
    f._last_data -= 10
    f._next_restart = 0
    f.read(1 / 60)
    assert src.restarts == 1


def test_demo_source_never_auto_restarts():
    assert AudioFeeder(DemoSource()).auto_restart is False
