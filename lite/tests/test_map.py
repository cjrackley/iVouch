"""Tests for Lite spec 5, objectives 5.3 (map page) + 5.4 (photo visibility).

TestClient against tmp SQLite + tmp mail/uploads dirs only -- never
the real ``lite/data/`` directory. The CLIP encoder is always stubbed
through the ``create_app(clip_encoder=...)`` seam (fast).

Covered here:

* ``GET /map`` login gate (anonymous callers are redirected).
* Map page wiring, asserted server-side from the fetched HTML: the
  in-page fetch of the existing ``GET /api/incidents`` endpoint,
  MapLibre GL JS 5.6.0 via the unpkg CDN with OpenFreeMap tiles, the
  street/satellite basemap toggle, popup field wiring (photo through
  the cookie-session ``/shared/photos/{id}`` route -- never the
  Bearer-only ``/api/photos`` -- incident type, severity,
  authenticity label with reasons, time, and a ``/shared/{id}``
  link), the exact compare line, both disclaimers, and the
  offline/CDN-failure fallback container with its show/hide logic.
* Incidents-payload level exclusion: a seeded accepted report is
  present in ``GET /api/incidents`` (the payload driving the dots)
  while mock-gate-rejected and deleted-account reports have no rows
  to plot.
* Photo visibility: another logged-in user fetches the accepted
  photo bytes through the cookie route the popup uses.

Manual-equivalent checks (no browser automation in Lite -- logged
honestly): every assertion above runs against the served HTML and
JSON via TestClient, which executes no JavaScript by construction.
Pixel rendering of dots, popups, and the basemap toggle was not
eyeballed (this environment has no browser); the wiring those
pixels depend on is asserted as served code instead.
"""

from __future__ import annotations

import hashlib
import io
import random
import re
from datetime import date, timedelta
from pathlib import Path

from PIL import Image

from lite.app.server import pipeline as upload_pipeline
from lite.app.server.api import create_app
from lite.app.server.db import connect

TEST_SECRET = "test-jwt-secret-for-map-tests-0123456789"
PASSWORD = "correct-horse-9"
ADULT_DOB = (date.today() - timedelta(days=365 * 30)).isoformat()

HTML = {"Accept": "text/html"}

OWNER_EMAIL = "map-owner@example.com"
OTHER_EMAIL = "map-other@example.com"
GONE_EMAIL = "map-gone@example.com"

LAT = 51.50745
LNG = -0.12762
PAGE_CLAIM = "a photo of a street with geometric shapes"

COMPARE_LINE = (
    "Compare the photo with this area visually. Lite does not "
    "automatically verify that a photo matches its location."
)
DEMO_LINE = (
    "Demo build \u2014 results need human review "
    "and are not evidence of authenticity."
)
PHOTO_LINE = (
    "Demo only: photos are visible to logged-in users. "
    "Do not upload sensitive images."
)

# Scope firewall: no automated scene-vs-location judgement may appear
# anywhere in the map code (route, template, or served page).
FORBIDDEN_TOKENS = ("score", "match-verdict", "geo-verified")


class FanStub:
    """Deterministic stub encoder (same shape as the 5.1 suite's)."""

    def image_embed(self, image):
        assert isinstance(image, Image.Image)
        return [1.0, 1.0]

    def text_embeds(self, texts):
        return [[1.0, 0.1 * (i + 1)] for i, _ in enumerate(texts)]


def _fresh_png_bytes(seed=0, size=(64, 64)) -> bytes:
    """Generate fresh random-noise PNG bytes (never mock-listed)."""
    rng = random.Random(seed)
    img = Image.new("RGB", size)
    img.putdata(
        [
            (
                rng.randrange(256),
                rng.randrange(256),
                rng.randrange(256),
            )
            for _ in range(size[0] * size[1])
        ]
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_app(monkeypatch, tmp_path):
    monkeypatch.setenv("LITE_JWT_SECRET", TEST_SECRET)
    dirs = {
        "db": tmp_path / "test.db",
        "mail": tmp_path / "mail",
        "uploads": tmp_path / "uploads",
    }
    app = create_app(
        db_path=dirs["db"],
        mail_dir=dirs["mail"],
        uploads_dir=dirs["uploads"],
        clip_encoder=FanStub(),
    )
    return app, dirs


def _mail_token(mail_dir, email) -> str:
    stem = "".join(
        ch if ch.isalnum() else "_" for ch in email.lower()
    )[:64]
    candidates = sorted(Path(mail_dir).glob(f"verify_{stem}_*.txt"))
    assert candidates, f"no verification mail found for {email}"
    match = re.search(
        r"^token:\s*(\S+)\s*$",
        candidates[-1].read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert match, f"mail file {candidates[-1].name} has no token line"
    return match.group(1)


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "page has no CSRF token field"
    return match.group(1)


def _verified_bearer(http, dirs, email):
    """Register + verify via API; return Bearer headers (spec-2 style)."""
    assert http.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "date_of_birth": ADULT_DOB,
        },
    ).status_code == 200
    assert http.post(
        "/auth/verify-email",
        json={"token": _mail_token(dirs["mail"], email)},
    ).status_code == 200
    login = http.post(
        "/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _cookie_login(http, dirs, email) -> None:
    """Register + verify via API, then log in via the page (cookie).

    Returns nothing: the proof is the ``lite_session`` cookie in the
    client's jar. Never fetches a Bearer [REDACTED]
    """
    assert http.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "date_of_birth": ADULT_DOB,
        },
    ).status_code == 200
    assert http.post(
        "/auth/verify-email",
        json={"token": _mail_token(dirs["mail"], email)},
    ).status_code == 200
    page = http.get("/login", headers=HTML)
    assert page.status_code == 200, page.text
    login = http.post(
        "/login",
        data={
            "email": email,
            "password": PASSWORD,
            "csrf_token": _csrf(page.text),
        },
        follow_redirects=False,
    )
    assert login.status_code == 303, login.text
    assert "lite_session" in http.cookies, "page login set no cookie"


