"""Fail-closed doc-freshness gate for AGENTS.md / CLAUDE.md.

Checks that the architecture docs name every user-facing engine/service /
wizard class and every root-level package, so the docs cannot silently rot
the way "no module split, no test suite" did. Run from .githooks/pre-commit;
also runnable standalone: .venv/bin/python scripts/check_doc_freshness.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

CLASS_DEF = re.compile(r"^class (\w+)", re.MULTILINE)
# User-facing roster: services / wizards / dialogs / coordinators by suffix,
# plus the handful of core classes the docs promise by name.
SUFFIXES = ("Service", "Wizard", "Dialog", "Coordinator")
ALWAYS = {"App", "AudioPlayer", "TextChunk"}
# Classes defined outside app.py that the docs must also name: module -> names.
EXTRA_MODULES = {"dubbing/ui_wizard.py": ("DubbingWizard",)}
DOCS = ("AGENTS.md", "CLAUDE.md")


def roster(root: Path) -> list[tuple[str, str]]:
    """Return [(class_name, defining_file)] for every documented-surface class."""
    found: list[tuple[str, str]] = []
    app = root / "app.py"
    for name in CLASS_DEF.findall(app.read_text(encoding="utf-8")):
        if name.endswith(SUFFIXES) or name in ALWAYS:
            found.append((name, "app.py"))
    for rel, names in EXTRA_MODULES.items():
        mod = root / rel
        if not mod.exists():
            continue
        text = mod.read_text(encoding="utf-8")
        for name in names:
            if re.search(rf"^class {name}\b", text, re.MULTILINE):
                found.append((name, rel))
    return found


def packages(root: Path) -> list[str]:
    """Return root-level dirs that are importable packages (have __init__.py)."""
    return sorted(
        p.name + "/"
        for p in root.iterdir()
        if p.is_dir()
        and not p.name.startswith(".")
        and (p / "__init__.py").exists()
    )


def check(root: Path) -> list[str]:
    """Return a list of drift messages; empty means docs are fresh."""
    errors: list[str] = []
    docs_text = ""
    for doc in DOCS:
        path = root / doc
        if not path.exists():
            errors.append(f"DOC DRIFT: {doc} is missing")
        else:
            docs_text += path.read_text(encoding="utf-8") + "\n"
    for name, defining in roster(root):
        if name not in docs_text:
            errors.append(
                f"DOC DRIFT: class {name} (defined in {defining}) is not "
                f"named in AGENTS.md/CLAUDE.md — update the docs"
            )
    agents = (root / "AGENTS.md").read_text(encoding="utf-8") if (root / "AGENTS.md").exists() else ""
    for pkg in packages(root):
        if pkg.rstrip("/") not in agents and pkg not in agents:
            errors.append(
                f"DOC DRIFT: package {pkg} is not named in AGENTS.md — update the docs"
            )
    return errors


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    errors = check(root)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("docs fresh: roster and packages match AGENTS.md/CLAUDE.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
