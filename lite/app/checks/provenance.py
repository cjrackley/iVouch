"""Provenance-lite flags (Lite spec 1, objective 1.2).

Pipeline position: step 3 of the spec-1 check pipeline. This module
emits observation flags only -- it never returns a verdict and never
lowers a label. In particular, missing EXIF by itself means nothing
suspicious: it only yields ``exif_present=False`` with the remaining
flags at their neutral values.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO

import piexif
from PIL import Image

# No key in lite/config.yaml names an implausibly-old capture-time
# cutoff, so this module defines its own (and deliberately does NOT
# invent a config key): capture times before 2000-01-01 UTC are treated
# as implausible. Consumer digital cameras postdate that era, so an
# older EXIF timestamp on a Lite upload indicates a bad clock, a
# hand-written tag, or scanned-film provenance -- not a fresh capture.
EARLIEST_PLAUSIBLE_CAPTURE_TIME = datetime(2000, 1, 1, tzinfo=timezone.utc)

_EXIF_DATETIME_FORMAT = "%Y:%m:%d %H:%M:%S"


@dataclass(frozen=True)
class Provenance:
    """Observation flags from an upload's EXIF block."""

    exif_present: bool
    time_plausible: bool
    gps_present: bool
    editor_tag: str | None = None


def _as_text(value) -> str | None:
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return None
    if not isinstance(value, str):
        return None
    text = value.strip().rstrip("\x00").strip()
    return text or None


def _parse_exif_datetime(value) -> datetime | None:
    text = _as_text(value)
    if text is None:
        return None
    try:
        parsed = datetime.strptime(text, _EXIF_DATETIME_FORMAT)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc)


def _capture_times(exif: dict) -> list[datetime]:
    found: list[datetime] = []
    zeroth = exif.get("0th", {}) or {}
    inner = exif.get("Exif", {}) or {}
    candidates = (
        zeroth.get(piexif.ImageIFD.DateTime),
        inner.get(piexif.ExifIFD.DateTimeOriginal),
        inner.get(piexif.ExifIFD.DateTimeDigitized),
    )
    for raw in candidates:
        if raw is None:
            continue
        parsed = _parse_exif_datetime(raw)
        if parsed is not None:
            found.append(parsed)
    return found


def provenance_signals(raw: bytes, received_at: datetime) -> Provenance:
    """Extract provenance observation flags from raw upload bytes.

    ``received_at`` is the upload receipt time; a capture time after it
    (i.e. in the future) is implausible, as is any capture time before
    ``EARLIEST_PLAUSIBLE_CAPTURE_TIME``. Bytes with no EXIF, no GPS, or
    no parseable capture time yield the neutral flags
    (``exif_present``/``gps_present`` False, ``time_plausible`` True,
    ``editor_tag`` None) instead of raising; undecodable input behaves
    the same way.
    """
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)

    try:
        with Image.open(BytesIO(raw)) as img:
            img.load()
        exif = piexif.load(raw if isinstance(raw, bytes) else bytes(raw))
    except Exception:
        return Provenance(
            exif_present=False,
            time_plausible=True,
            gps_present=False,
            editor_tag=None,
        )

    ifds = [exif.get(name) or {} for name in ("0th", "Exif", "GPS", "Interop", "1st")]
    exif_present = any(bool(ifd) for ifd in ifds)

    gps = exif.get("GPS", {}) or {}
    gps_present = bool(gps)

    zeroth = exif.get("0th", {}) or {}
    editor_tag = _as_text(zeroth.get(piexif.ImageIFD.Software))

    times = _capture_times(exif)
    time_plausible = all(
        EARLIEST_PLAUSIBLE_CAPTURE_TIME <= taken <= received_at for taken in times
    )

    return Provenance(
        exif_present=exif_present,
        time_plausible=time_plausible,
        gps_present=gps_present,
        editor_tag=editor_tag,
    )