def _accepted_upload(http, headers, *, client_id, seed) -> tuple[bytes, int]:
    """Upload fresh bytes via the JSON flow; return (raw, report_id)."""
    raw = _fresh_png_bytes(seed=seed)
    assert (
        hashlib.sha256(raw).hexdigest()
        not in upload_pipeline.load_mock_hashes()
    )
    resp = http.post(
        "/analyze",
        data={
            "client_report_id": client_id,
            "location_lat": str(LAT),
            "location_lng": str(LNG),
            "location_consented": "true",
            "location_source": "browser",
            "claim_text": PAGE_CLAIM,
        },
        files={"photo": ("photo.png", raw, "image/png")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "report_id" in body, body
    return raw, int(body["report_id"])


def _mock_rejected_upload(http, headers, *, client_id) -> None:
    """Upload mock-listed fixture bytes: rejected, no report row."""
    raw = (
        Path(__file__).resolve().parent / "fixtures" / "shapes_basic.png"
    ).read_bytes()
    assert (
        hashlib.sha256(raw).hexdigest()
        in upload_pipeline.load_mock_hashes()
    )
    resp = http.post(
        "/analyze",
        data={
            "client_report_id": client_id,
            "location_lat": str(LAT),
            "location_lng": str(LNG),
            "location_consented": "true",
            "location_source": "browser",
            "claim_text": PAGE_CLAIM,
        },
        files={"photo": ("shapes_basic.png", raw, "image/png")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert "report_id" not in resp.json(), resp.text


def _delete_account_via_page(http) -> None:
    """Delete the cookie-session account through the page flow."""
    page = http.get("/account", headers=HTML)
    assert page.status_code == 200, page.text
    resp = http.post(
        "/account/delete",
        data={"csrf_token": _csrf(page.text), "confirm": "yes"},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text


def _report_ids_in_db(db_path) -> set:
    conn = connect(str(db_path))
    try:
        return {
            row["id"]
            for row in conn.execute("SELECT id FROM reports").fetchall()
        }
    finally:
        conn.close()


def _seed_accepted_plus_rejected(http, dirs):
    """One accepted upload (owner); one mock rejection (no row)."""
    owner_headers = _verified_bearer(http, dirs, OWNER_EMAIL)
    other_headers = _verified_bearer(http, dirs, OTHER_EMAIL)
    _, accepted_id = _accepted_upload(
        http, owner_headers, client_id="map-accept-1", seed=701
    )
    before = _report_ids_in_db(dirs["db"])
    _mock_rejected_upload(http, other_headers, client_id="map-reject-1")
    assert _report_ids_in_db(dirs["db"]) == before
    return owner_headers, other_headers, accepted_id


def test_map_login_gate(monkeypatch, tmp_path):
    """Anonymous callers are redirected to login, never shown the map."""
    from fastapi.testclient import TestClient

    app, _ = _make_app(monkeypatch, tmp_path)
    anon = TestClient(app)
    resp = anon.get("/map", headers=HTML, follow_redirects=False)
    assert resp.status_code in (401, 303), resp.status_code
    if resp.status_code == 303:
        assert resp.headers["location"].endswith("/login"), resp.text
        followed = anon.get("/map", headers=HTML)
        assert followed.status_code == 200, followed.text
        assert "Log in" in followed.text


def test_map_page_wiring(monkeypatch, tmp_path):
    """Served map HTML carries every 5.3/5.4 wiring element."""
    from fastapi.testclient import TestClient

    app, dirs = _make_app(monkeypatch, tmp_path)
    http = TestClient(app)
    _, _, accepted_id = _seed_accepted_plus_rejected(http, dirs)
    viewer = TestClient(app)
    _cookie_login(viewer, dirs, OTHER_EMAIL)

    page = viewer.get("/map", headers=HTML)
    assert page.status_code == 200, page.text
    body = page.text

    # Dots are driven by the existing incidents endpoint (unmodified).
    assert "/api/incidents" in body

    # MapLibre 5.6.0 via CDN (same pin as the upload picker) plus
    # OpenFreeMap tiles, street and satellite styles.
    assert "maplibre-gl@5.6.0" in body
    assert "unpkg.com" in body
    assert "maplibre-gl.css" in body
    assert "maplibre-gl.js" in body
    assert "tiles.openfreemap.org" in body
    assert "https://tiles.openfreemap.org/styles/liberty" in body

    # Basemap toggle control switching street/satellite styles.
    assert "basemap_street" in body
    assert "basemap_satellite" in body
    assert "setStyle" in body

    # Popup field wiring: cookie-session photo route (browsers send
    # cookies only, never the Bearer-only /api/photos), incident
    # type, severity, authenticity label with reasons, time, and the
    # community-page link pattern.
    assert "/shared/photos/" in body
    assert '"/shared/photos/"' in body or "'/shared/photos/'" in body
    assert "/api/photos" not in body, (
        "map popup must not use the Bearer-only photo route"
    )
    assert "incident_probs" in body
    assert "top_severity" in body
    assert "verdict" in body
    assert "reasons" in body
    assert "created_at" in body
    assert '"/shared/"' in body or "'/shared/'" in body

    # Exact wording: compare line plus both disclaimers.
    assert COMPARE_LINE in body
    assert DEMO_LINE in body
    assert PHOTO_LINE in body

    # Offline/CDN-failure fallback: server-rendered report links plus
    # the show/hide logic that swaps them in for a blank map.
    assert 'id="map_fallback"' in body
    assert f'href="/shared/{accepted_id}"' in body
    assert "showFallback" in body
    assert "hideFallback" in body
    assert "typeof maplibregl" in body
    assert re.search(r'\.on\(\s*"error"', body), (
        "map has no tile-failure error handler"
    )

    # Scope firewall: no automated scene-vs-location judgement.
    for token in FORBIDDEN_TOKENS:
        assert token not in body, f"map page contains {token!r}"


def test_incidents_payload_drives_dots_excludes_rejected_deleted(
    monkeypatch, tmp_path
):
    """Accepted report plots; rejected/deleted reports have no dot."""
    from fastapi.testclient import TestClient

    app, dirs = _make_app(monkeypatch, tmp_path)
    http = TestClient(app)
    owner_headers, _, accepted_id = _seed_accepted_plus_rejected(
        http, dirs
    )

    # A third account uploads, then deletes itself: its report row
    # cascades away and must leave the incidents payload.
    gone_headers = _verified_bearer(http, dirs, GONE_EMAIL)
    _, gone_id = _accepted_upload(
        http, gone_headers, client_id="map-gone-1", seed=702
    )
    assert gone_id in _report_ids_in_db(dirs["db"])
    gone = TestClient(app)
    _cookie_login(gone, dirs, GONE_EMAIL)
    _delete_account_via_page(gone)
    assert gone_id not in _report_ids_in_db(dirs["db"])

    incidents = http.get("/api/incidents", headers=owner_headers)
    assert incidents.status_code == 200, incidents.text
    payload = incidents.json()
    assert payload["type"] == "FeatureCollection"
    features = payload["features"]
    assert features, "seeded accepted report missing from incidents"

    surfaced = {
        feature["properties"]["report_id"] for feature in features
    }
    assert accepted_id in surfaced
    assert gone_id not in surfaced
    assert surfaced <= _report_ids_in_db(dirs["db"])

    # The map fallback list mirrors the same payload: accepted linked,
    # deleted never linked, rejected never stored.
    viewer = TestClient(app)
    _cookie_login(viewer, dirs, OTHER_EMAIL)
    page = viewer.get("/map", headers=HTML)
    assert page.status_code == 200, page.text
    assert f'href="/shared/{accepted_id}"' in page.text
    assert f'href="/shared/{gone_id}"' not in page.text


def test_map_popup_photo_visible_to_other_user(monkeypatch, tmp_path):
    """5.4: another logged-in user sees popup photo bytes (cookie)."""
    from fastapi.testclient import TestClient

    app, dirs = _make_app(monkeypatch, tmp_path)
    http = TestClient(app)
    owner_headers, _, accepted_id = _seed_accepted_plus_rejected(
        http, dirs
    )
    raw_owner = http.get(
        f"/api/photos/{accepted_id}", headers=owner_headers
    )
    assert raw_owner.status_code == 200, raw_owner.text

    other = TestClient(app)
    _cookie_login(other, dirs, OTHER_EMAIL)
    photo = other.get(f"/shared/photos/{accepted_id}")
    assert photo.status_code == 200, photo.text
    assert photo.headers["content-type"].startswith("image/")
    assert photo.content == raw_owner.content
