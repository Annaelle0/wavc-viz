# Changelog

## 1.0.0

Initial release.

- WASAPI loopback capture (what you hear), microphone/line-in, and a built-in demo source
- Multi-resolution FFT with log-spaced bands, treble tilt compensation and EQ curve
- CAVA-style smoothing: autosens, gravity/integral noise reduction, monstercat
- Terminal renderer: 1/8-cell block precision, bottom / top / mirror orientations,
  vertical and horizontal gradients, 10 themes, truecolor / 256 / no-color modes
- Native tkinter window: borderless, always-on-top, transparent desktop-widget mode
- Mono and stereo layouts, INI configuration, interactive key bindings
- Automatic recovery when the default output device changes
- Python 3.9 – 3.14 (test suite verified on every version)
