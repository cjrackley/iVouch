"""Fixture tests for Lite spec 0, objective 0.3.

Checks that the synthetic fixtures are deterministic for the fixed seed
(regenerating produces byte-identical output, matching the committed
files) and that each EXIF variant parses as claimed via Pillow/piexif.
"""

import hashlib
import importlib.util
from pathlib import Path

import piexif
from PIL import Image

from lite.tests.fixtures.generate import (
    EDITOR_SOFTWARE,
    HASHES_NAME,
    IMAGE_NAMES,
    SEED,
    generate,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
FIVE_MB = 5 * 1024 * 1024

NO_EXIF_JPEGS = ("solid_no_exif.jpg", "text_no_exif.jpg", "shapes_q50.jpg")


def _load_image_names():
    return sorted(p.name for p in FIXTURES_DIR.glob("*.jpg")) + sorted(
        p.name for p in FIXTURES_DIR.glob("*.png")
    )


def _as_str(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="strict").rstrip("\x00")
    return value


def test_fixture_files_present_and_small():
    names = _load_image_names()
    assert sorted(names) == sorted(IMAGE_NAMES), f"unexpected fixtures: {names}"
    total = 0
    for name in IMAGE_NAMES:
        path = FIXTURES_DIR / name
        size = path.stat().st_size
        assert size > 0, f"{name} is empty"
        total += size
    assert total < FIVE_MB, f"fixtures total {total} bytes exceeds 5 MB"


def test_deterministic_for_fixed_seed(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    run_a = {p.name: p.read_bytes() for p in generate(first)}
    run_b = {p.name: p.read_bytes() for p in generate(second)}
    assert sorted(run_a) == sorted(run_b)
    for name in run_a:
        assert run_a[name] == run_b[name], f"{name} differs between runs"


def test_committed_fixtures_match_generator(tmp_path):
    for path in generate(tmp_path):
        committed = FIXTURES_DIR / path.name
        assert committed.is_file(), f"committed fixture missing: {path.name}"
        assert path.read_bytes() == committed.read_bytes(), (
            f"committed {path.name} is stale; rerun generate.py"
        )


def test_seed_is_fixed():
    assert SEED == 20261028


def test_generator_module_loads_from_file():
    # The suite must exercise the committed generator file itself, so load
    # it by path and confirm it exposes the same fixed seed.
    spec = importlib.util.spec_from_file_location(
        "fixture_generate", FIXTURES_DIR / "generate.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.SEED == SEED
    assert tuple(module.IMAGE_NAMES) == tuple(IMAGE_NAMES)


def test_no_exif_variants_have_no_exif():
    for name in NO_EXIF_JPEGS:
        with Image.open(FIXTURES_DIR / name) as img:
            img.load()
            assert img.format == "JPEG"
            assert len(img.getexif()) == 0, f"{name} unexpectedly has EXIF"
        exif = piexif.load(str(FIXTURES_DIR / name))
        assert exif["0th"] == {}, f"{name} has 0th IFD entries"
        assert exif["Exif"] == {}, f"{name} has Exif IFD entries"
        assert exif["GPS"] == {}, f"{name} has GPS IFD entries"


def test_gps_variant_parses_as_claimed():
    path = FIXTURES_DIR / "shapes_gps.jpg"
    with Image.open(path) as img:
        img.load()
        assert img.format == "JPEG"
        assert 34853 in img.getexif(), "GPS IFD tag missing via Pillow"
    exif = piexif.load(str(path))
    gps = exif["GPS"]
    assert _as_str(gps[piexif.GPSIFD.GPSLatitudeRef]) == "N"
    assert _as_str(gps[piexif.GPSIFD.GPSLongitudeRef]) == "W"
    assert gps[piexif.GPSIFD.GPSLatitude] == ((40, 1), (25, 1), (5500, 100))
    assert gps[piexif.GPSIFD.GPSLongitude] == ((79, 1), (59, 1), (500, 100))
    assert piexif.ImageIFD.Software not in exif["0th"]


def test_editor_variant_parses_as_claimed():
    path = FIXTURES_DIR / "shapes_editor.jpg"
    with Image.open(path) as img:
        img.load()
        assert img.format == "JPEG"
    exif = piexif.load(str(path))
    assert _as_str(exif["0th"][piexif.ImageIFD.Software]) == EDITOR_SOFTWARE
    assert exif["GPS"] == {}, "editor variant unexpectedly has GPS"


def test_png_variant_parses():
    path = FIXTURES_DIR / "shapes_basic.png"
    with Image.open(path) as img:
        img.load()
        assert img.format == "PNG"
        assert img.size == (320, 240)
        assert len(img.getexif()) == 0


def test_reencoded_variant_is_jpeg():
    with Image.open(FIXTURES_DIR / "shapes_q50.jpg") as img:
        img.load()
        assert img.format == "JPEG"
        assert img.size == (320, 240)


def test_mock_hashes_cover_benign_fixtures_only():
    lines = (FIXTURES_DIR / HASHES_NAME).read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(IMAGE_NAMES), f"expected {len(IMAGE_NAMES)} hashes"
    expected = {
        hashlib.sha256((FIXTURES_DIR / name).read_bytes()).hexdigest()
        for name in IMAGE_NAMES
    }
    assert set(lines) == expected
    for line in lines:
        assert len(line) == 64 and all(
            c in "0123456789abcdef" for c in line
        ), f"not a sha256 hex digest: {line!r}"
