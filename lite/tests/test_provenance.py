"""Tests for Lite spec 1, objective 1.2: provenance-lite flags.

Uses ONLY committed spec-0 fixtures plus EXIF blocks synthesized
in-test with piexif/Pillow (no new fixture files are committed).
"""

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import piexif
from PIL import Image

from lite.app.checks.provenance import (
    EARLIEST_PLAUSIBLE_CAPTURE_TIME,
    Provenance,
    provenance_signals,
)
from lite.tests.fixtures.generate import EDITOR_SOFTWARE

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
RECEIVED_AT = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)


def _raw(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


def _jpeg_with_exif(exif_dict: dict) -> bytes:
    img = Image.new("RGB", (32, 24), (10, 20, 30))
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=piexif.dump(exif_dict))
    return buf.getvalue()


def _blank_exif() -> dict:
    return {"0th": {}, "Exif": {}, "GPS": {}, "Interop": {}, "1st": {},
            "thumbnail": None}


def test_no_exif_solid_flags():
    result = provenance_signals(_raw("solid_no_exif.jpg"), RECEIVED_AT)
    assert result == Provenance(
        exif_present=False,
        time_plausible=True,
        gps_present=False,
        editor_tag=None,
    )


def test_no_exif_text_flags():
    result = provenance_signals(_raw("text_no_exif.jpg"), RECEIVED_AT)
    assert result.exif_present is False
    assert result.time_plausible is True
    assert result.gps_present is False
    assert result.editor_tag is None


def test_gps_variant_flags():
    result = provenance_signals(_raw("shapes_gps.jpg"), RECEIVED_AT)
    assert result.exif_present is True
    assert result.gps_present is True
    assert result.editor_tag is None
    # GPS block carries no capture-time tags: nothing inconsistent seen.
    assert result.time_plausible is True


def test_editor_variant_flags():
    result = provenance_signals(_raw("shapes_editor.jpg"), RECEIVED_AT)
    assert result.exif_present is True
    assert result.gps_present is False
    assert result.editor_tag == EDITOR_SOFTWARE
    # Editor tag alone, with no capture-time tags, is not implausible.
    assert result.time_plausible is True


def test_reencoded_q50_flags():
    result = provenance_signals(_raw("shapes_q50.jpg"), RECEIVED_AT)
    assert result.exif_present is False
    assert result.time_plausible is True
    assert result.gps_present is False
    assert result.editor_tag is None


def test_png_variant_flags():
    result = provenance_signals(_raw("shapes_basic.png"), RECEIVED_AT)
    assert result.exif_present is False
    assert result.time_plausible is True
    assert result.gps_present is False
    assert result.editor_tag is None


def test_future_capture_time_is_implausible():
    exif_dict = _blank_exif()
    exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = "2027:05:06 12:00:00"
    raw = _jpeg_with_exif(exif_dict)
    result = provenance_signals(raw, RECEIVED_AT)
    assert result.exif_present is True
    assert result.time_plausible is False


def test_past_capture_time_is_plausible():
    exif_dict = _blank_exif()
    exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = "2024:05:06 12:00:00"
    raw = _jpeg_with_exif(exif_dict)
    result = provenance_signals(raw, RECEIVED_AT)
    assert result.exif_present is True
    assert result.time_plausible is True


def test_implausibly_old_capture_time_is_implausible():
    assert EARLIEST_PLAUSIBLE_CAPTURE_TIME.year == 2000
    exif_dict = _blank_exif()
    exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = "1995:01:02 03:04:05"
    raw = _jpeg_with_exif(exif_dict)
    result = provenance_signals(raw, RECEIVED_AT)
    assert result.time_plausible is False


def test_non_image_bytes_yield_neutral_flags():
    for raw in (b"this is definitely not an image", b""):
        result = provenance_signals(raw, RECEIVED_AT)
        assert result.exif_present is False
        assert result.time_plausible is True
        assert result.gps_present is False
        assert result.editor_tag is None
