"""Tests for the doc-freshness gate (scripts/check_doc_freshness.py)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_doc_freshness import check


def write_tree(root: Path, *, missing_class: bool = False) -> None:
    (root / "app.py").write_text(
        "class PocketTTSService:\n    pass\n"
        "class App:\n    pass\n"
        "class InternalHelper:\n    pass\n",
        encoding="utf-8",
    )
    (root / "dubbing").mkdir(exist_ok=True)
    (root / "dubbing" / "__init__.py").write_text("", encoding="utf-8")
    (root / "dubbing" / "ui_wizard.py").write_text(
        "class DubbingWizard:\n    pass\n", encoding="utf-8"
    )
    agents = "PocketTTSService App dubbing DubbingWizard TextChunk AudioPlayer"
    if missing_class:
        agents = agents.replace("PocketTTSService ", "")
    (root / "AGENTS.md").write_text(agents, encoding="utf-8")
    (root / "CLAUDE.md").write_text("pointer overlay", encoding="utf-8")


def test_clean_tree_passes(tmp_path: Path) -> None:
    write_tree(tmp_path)
    assert check(tmp_path) == []


def test_missing_class_fails(tmp_path: Path) -> None:
    write_tree(tmp_path, missing_class=True)
    errors = check(tmp_path)
    assert any("PocketTTSService" in e for e in errors)


def test_missing_package_fails(tmp_path: Path) -> None:
    write_tree(tmp_path)
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "__init__.py").write_text("", encoding="utf-8")
    errors = check(tmp_path)
    assert any("extra/" in e for e in errors)


def test_real_tree_passes() -> None:
    root = Path(__file__).resolve().parent.parent
    assert check(root) == []


def test_missing_doc_file_fails(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("class App:\n    pass\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("App", encoding="utf-8")
    errors = check(tmp_path)
    assert any("CLAUDE.md" in e for e in errors)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
