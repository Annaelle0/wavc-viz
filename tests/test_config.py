import pytest

from wavc.colors import build_gradient, parse_color, parse_gradient
from wavc.config import (
    Config,
    ConfigError,
    apply_overrides,
    load_config,
    write_default_config,
)


def test_defaults_validate():
    Config().validate()


def test_default_file_round_trips(tmp_path):
    p = write_default_config(tmp_path / "c.ini")
    cfg = load_config(p)
    assert cfg == Config().validate()


def test_refuses_to_overwrite(tmp_path):
    p = write_default_config(tmp_path / "c.ini")
    with pytest.raises(ConfigError):
        write_default_config(p)
    write_default_config(p, overwrite=True)


def test_values_parsed_with_inline_comments_and_hex_colors(tmp_path):
    p = tmp_path / "c.ini"
    p.write_text(
        "[general]\nbars = 48 ; inline comment\nautosens = no\n"
        "[color]\ngradient = #ff0000, #00ff00 ; two stops\nbackground = #101018\n"
        "[smoothing]\nmonstercat = true\n[eq]\neq = 1 2.5 1\n"
    )
    cfg = load_config(p)
    assert cfg.bars == 48 and cfg.autosens is False
    assert cfg.gradient == ["#ff0000", "#00ff00"]
    assert cfg.background == "#101018"
    assert cfg.monstercat == 1.5
    assert cfg.eq == [1.0, 2.5, 1.0]


@pytest.mark.parametrize(
    "text",
    [
        "[general]\nbars = abc\n",
        "[general]\nframerate = 5\n",
        "[output]\norientation = sideways\n",
        "[color]\ntheme = nope\n",
        "[color]\ngradient = notacolor\n",
        "[general]\nlower_cutoff_freq = 9000\nhigher_cutoff_freq = 100\n",
    ],
)
def test_invalid_values_raise(tmp_path, text):
    p = tmp_path / "c.ini"
    p.write_text(text)
    with pytest.raises(ConfigError):
        load_config(p)


def test_missing_explicit_config_is_an_error(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "missing.ini")


def test_overrides_skip_none_and_validate():
    cfg = apply_overrides(Config(), bars=None, theme="fire")
    assert cfg.theme == "fire"
    with pytest.raises(ConfigError):
        apply_overrides(Config(), bars=-5)


def test_color_parsing():
    assert parse_color("#fff") == (255, 255, 255)
    assert parse_color("FF8000") == (255, 128, 0)
    assert parse_color("red") == (255, 0, 0)
    with pytest.raises(ValueError):
        parse_color("#12")
    with pytest.raises(ValueError):
        parse_gradient([])


def test_gradient_interpolation():
    g = build_gradient([(0, 0, 0), (255, 255, 255)], 5)
    assert g.shape == (5, 3) and tuple(g[0]) == (0, 0, 0) and tuple(g[-1]) == (255, 255, 255)
    assert build_gradient([(1, 2, 3)], 4).shape == (4, 3)
    assert build_gradient([(1, 2, 3), (4, 5, 6)], 1).shape == (1, 3)


def test_all_example_configs_load():
    from pathlib import Path

    examples = sorted((Path(__file__).resolve().parents[1] / "examples").glob("*.ini"))
    assert len(examples) >= 3
    for path in examples:
        load_config(path)
