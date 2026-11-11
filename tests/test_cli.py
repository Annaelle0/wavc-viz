import pytest

from wavc import __version__
from wavc.cli import main


def test_version(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_list_themes(capsys):
    assert main(["--list-themes"]) == 0
    assert "aurora" in capsys.readouterr().out


def test_init_config(tmp_path, capsys):
    p = tmp_path / "x.ini"
    assert main(["--init-config", str(p)]) == 0
    assert p.exists()
    assert main(["--init-config", str(p)]) == 1          # refuses to overwrite
    assert main(["--init-config", str(p), "--force"]) == 0


def test_bad_config_reports_error(tmp_path, capsys):
    p = tmp_path / "bad.ini"
    p.write_text("[general]\nbars = nope\n")
    assert main(["-c", str(p), "--demo"]) == 2
    assert "error" in capsys.readouterr().err


def test_bad_override(capsys):
    assert main(["--demo", "--bars", "-3"]) == 2


def test_demo_runs_headless_for_a_few_frames(capsys):
    # stdout is captured (not a tty) but --frames lets us exercise the real loop
    assert main(["--demo", "--frames", "5", "--fps", "240"]) == 0
