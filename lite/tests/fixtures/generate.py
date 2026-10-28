"""Deterministic synthetic image fixtures for Lite unit tests.

Spec 0, objective 0.3. Drawing uses ONLY Pillow (pinned in
``lite/requirements.txt``) plus the Python standard library; EXIF blocks
are written with piexif (also pinned). Only Pillow's built-in default
font (``ImageFont.load_default()``) is used -- no system fonts -- and all
randomness comes from a single ``random.Random`` seeded with ``SEED``,
so re-runs on the same checkout produce byte-identical files. No
timestamps or dates are embedded anywhere (JPEG has no timestamp fields
and no ``DateTime`` EXIF tags are written).

Fixtures written by :func:`generate` (all unit-test use only):

- ``solid_no_exif.jpg`` -- solid-colour scene, no EXIF.
- ``text_no_exif.jpg`` -- short text lines, no EXIF.
- ``shapes_gps.jpg`` -- seeded shapes, EXIF with GPS coordinates.
- ``shapes_editor.jpg`` -- seeded shapes, EXIF with an editor tag.
- ``shapes_q50.jpg`` -- seeded shapes re-encoded at JPEG quality 50.
- ``shapes_basic.png`` -- seeded shapes as PNG.
- ``mock_hashes.txt`` -- one SHA-256 hex digest per line (sorted by
  file name) covering exactly the image files above: benign synthetic
  fixtures only, for the spec-1 mock safety gate (see
  ``policy_mock_hashes_path`` in ``lite/config.yaml``).
"""

from __future__ import annotations

import argparse
import hashlib
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import piexif

SEED = 20261028
SIZE = (320, 240)
BASE_JPEG_QUALITY = 92
REENCODE_QUALITY = 50
EDITOR_SOFTWARE = "GIMP 2.10.36"

# Fixed GPS point (decimal 40.431944 N, 79.984722 W) as EXIF rationals.
GPS_LAT_REF = "N"
GPS_LAT = ((40, 1), (25, 1), (5500, 100))
GPS_LON_REF = "W"
GPS_LON = ((79, 1), (59, 1), (500, 100))

IMAGE_NAMES = (
    "solid_no_exif.jpg",
    "text_no_exif.jpg",
    "shapes_gps.jpg",
    "shapes_editor.jpg",
    "shapes_q50.jpg",
    "shapes_basic.png",
)
HASHES_NAME = "mock_hashes.txt"


def make_solid() -> Image.Image:
    """Return a solid-colour scene (no randomness needed)."""
    return Image.new("RGB", SIZE, (30, 90, 160))


def make_text(rng: random.Random) -> Image.Image:
    """Return fixed text lines plus one seeded accent rule."""
    img = Image.new("RGB", SIZE, (245, 242, 235))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    lines = ("ivouch lite fixture", "claim: storm damage", "severity: minor")
    y = 40
    for line in lines:
        draw.text((30, y), line, fill=(20, 20, 20), font=font)
        y += 30
    x = 30 + rng.randrange(0, 40)
    draw.line([(x, y), (x + 120, y)], fill=(200, 40, 40), width=3)
    return img


def make_shapes(rng: random.Random) -> Image.Image:
    """Return seeded shapes on a light background."""
    img = Image.new("RGB", SIZE, (240, 240, 240))
    draw = ImageDraw.Draw(img)
    palette = [
        (200, 60, 60),
        (60, 140, 60),
        (60, 90, 200),
        (220, 170, 40),
        (130, 70, 180),
    ]
    for _ in range(5):
        x0 = rng.randrange(0, 200)
        y0 = rng.randrange(0, 140)
        x1 = x0 + rng.randrange(40, 120)
        y1 = y0 + rng.randrange(40, 100)
        colour = palette[rng.randrange(len(palette))]
        kind = rng.choice(("rect", "ellipse", "line"))
        if kind == "rect":
            draw.rectangle([x0, y0, x1, y1], outline=colour, width=3)
        elif kind == "ellipse":
            draw.ellipse([x0, y0, x1, y1], outline=colour, width=3)
        else:
            draw.line([x0, y0, x1, y1], fill=colour, width=3)
    return img


def gps_exif_bytes() -> bytes:
    """Return a fixed EXIF block carrying GPS coordinates only."""
    exif_dict = {
        "0th": {},
        "Exif": {},
        "GPS": {
            piexif.GPSIFD.GPSVersionID: (2, 0, 0, 0),
            piexif.GPSIFD.GPSLatitudeRef: GPS_LAT_REF,
            piexif.GPSIFD.GPSLatitude: GPS_LAT,
            piexif.GPSIFD.GPSLongitudeRef: GPS_LON_REF,
            piexif.GPSIFD.GPSLongitude: GPS_LON,
        },
        "Interop": {},
        "1st": {},
        "thumbnail": None,
    }
    return piexif.dump(exif_dict)


def editor_exif_bytes() -> bytes:
    """Return a fixed EXIF block carrying an editor tag only."""
    exif_dict = {
        "0th": {piexif.ImageIFD.Software: EDITOR_SOFTWARE},
        "Exif": {},
        "GPS": {},
        "Interop": {},
        "1st": {},
        "thumbnail": None,
    }
    return piexif.dump(exif_dict)


def generate(output_dir: str | Path) -> list[Path]:
    """Write all fixtures plus ``mock_hashes.txt``; return written paths."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)

    solid = make_solid()
    text = make_text(rng)
    shapes = make_shapes(rng)

    payloads: dict[str, Image.Image] = {
        "solid_no_exif.jpg": solid,
        "text_no_exif.jpg": text,
        "shapes_gps.jpg": shapes,
        "shapes_editor.jpg": shapes,
        "shapes_q50.jpg": shapes,
        "shapes_basic.png": shapes,
    }
    written: list[Path] = []
    for name in IMAGE_NAMES:
        path = out / name
        img = payloads[name]
        if name.endswith(".png"):
            img.save(path, format="PNG")
        elif name == "shapes_gps.jpg":
            img.save(path, format="JPEG", quality=BASE_JPEG_QUALITY,
                      exif=gps_exif_bytes())
        elif name == "shapes_editor.jpg":
            img.save(path, format="JPEG", quality=BASE_JPEG_QUALITY,
                      exif=editor_exif_bytes())
        elif name == "shapes_q50.jpg":
            img.save(path, format="JPEG", quality=REENCODE_QUALITY)
        else:
            img.save(path, format="JPEG", quality=BASE_JPEG_QUALITY)
        written.append(path)

    hashes_path = out / HASHES_NAME
    lines = []
    for name in sorted(IMAGE_NAMES):
        digest = hashlib.sha256((out / name).read_bytes()).hexdigest()
        lines.append(digest + "\n")
    hashes_path.write_text("".join(lines), encoding="utf-8")
    written.append(hashes_path)
    return written


def main(argv: list[str] | None = None) -> int:
    """Regenerate the committed fixtures in place."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parent),
        help="directory to write fixtures into",
    )
    args = parser.parse_args(argv)
    for path in generate(args.output_dir):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
