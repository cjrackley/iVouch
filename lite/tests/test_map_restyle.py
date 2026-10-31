"""Tests for Lite spec 6, objective 6.3: map page restyle + bottom sheet.

TestClient against tmp SQLite + tmp mail/uploads dirs only -- never
the real ``lite/data/`` directory. The CLIP encoder is always stubbed
through the ``create_app(clip_encoder=...)`` seam (fast).

Covered here (page tests via TestClient + HTML asserts, no browser):

* Bottom-sheet markup: the sheet container (60% height, grab handle,
  rounded top), photo route, incident type (never a title field --
  titles are objective 6.5), no vouch count, ``[View Details]`` to
  ``/shared/{id}`` as the only navigation, and ``[Save]`` as plain
  HTML forms targeting the 6.6 save/unsave endpoints (green fill when
  saved; working without JS through the server-rendered fallback).
* View-details and save wiring end to end: saving through the map
  form lands on ``/saved`` and flips the map to the unsave control.
* Everything spec 5.3/5.4 requires is still served (incident type,
  severity, label with reasons, time, street/satellite toggle,
  visual-compare text, both disclaimers, offline fallback).
* No floating search bar, no default-pin wording, exactly one inline
  script block, and no literal colour values in the template.
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

TEST_SECRET = "test-jwt-secret-for-map-restyle-0123456789"
PASSWORD = "correct-horse-9"
ADULT_DOB = (date.today() - timedelta(days=365 * 30)).isoformat()

HTML = {"Accept": "text/html"}

OWNER_EMAIL = "restyle-owner@example.com"
VIEWER_EMAIL = "restyle-viewer@example.com"

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

HEX_RE = re.compile(r"(?<!&)#[0-9A-Fa-f]{3,8}\b")
SCRIPT_TAG_RE = re.compile(r"<script\b[^>]*>", re.IGNORECASE)
SCRIPT_CLOSE_RE = re.compile(r"</script\s*>", re.IGNORECASE)
SCRIPT_SRC_RE = re.compile(
    r"<script[^>]*\bsrc\s*=\s*\"([^\"]+)\"", re.IGNORECASE
)


class FanStub:
    """Deterministic stub encoder (same shape as the 5.x suites')."""

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
    """Register + verify via API; return Bearer [REDACTED] (spec-2 style)."""
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
    """Register + verify via API, then log in via the page (cookie)."""
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


def _seed_viewer_with_pin(monkeypatch, tmp_path):
    """One accepted upload (owner); return (viewer client, report id)."""
    from fastapi.testclient import TestClient

    app, dirs = _make_app(monkeypatch, tmp_path)
    http = TestClient(app)
    owner_headers = _verified_bearer(http, dirs, OWNER_EMAIL)
    raw = _fresh_png_bytes(seed=901)
    assert (
        hashlib.sha256(raw).hexdigest()
        not in upload_pipeline.load_mock_hashes()
    )
    resp = http.post(
        "/analyze",
        data={
            "client_report_id": "restyle-accept-1",
            "location_lat": str(LAT),
            "location_lng": str(LNG),
            "location_consented": "true",
            "location_source": "browser",
            "claim_text": PAGE_CLAIM,
        },
        files={"photo": ("photo.png", raw, "image/png")},
        headers=owner_headers,
    )
    assert resp.status_code == 200, resp.text
    accepted_id = int(resp.json()["report_id"])
    viewer = TestClient(app)
    _cookie_login(viewer, dirs, VIEWER_EMAIL)
    page = viewer.get("/map", headers=HTML)
    assert page.status_code == 200, page.text
    return viewer, page.text, accepted_id


def test_bottom_sheet_markup_fields_and_save_forms(monkeypatch, tmp_path):
    """Sheet: photo, incident type, details link, save forms; no title."""
    _, body, _ = _seed_viewer_with_pin(monkeypatch, tmp_path)

    # Sheet container with grab handle, 60% height, rounded top.
    assert 'id="map_sheet"' in body
    assert 'id="sheet_grab"' in body
    assert "height: 60%" in body or "height:60%" in body
    assert "var(--radius-pill)" in body

    # Photo through the cookie-session route; incident type in place
    # of the (6.5, unapproved) title field.
    assert "/shared/photos/" in body
    assert "Incident type" in body
    assert 'name="title"' not in body

    # Vouch count is unapproved (6.6/6.10): it must not appear.
    assert "vouches" not in body.lower()

    # [View Details] is the only navigation, aimed at /shared/{id}.
    assert "View Details" in body
    assert 'id="sheet_details"' in body
    assert '"/shared/"' in body or "'/shared/'" in body

    # [Save] controls are plain HTML forms on the 6.6 endpoints, with
    # CSRF fields, so they work without JS.
    assert 'method="post"' in body
    assert 'action="/saved"' in body
    assert "/unsave" in body
    assert 'name="csrf_token"' in body
    assert 'name="report_id"' in body

    # The saved state fills green via the existing secondary variable.
    assert "unsave-button" in body
    assert "var(--color-secondary)" in body


def test_view_details_link_and_save_round_trip(monkeypatch, tmp_path):
    """Fallback link reaches /shared/{id}; map save flips to unsave."""
    viewer, _, accepted_id = _seed_viewer_with_pin(
        monkeypatch, tmp_path
    )

    page = viewer.get("/map", headers=HTML)
    assert f'href="/shared/{accepted_id}"' in page.text

    save = viewer.post(
        "/saved",
        data={
            "csrf_token": _csrf(page.text),
            "report_id": str(accepted_id),
        },
        follow_redirects=False,
    )
    assert save.status_code == 303, save.text
    assert save.headers["location"].endswith("/saved"), save.text

    again = viewer.get("/map", headers=HTML)
    assert again.status_code == 200, again.text
    assert (
        f'action="/saved/{accepted_id}/unsave"' in again.text
    ), "map still offers save after the report was saved"
    assert f'data-saved-ids="{accepted_id}"' in again.text


def test_spec5_requirements_still_served(monkeypatch, tmp_path):
    """Incident, severity, label+reasons, time, toggle, texts, fallback."""
    _, body, accepted_id = _seed_viewer_with_pin(monkeypatch, tmp_path)

    assert "/api/incidents" in body
    assert "maplibre-gl@5.6.0" in body
    assert "unpkg.com" in body
    assert "tiles.openfreemap.org" in body
    assert "basemap_street" in body
    assert "basemap_satellite" in body
    assert "setStyle" in body
    assert "incident_probs" in body
    assert "top_severity" in body
    assert "verdict" in body
    assert "reasons" in body
    assert "created_at" in body
    assert "/api/photos" not in body
    assert COMPARE_LINE in body
    assert DEMO_LINE in body
    assert PHOTO_LINE in body
    assert 'id="map_fallback"' in body
    assert f'href="/shared/{accepted_id}"' in body
    assert "showFallback" in body
    assert "hideFallback" in body
    assert "typeof maplibregl" in body
    assert re.search(r'\.on\(\s*"error"', body)


def test_no_search_bar_and_no_default_pin(monkeypatch, tmp_path):
    """Search stays out; markers are custom pills, never the red pin."""
    _, body, _ = _seed_viewer_with_pin(monkeypatch, tmp_path)

    assert "search" not in body.lower(), "map carries a search bar"
    assert 'type="search"' not in body
    assert "red pin" not in body.lower()
    assert "maplibregl.Popup" not in body, (
        "pin tap must open the bottom sheet, not a popup"
    )
    assert "Marker({ element" in body, "markers lack a custom element"


def test_single_inline_script_with_controls_and_viewport(
    monkeypatch, tmp_path
):
    """One script block; Recenter/Zoom/FAB; viewport fill; active ring."""
    _, body, _ = _seed_viewer_with_pin(monkeypatch, tmp_path)

    for match in SCRIPT_TAG_RE.finditer(body):
        src = SCRIPT_SRC_RE.search(match.group(0))
        if src is not None:
            assert src.group(1) == (
                "https://unpkg.com/maplibre-gl@5.6.0"
                "/dist/maplibre-gl.js"
            ), src.group(1)
    inline = len(SCRIPT_TAG_RE.findall(body)) - len(
        SCRIPT_SRC_RE.findall(body)
    )
    assert inline == 1, f"map carries {inline} inline scripts"
    assert len(SCRIPT_CLOSE_RE.findall(body)) == len(
        SCRIPT_TAG_RE.findall(body)
    )
    for marker in ("maplibregl", "showFallback", "/api/incidents"):
        assert marker in body

    # Floating controls and the gradient FAB to /upload.
    assert 'id="map_recenter"' in body
    assert "Recenter" in body
    assert 'id="map_zoom_in"' in body
    assert 'id="map_zoom_out"' in body
    assert 'id="map_create"' in body
    assert 'href="/upload"' in body
    assert "btn btn-primary" in body

    # The map fills the viewport minus the top bar and tab bar.
    assert "calc(100vh" in body
    assert "var(--top-bar-h)" in body
    assert "var(--tab-bar-h)" in body

    # Active pin feedback plus denied-permission-safe recentering.
    assert "scale(1.15)" in body
    assert "0 0 0 3px" in body
    assert "geolocation" in body
    assert "getCurrentPosition" in body


def test_map_template_uses_variables_not_literals():
    """No literal colour values may appear in the map template."""
    source = (
        Path(__file__).resolve().parent.parent
        / "app"
        / "server"
        / "templates"
        / "map.html"
    ).read_text(encoding="utf-8")
    assert not HEX_RE.search(source), (
        "map.html carries a literal colour instead of a CSS variable: "
        f"{HEX_RE.search(source).group(0)!r}"
    )
