"""Tests for Lite spec 1, objective 1.3: duplicates.

Uses ONLY committed spec-0 fixtures plus in-test byte transforms of
those fixtures (JPEG re-encode, resize); never fetches images from
the network. The near-match distance always comes from
``phash_max_distance`` in ``lite/config.yaml`` via
:func:`lite.app.config.load_config` -- no literal is re-typed here.
"""

import hashlib
import inspect
from io import BytesIO
from pathlib import Path

import imagehash
from PIL import Image

from lite.app.checks.duplicates import exact_match, near_matches
from lite.app.config import load_config

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

ORIGINAL_NAME = "shapes_editor.jpg"
REENCODED_NAME = "shapes_q50.jpg"
UNRELATED_NAME = "solid_no_exif.jpg"


def _raw(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _phash_hex(raw: bytes) -> str:
    with Image.open(BytesIO(raw)) as img:
        img.load()
        return str(imagehash.phash(img.convert("RGB")))


def _reencode_jpeg(raw: bytes, quality: int) -> bytes:
    with Image.open(BytesIO(raw)) as img:
        rgb = img.convert("RGB")
    buf = BytesIO()
    rgb.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _resize(raw: bytes, scale: float) -> bytes:
    with Image.open(BytesIO(raw)) as img:
        rgb = img.convert("RGB")
        size = (max(1, int(rgb.width * scale)), max(1, int(rgb.height * scale)))
        small = rgb.resize(size, Image.BICUBIC)
    buf = BytesIO()
    small.save(buf, format="PNG")
    return buf.getvalue()


def _distance(a: str, b: str) -> int:
    return int(imagehash.hex_to_hash(a) - imagehash.hex_to_hash(b))


def _store_with_original() -> tuple[str, list[tuple[str, str, str]]]:
    original_raw = _raw(ORIGINAL_NAME)
    unrelated_raw = _raw(UNRELATED_NAME)
    store = [
        ("r-original", _sha256(original_raw), _phash_hex(original_raw)),
        ("r-other", _sha256(unrelated_raw), _phash_hex(unrelated_raw)),
    ]
    return _phash_hex(original_raw), store


def test_max_distance_is_required_arg():
    params = inspect.signature(near_matches).parameters
    assert "max_distance" in params
    assert params["max_distance"].default is inspect.Parameter.empty


def test_exact_match_returns_report_id():
    original_raw = _raw(ORIGINAL_NAME)
    unrelated_raw = _raw(UNRELATED_NAME)
    store = [
        ("r-original", _sha256(original_raw), _phash_hex(original_raw)),
        ("r-other", _sha256(unrelated_raw), _phash_hex(unrelated_raw)),
    ]
    assert exact_match(_sha256(original_raw), store) == "r-original"
    assert exact_match(_sha256(unrelated_raw), store) == "r-other"


def test_exact_match_miss_returns_none():
    _, store = _store_with_original()
    assert exact_match("00" * 32, store) is None
    assert exact_match(_sha256(_raw(ORIGINAL_NAME)), []) is None


def test_reencode_q50_near_matches_original():
    cfg = load_config()
    _, store = _store_with_original()
    original_raw = _raw(ORIGINAL_NAME)
    # Committed q50 fixture (same shapes scene, quality 50).
    committed = _raw(REENCODED_NAME)
    committed_distance = _distance(_phash_hex(original_raw), _phash_hex(committed))
    assert committed_distance <= cfg.phash_max_distance
    assert "r-original" in near_matches(
        _phash_hex(committed), store, cfg.phash_max_distance
    )
    # Fresh in-test re-encode at quality 50.
    fresh = _reencode_jpeg(original_raw, 50)
    fresh_distance = _distance(_phash_hex(original_raw), _phash_hex(fresh))
    assert fresh_distance <= cfg.phash_max_distance
    assert "r-original" in near_matches(
        _phash_hex(fresh), store, cfg.phash_max_distance
    )


def test_resize_90pct_near_matches_original():
    cfg = load_config()
    original_raw = _raw(ORIGINAL_NAME)
    _, store = _store_with_original()
    resized = _resize(original_raw, 0.9)
    distance = _distance(_phash_hex(original_raw), _phash_hex(resized))
    assert distance <= cfg.phash_max_distance
    assert "r-original" in near_matches(
        _phash_hex(resized), store, cfg.phash_max_distance
    )


def test_unrelated_fixture_does_not_near_match():
    cfg = load_config()
    original_phash, store = _store_with_original()
    unrelated_phash = _phash_hex(_raw(UNRELATED_NAME))
    assert _distance(original_phash, unrelated_phash) > cfg.phash_max_distance
    hits = near_matches(unrelated_phash, store, cfg.phash_max_distance)
    # The unrelated image matches only its own row (distance 0 to
    # itself); it must never list the original's report id.
    assert "r-original" not in hits
    assert hits == ["r-other"]


def test_zero_distance_matches_only_identical():
    original_phash, store = _store_with_original()
    assert near_matches(original_phash, store, 0) == ["r-original"]
