"""Tests for Lite spec 5, objective 5.2 (bounds half): jitter distance bounds.

Proves that :func:`lite.app.server.geo.display_point` offsets the exact
point by a haversine distance inside ``[jitter_min_m, jitter_max_m]``
read via the config loader (never re-typed), and strictly greater than
zero. Pure function tests: no server, no network.

The display API itself (keys, determinism, exclusion) is tested
elsewhere and is out of scope here.
"""

from __future__ import annotations

import math

from lite.app.config import load_config
from lite.app.server.geo import display_point

EARTH_RADIUS_M = 6371000.0

# Spread of report ids: dense low range plus large/sparse ids so the
# hash-seeded bearing/distance draws cover the jitter interval.
REPORT_IDS = list(range(1, 41)) + [100, 101, 1000, 424242, 999999999]

# Spread of base coords: mid latitudes both hemispheres, equator/prime
# meridian, plus high latitudes where the cos(latitude) longitude
# scaling matters (Tromso area ~70N, Svalbard ~78.2N).
BASE_COORDS = [
    (40.7128, -74.0060),  # New York
    (51.50745, -0.12762),  # London (fractional, like retrieval tests)
    (0.0, 0.0),  # equator / prime meridian
    (-33.865143, 151.209900),  # Sydney (southern hemisphere)
    (69.6492, 18.9553),  # Tromso (high latitude)
    (78.2232, 15.6267),  # Svalbard (extreme cos scaling)
]


def _haversine_m(lat1, lng1, lat2, lng2) -> float:
    """Great-circle distance in meters (independent oracle)."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lng2 - lng1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def test_display_distance_within_configured_bounds():
    cfg = load_config()
    lo = cfg.jitter_min_m
    hi = cfg.jitter_max_m
    assert lo < hi
    for report_id in REPORT_IDS:
        for lat, lng in BASE_COORDS:
            display_lat, display_lng = display_point(lat, lng, report_id)
            distance = _haversine_m(lat, lng, display_lat, display_lng)
            assert lo <= distance <= hi, (
                f"report {report_id} @ ({lat}, {lng}): "
                f"distance {distance:.3f} m outside [{lo}, {hi}]"
            )


def test_display_distance_strictly_positive():
    # The configured min bound (200 m per shipped config, read via the
    # loader and asserted below) guarantees a nonzero offset; this
    # asserts the > 0 property explicitly on every sample.
    cfg = load_config()
    assert cfg.jitter_min_m > 0
    for report_id in REPORT_IDS:
        for lat, lng in BASE_COORDS:
            display_lat, display_lng = display_point(lat, lng, report_id)
            distance = _haversine_m(lat, lng, display_lat, display_lng)
            assert distance > 0, (
                f"report {report_id} @ ({lat}, {lng}): "
                "display point equals exact point"
            )
