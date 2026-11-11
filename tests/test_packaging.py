import re
from pathlib import Path

PYPROJECT = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")


def test_distribution_name_and_both_commands():
    assert re.search(r'^name = "wavc-viz"$', PYPROJECT, re.M)
    assert re.search(r'^wavc = "wavc\.cli:main"$', PYPROJECT, re.M)
    assert re.search(r'^wavc-viz = "wavc\.cli:main"$', PYPROJECT, re.M)


def test_urls_point_at_the_renamed_repo_and_have_no_placeholder():
    assert "YOUR_USERNAME" not in PYPROJECT
    urls = re.findall(r"https://github\.com/([^/\s\"]+)/([^/\s\"]+)", PYPROJECT)
    own = [(u, r) for u, r in urls if r.startswith("wavc")]
    assert own and all(r.startswith("wavc-viz") for _, r in own)
