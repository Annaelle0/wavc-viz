# Contributing

Thanks for helping out! The project is small and easy to hack on.

```powershell
git clone https://github.com/Annaelle0/wavc-viz
cd wavc-viz
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest
ruff check .
```

Everything except the actual audio capture (`LoopbackSource` / `InputSource`) is unit-tested and
runs on Linux/macOS too, so you can work on the DSP and renderers anywhere. Use
`wavc --demo` to try changes without an audio device.

## Layout

| File | Purpose |
|------|---------|
| `dsp.py` | FFT analysis, band mapping, autosens, smoothing |
| `audio.py` | WASAPI loopback / input / demo sources and the silence-aware feeder |
| `render.py` | Terminal frame builder (block glyphs, gradients, orientations) |
| `gui.py` | tkinter window front-end |
| `session.py` | Shared state + key bindings for both front-ends |
| `config.py` | Defaults, INI schema, validation |
| `cli.py` | Argument parsing and entry point |

## Guidelines

- Add or update tests for behaviour changes; keep `ruff check .` clean.
- Keep the terminal path dependency-light (numpy + PyAudioWPatch only).
- Hardware-dependent code should degrade with a clear `AudioError`, never a traceback.
- If you change a config key, update `DEFAULT_CONFIG_TEXT`, the README table and `CHANGELOG.md`.
