"""Layout and tooling checks for Lite spec 0, objective 0.1.

Asserts the Lite directory layout exists, every dependency in
``lite/requirements.txt`` is pinned to an exact version (``==``),
and the interpreter meets the spec-0 floor (3.12 preferred;
3.11 permitted with a printed note, never a skip).
"""

import re
import sys
from pathlib import Path

LITE_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_DIRS = [
    "app",
    "app/server",
    "app/checks",
    "tests",
    "data/artifacts",
    "data/uploads",
    "data/mail",
    "work/checkpoints",
]

REQUIRED_FILES = [
    "app/__init__.py",
    "app/server/__init__.py",
    "app/checks/__init__.py",
    "app/cli.py",
    "tests/__init__.py",
    "tests/test_layout.py",
    "requirements.txt",
]

# name==version, with no ranges, globs, extras bounds, or env markers
# carrying a second constraint (a bare ";" marker suffix is allowed).
PIN_RE = re.compile(r"^[A-Za-z0-9_.\-]+==[A-Za-z0-9_.\-!+]+(;[^\s,]+)?$")


def test_required_dirs_exist():
    missing = [d for d in REQUIRED_DIRS if not (LITE_ROOT / d).is_dir()]
    assert not missing, f"missing Lite dirs: {missing}"


def test_required_files_exist():
    missing = [f for f in REQUIRED_FILES if not (LITE_ROOT / f).is_file()]
    assert not missing, f"missing Lite files: {missing}"


def test_cli_imports_cleanly():
    import lite.app.cli as cli

    assert cli.main() == 0


def test_requirements_pins_exact_versions():
    req = LITE_ROOT / "requirements.txt"
    lines = [
        line.strip()
        for line in req.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert lines, "requirements.txt lists no dependencies"
    unpinned = [line for line in lines if not PIN_RE.match(line)]
    assert not unpinned, f"dependencies without an exact == pin: {unpinned}"


def test_python_version_supported():
    if sys.version_info < (3, 11):
        raise AssertionError(
            f"Python {sys.version.split()[0]} is below the Lite floor 3.11"
        )
    if sys.version_info < (3, 12):
        print(
            f"NOTE: Python {sys.version.split()[0]} is permitted "
            "(spec-0 floor 3.11); 3.12 remains preferred."
        )
    assert sys.version_info >= (3, 11)
