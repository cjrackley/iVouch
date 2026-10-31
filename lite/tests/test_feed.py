"""Tests for Lite spec 6, objective 6.7: feed page.

TestClient against tmp SQLite + tmp mail/uploads dirs only -- never
the real ``lite/data/`` directory. The CLIP encoder is always stubbed
through the ``create_app(clip_encoder=...)`` seam (fast; the live
model path is objective 2.5's, never here).

Endpoints under test: ``GET /feed`` (login required, redirect to
``/login`` when logged out) with the ``For You | Nearby`` segmented
toggle as plain links (no Following segment: follows/profiles were
not approved). Save toggles reuse the 6.6 ``POST /saved`` and
``POST /saved/{id}/unsave`` endpoints.
"""

from __future__ import annotations

import io
import random
import re
from datetime import date, timedelta
from pathlib import Path

from PIL import Image

from lite.app.server.api import create_app
from lite.app.server.db import connect, create_report

TEST_SECRET = "test-jwt-secret-for-feed-tests-0123456789"
PASSWORD = "correct-horse-9"
ADULT_DOB = (date.today() - timedelta(days=365 * 30)).isoformat()

OWNER_EMAIL = "feeder@example.com"
OTHER_EMAIL = "feed-bystander@example.com"

LAT = 51.50745
LNG = -0.12762
FAR_LAT = 40.71280
FAR_LNG = -74.00600
OWNER_CLAIM = "a photo of a street with geometric shapes"

HTML = {"Accept": "text/html"}


class FanStub:
    """Deterministic stub encoder (same shape as the 2.3 suite's)."""

    def image_embed(self, image):
        assert isinstance(image, Image.Image)
        return [1.0, 1.0]

    def text_embeds(self, texts):
        return [[1.0, 0.1 * (i + 1)] for i, _ in enumerate(texts)]


def _fresh_jpeg_bytes(seed=0, size=(64, 64)) -> bytes:
    """Generate fresh random-noise JPEG bytes (never mock-listed)."""
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
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_client(monkeypatch, tmp_path):
    monkeypatch.setenv("LITE_JWT_SECRET", TEST_SECRET)
    dirs = {
        "db": tmp_path / "test.db",
        "mail": tmp_path / "mail",
        "uploads": tmp_path / "uploads",
    }
    from fastapi.testclient import TestClient

    app = create_app(
        db_path=dirs["db"],
        mail_dir=dirs["mail"],
        uploads_dir=dirs["uploads"],
        clip_encoder=FanStub(),
    )
    return TestClient(app), dirs


