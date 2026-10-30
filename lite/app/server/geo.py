"""Deterministic display-point jitter for Lite spec 2.4 / spec 5.2.

Exact coordinates stay server-side. :func:`display_point` offsets a
report's exact location by a deterministic pseudo-random bearing and
distance, seeded by the report id (hash-based, stable across calls
and processes), with the offset magnitude inside
``jitter_min_m``..``jitter_max_m`` from ``lite/config.yaml`` (via the
loader, never re-typed literals).

Meters convert to degrees at ~111320 m per degree of latitude, with
the longitude component scaled by ``cos(latitude)``.
"""

from __future__ import annotations

import hashlib
import math
import random

from lite.app.config import load_config

METERS_PER_DEGREE_LAT = 111320.0


def display_point(
    lat: float, lng: float, report_id: int
) -> tuple[float, float]:
    """Return the jittered ``(display_lat, display_lng)`` for a report.

    Pure function of its inputs: the same report id always yields the
    same point. The offset magnitude is uniform in
    ``[jitter_min_m, jitter_max_m]`` meters, so with the shipped
    config (min 200 m) the result is never the exact input point.
    """
    cfg = load_config()
    seed = int.from_bytes(
        hashlib.sha256(str(report_id).encode("utf-8")).digest()[:8],
        "big",
    )
    rng = random.Random(seed)
    distance_m = rng.uniform(cfg.jitter_min_m, cfg.jitter_max_m)
    bearing = rng.uniform(0.0, 2.0 * math.pi)
    north_m = distance_m * math.cos(bearing)
    east_m = distance_m * math.sin(bearing)
    display_lat = lat + north_m / METERS_PER_DEGREE_LAT
    cos_lat = math.cos(math.radians(lat))
    if abs(cos_lat) < 1e-6:
        cos_lat = 1e-6 if cos_lat >= 0 else -1e-6
    display_lng = lng + east_m / (METERS_PER_DEGREE_LAT * cos_lat)
    return (display_lat, display_lng)
