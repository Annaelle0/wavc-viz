"""The README must not point at images or videos that are missing from the repo."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_docs_file_linked_from_readme_exists():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    refs = {a or b for a, b in re.findall(r'(?:src|href)="(docs/[^"]+)"|\]\((docs/[^)]+)\)', text)}
    assert len(refs) >= 10
    missing = sorted(r for r in refs if not (ROOT / r).is_file())
    assert not missing, missing


def test_demo_media_is_small_enough_for_a_repo():
    for name, limit_mb in (("demo.gif", 8), ("demo.mp4", 8)):
        assert (ROOT / "docs" / name).stat().st_size < limit_mb * 1024 * 1024