def _verified_account(http, dirs, email):
    """Register, verify via console mail, log in; return (headers, id)."""
    resp = http.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "date_of_birth": ADULT_DOB,
        },
    )
    assert resp.status_code == 200
    stem = "".join(
        ch if ch.isalnum() else "_" for ch in email.lower()
    )[:64]
    candidates = sorted(
        Path(dirs["mail"]).glob(f"verify_{stem}_*.txt")
    )
    assert candidates, f"no verification mail found for {email}"
    match = re.search(
        r"^token:\s*(\S+)\s*$",
        candidates[-1].read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert match, f"mail file {candidates[-1].name} has no token line"
    verify = http.post("/auth/verify-email", json={"token": match.group(1)})
    assert verify.status_code == 200
    login = http.post(
        "/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert login.status_code == 200
    assert login.json()["email_verified"] is True
    headers = {
        "Authorization": f"Bearer {login.json()['access_token']}"
    }
    me = http.get("/account", headers=headers)
    assert me.status_code == 200
    return headers, me.json()["id"]


def _upload(http, headers, raw, claim, client_id, lat=LAT, lng=LNG,
            title="Corner shop front"):
    resp = http.post(
        "/analyze",
        data={
            "client_report_id": client_id,
            "location_lat": str(lat),
            "location_lng": str(lng),
            "location_consented": "true",
            "location_source": "browser",
            "claim_text": claim,
            "title": title,
            "category": "fire",
        },
        files={"photo": ("photo.jpg", raw, "image/jpeg")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _page_login(http, email):
    """Log in through the page form (sets the cookie session)."""
    page = http.get("/login", headers=HTML)
    assert page.status_code == 200, page.text
    match = re.search(
        r'name="csrf_token" value="([^"]+)"', page.text
    )
    assert match, "login page has no CSRF token field"
    resp = http.post(
        "/login",
        data={
            "email": email,
            "password": PASSWORD,
            "csrf_token": match.group(1),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text


def _page_csrf(http):
    page = http.get("/account", headers=HTML)
    assert page.status_code == 200, page.text
    match = re.search(
        r'name="csrf_token" value="([^"]+)"', page.text
    )
    assert match, "/account has no CSRF token field"
    return match.group(1)


def _setup_owner_with_report(monkeypatch, tmp_path, seed=401):
    http, dirs = _make_client(monkeypatch, tmp_path)
    owner_headers, _ = _verified_account(http, dirs, OWNER_EMAIL)
    upload = _upload(
        http,
        owner_headers,
        _fresh_jpeg_bytes(seed=seed),
        OWNER_CLAIM,
        f"feed-owner-{seed}",
    )
    assert "report_id" in upload, upload
    return http, dirs, owner_headers, upload["report_id"]


def test_feed_page_requires_login(monkeypatch, tmp_path):
    http, _ = _make_client(monkeypatch, tmp_path)
    page = http.get("/feed", headers=HTML, follow_redirects=False)
    assert page.status_code == 303, page.text
    assert page.headers["location"] == "/login"


def test_segments_for_you_and_nearby_present_following_absent(
    monkeypatch, tmp_path
):
    http, dirs, _, _ = _setup_owner_with_report(monkeypatch, tmp_path)
    _page_login(http, OWNER_EMAIL)
    for route in ("/feed", "/feed?view=nearby"):
        page = http.get(route, headers=HTML)
        assert page.status_code == 200, (route, page.text)
        assert "For You" in page.text, route
        assert "Nearby" in page.text, route
        assert "Following" not in page.text, route
        assert 'href="/feed"' in page.text, route
        assert 'href="/feed?view=nearby"' in page.text, route
        assert "/profile" not in page.text, route
        assert "<script" not in page.text.lower(), route


def test_each_card_opens_shared_report(monkeypatch, tmp_path):
    http, dirs = _make_client(monkeypatch, tmp_path)
    owner_headers, _ = _verified_account(http, dirs, OWNER_EMAIL)
    first = _upload(
        http, owner_headers, _fresh_jpeg_bytes(seed=411),
        OWNER_CLAIM, "feed-cards-1",
    )
    second = _upload(
        http, owner_headers, _fresh_jpeg_bytes(seed=412),
        "another street scene with shapes", "feed-cards-2",
        title="Bus stop mural",
    )
    _page_login(http, OWNER_EMAIL)
    page = http.get("/feed", headers=HTML)
    assert page.status_code == 200, page.text
    for report_id in (first["report_id"], second["report_id"]):
        assert f'href="/shared/{report_id}"' in page.text
        assert f'src="/shared/photos/{report_id}"' in page.text
    # Newest first on the default For You view.
    assert page.text.index(f"/shared/{second['report_id']}") < (
        page.text.index(f"/shared/{first['report_id']}")
    )
    # Titles use the 6.5 display helper; vouch counts start at zero.
    assert "Corner shop front" in page.text
    assert "Bus stop mural" in page.text
    assert "0 vouches" in page.text


def test_vouch_count_shows_per_card(monkeypatch, tmp_path):
    http, dirs, owner_headers, report_id = _setup_owner_with_report(
        monkeypatch, tmp_path
    )
    vouched = http.post(
        "/vouches", json={"report_id": report_id}, headers=owner_headers
    )
    assert vouched.status_code == 200, vouched.text
    _page_login(http, OWNER_EMAIL)
    page = http.get("/feed", headers=HTML)
    assert page.status_code == 200, page.text
    assert "1 vouches" in page.text


def test_save_works_per_card_and_syncs_with_saved(
    monkeypatch, tmp_path
):
    http, dirs, owner_headers, report_id = _setup_owner_with_report(
        monkeypatch, tmp_path
    )
    _page_login(http, OWNER_EMAIL)

    page = http.get("/feed", headers=HTML)
    assert page.status_code == 200, page.text
    assert ">Save<" in page.text
    assert f'action="/saved/{report_id}/unsave"' not in page.text

    csrf = _page_csrf(http)
    added = http.post(
        "/saved",
        data={"report_id": str(report_id), "csrf_token": csrf},
        follow_redirects=False,
    )
    assert added.status_code == 303, added.text

    page = http.get("/feed", headers=HTML)
    assert page.status_code == 200, page.text
    assert f'action="/saved/{report_id}/unsave"' in page.text

    saved_page = http.get("/saved", headers=HTML)
    assert saved_page.status_code == 200, saved_page.text
    assert f'href="/shared/{report_id}"' in saved_page.text

    csrf = _page_csrf(http)
    removed = http.post(
        f"/saved/{report_id}/unsave",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert removed.status_code == 303, removed.text

    page = http.get("/feed", headers=HTML)
    assert page.status_code == 200, page.text
    assert f'action="/saved/{report_id}/unsave"' not in page.text
    saved_page = http.get("/saved", headers=HTML)
    assert "No saved vouches yet" in saved_page.text


def test_feed_page_shows_shared_fields_only(monkeypatch, tmp_path):
    http, dirs, owner_headers, report_id = _setup_owner_with_report(
        monkeypatch, tmp_path
    )
    _page_login(http, OWNER_EMAIL)
    page = http.get("/feed", headers=HTML)
    assert page.status_code == 200, page.text
    assert OWNER_EMAIL not in page.text
    assert OTHER_EMAIL not in page.text
    assert str(LAT) not in page.text
    assert str(LNG) not in page.text
    assert "/uploads/" not in page.text.replace("\\", "/")
    assert "mailto:" not in page.text.lower()
    assert "location_lat" not in page.text


def test_avatar_row_has_no_dead_profile_link(monkeypatch, tmp_path):
    http, dirs, owner_headers, report_id = _setup_owner_with_report(
        monkeypatch, tmp_path
    )
    _page_login(http, OWNER_EMAIL)
    page = http.get("/feed", headers=HTML)
    assert page.status_code == 200, page.text
    assert "Member " in page.text
    assert "/profile" not in page.text
    assert "href=\"/profile" not in page.text


def test_empty_state_with_map_button(monkeypatch, tmp_path):
    http, dirs = _make_client(monkeypatch, tmp_path)
    _verified_account(http, dirs, OWNER_EMAIL)
    _page_login(http, OWNER_EMAIL)
    page = http.get("/feed", headers=HTML)
    assert page.status_code == 200, page.text
    assert "No vouches to show yet" in page.text
    assert 'href="/map"' in page.text
    assert "Explore Map" in page.text
    assert "/shared/" not in page.text
    assert "<script" not in page.text.lower()


def test_nearby_distance_shown_only_with_viewer_location(
    monkeypatch, tmp_path
):
    http, dirs = _make_client(monkeypatch, tmp_path)
    owner_headers, _ = _verified_account(http, dirs, OWNER_EMAIL)
    near = _upload(
        http, owner_headers, _fresh_jpeg_bytes(seed=421),
        OWNER_CLAIM, "feed-nearby-near",
    )
    far = _upload(
        http, owner_headers, _fresh_jpeg_bytes(seed=422),
        "a far away street scene", "feed-nearby-far",
        lat=FAR_LAT, lng=FAR_LNG, title="Far corner",
    )
    _page_login(http, OWNER_EMAIL)

    plain = http.get("/feed?view=nearby", headers=HTML)
    assert plain.status_code == 200, plain.text
    assert "away" not in plain.text

    located = http.get(
        f"/feed?view=nearby&lat={LAT}&lng={LNG}", headers=HTML
    )
    assert located.status_code == 200, located.text
    assert "away" in located.text
    # Nearest first when the viewer location is known.
    assert located.text.index(f"/shared/{near['report_id']}") < (
        located.text.index(f"/shared/{far['report_id']}")
    )
    # Exact coordinates never leak, even with a viewer location.
    assert str(LAT) not in located.text
    assert str(LNG) not in located.text
    assert str(FAR_LAT) not in located.text
    assert str(FAR_LNG) not in located.text


def test_feed_tab_present_with_no_dead_links(monkeypatch, tmp_path):
    http, dirs, _, _ = _setup_owner_with_report(monkeypatch, tmp_path)
    _page_login(http, OWNER_EMAIL)
    page = http.get("/feed", headers=HTML)
    assert page.status_code == 200, page.text
    # Every tab-bar target exists for a logged-in viewer.
    for target in ("/feed", "/map", "/upload", "/saved", "/account"):
        assert f'href="{target}"' in page.text, target
        target_page = http.get(target, headers=HTML)
        assert target_page.status_code == 200, target
    # Unapproved routes stay unlinked.
    for missing in ("/profile", "/search", "/notifications",
                    "Following"):
        assert missing not in page.text, missing


def test_pending_reports_never_appear(monkeypatch, tmp_path):
    http, dirs, owner_headers, report_id = _setup_owner_with_report(
        monkeypatch, tmp_path
    )
    conn = connect(str(dirs["db"]))
    try:
        account_id = conn.execute(
            "SELECT id FROM accounts WHERE email = ?",
            (OWNER_EMAIL,),
        ).fetchone()["id"]
        pending_id, _ = create_report(
            conn,
            account_id=account_id,
            client_report_id="feed-pending-1",
            location_lat=LAT,
            location_lng=LNG,
            location_consented=1,
            location_source="browser",
        )
    finally:
        conn.close()
    _page_login(http, OWNER_EMAIL)
    page = http.get("/feed", headers=HTML)
    assert page.status_code == 200, page.text
    assert f"/shared/{report_id}" in page.text
    assert f"/shared/{pending_id}" not in page.text
