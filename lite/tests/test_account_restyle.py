"""Tests for Lite spec 6, objective 6.8: account/profile restyle.

Own profile only (user decision 2026-10-31): no Edit Profile, no
name/bio/avatar editing, no Following stat, no Activity tab, and no
``/profile/{id}`` route. TestClient against tmp SQLite + tmp
mail/uploads dirs only -- never the real ``lite/data/`` directory.
The CLIP encoder is always stubbed through the
``create_app(clip_encoder=...)`` seam (fast; the live model path is
objective 2.5's, never here).
"""

from __future__ import annotations

import io
import random
import re
from datetime import date, timedelta
from pathlib import Path

from PIL import Image

from lite.app.server.api import create_app
from lite.app.server.db import connect, make_reviewer

TEST_SECRET = "test-jwt-secret-for-account-restyle-0123456789"
PASSWORD = "correct-horse-9"
ADULT_DOB = (date.today() - timedelta(days=365 * 30)).isoformat()

OWNER_EMAIL = "restyle-owner@example.com"
OTHER_EMAIL = "restyle-bystander@example.com"

LAT = 51.50745
LNG = -0.12762
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
    """Register, verify via console mail, log in; return headers."""
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
    return headers


def _upload(http, headers, raw, claim, client_id, title="Corner shop front"):
    resp = http.post(
        "/analyze",
        data={
            "client_report_id": client_id,
            "location_lat": str(LAT),
            "location_lng": str(LNG),
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


def _setup_owner_with_reports(monkeypatch, tmp_path):
    """Owner with two accepted reports, first one saved."""
    http, dirs = _make_client(monkeypatch, tmp_path)
    owner_headers = _verified_account(http, dirs, OWNER_EMAIL)
    first = _upload(
        http, owner_headers, _fresh_jpeg_bytes(seed=501),
        OWNER_CLAIM, "restyle-owner-1", title="Corner shop front",
    )
    second = _upload(
        http, owner_headers, _fresh_jpeg_bytes(seed=502),
        "another street scene with shapes", "restyle-owner-2",
        title="Bus stop mural",
    )
    assert "report_id" in first and "report_id" in second, (
        first, second,
    )
    saved = http.post(
        "/saved", json={"report_id": first["report_id"]},
        headers=owner_headers,
    )
    assert saved.status_code == 200, saved.text
    return http, dirs, owner_headers, first["report_id"], second["report_id"]


def test_profile_layout_fields_present(monkeypatch, tmp_path):
    http, dirs = _make_client(monkeypatch, tmp_path)
    _verified_account(http, dirs, OWNER_EMAIL)
    _page_login(http, OWNER_EMAIL)
    page = http.get("/account", headers=HTML)
    assert page.status_code == 200, page.text
    # Avatar: 80px circle with the account initial, no upload control.
    assert 'class="account-avatar"' in page.text
    assert "80px" in page.text
    assert ">R</span>" in page.text
    assert 'type="file"' not in page.text
    # Name: existing display identifier at 20px weight 700.
    assert 'class="account-name"' in page.text
    assert OWNER_EMAIL in page.text
    assert "20px" in page.text
    assert "700" in page.text
    # Verified state and no scripts.
    assert "Email status:" in page.text
    assert "<script" not in page.text.lower()


def test_stats_row_vouches_and_saved_counts(monkeypatch, tmp_path):
    http, dirs, _, _, _ = _setup_owner_with_reports(
        monkeypatch, tmp_path
    )
    _page_login(http, OWNER_EMAIL)
    page = http.get("/account", headers=HTML)
    assert page.status_code == 200, page.text
    assert re.search(
        r'class="account-stat-value">2</span>\s*'
        r'<span class="account-stat-label">Vouches</span>',
        page.text,
    ), page.text
    assert re.search(
        r'class="account-stat-value">1</span>\s*'
        r'<span class="account-stat-label">Saved</span>',
        page.text,
    ), page.text
    # Exactly two stat columns: no Following column.
    assert "Following" not in page.text
    assert page.text.count('<span class="account-stat-value">') == 2


def test_tabs_my_pins_and_saved_without_activity(monkeypatch, tmp_path):
    http, dirs, _, _, _ = _setup_owner_with_reports(
        monkeypatch, tmp_path
    )
    _page_login(http, OWNER_EMAIL)
    page = http.get("/account", headers=HTML)
    assert page.status_code == 200, page.text
    assert "My Pins" in page.text
    assert "Saved" in page.text
    assert 'href="/account?tab=pins"' in page.text
    assert 'href="/account?tab=saved"' in page.text
    assert "Activity" not in page.text
    assert "Edit Profile" not in page.text
    assert "/profile" not in page.text


def test_my_pins_link_to_owner_reports(monkeypatch, tmp_path):
    http, dirs, _, first_id, second_id = _setup_owner_with_reports(
        monkeypatch, tmp_path
    )
    _page_login(http, OWNER_EMAIL)
    page = http.get("/account", headers=HTML)
    assert page.status_code == 200, page.text
    assert f'href="/reports/{first_id}"' in page.text
    assert f'href="/reports/{second_id}"' in page.text
    assert "Corner shop front" in page.text
    assert "Bus stop mural" in page.text
    # Pins tab shows owner links, not shared links.
    assert "/shared/" not in page.text


def test_saved_tab_mirrors_saved_places(monkeypatch, tmp_path):
    http, dirs, _, first_id, second_id = _setup_owner_with_reports(
        monkeypatch, tmp_path
    )
    _page_login(http, OWNER_EMAIL)
    page = http.get("/account?tab=saved", headers=HTML)
    assert page.status_code == 200, page.text
    assert f'href="/shared/{first_id}"' in page.text
    assert f'href="/reports/{second_id}"' not in page.text
    # Links to /saved instead of duplicating unsave logic.
    assert 'href="/saved"' in page.text
    assert f'action="/saved/{first_id}/unsave"' not in page.text
    assert "<script" not in page.text.lower()


def test_admin_link_reviewer_only(monkeypatch, tmp_path):
    http, dirs = _make_client(monkeypatch, tmp_path)
    _verified_account(http, dirs, OWNER_EMAIL)
    _page_login(http, OWNER_EMAIL)
    plain = http.get("/account", headers=HTML)
    assert plain.status_code == 200, plain.text
    assert "Admin" not in plain.text
    assert 'href="/review"' not in plain.text

    conn = connect(str(dirs["db"]))
    try:
        make_reviewer(conn, OWNER_EMAIL)
    finally:
        conn.close()
    gated = http.get("/account", headers=HTML)
    assert gated.status_code == 200, gated.text
    assert "Admin" in gated.text
    assert 'href="/review"' in gated.text


def test_delete_confirm_present_at_page_level(monkeypatch, tmp_path):
    http, dirs = _make_client(monkeypatch, tmp_path)
    _verified_account(http, dirs, OWNER_EMAIL)
    _page_login(http, OWNER_EMAIL)
    page = http.get("/account", headers=HTML)
    assert page.status_code == 200, page.text
    # Confirm-once flow untouched: same action, checkbox, and token.
    assert 'action="/account/delete"' in page.text
    assert 'name="confirm"' in page.text
    assert 'name="csrf_token"' in page.text
    assert 'href="/logout"' in page.text


def test_no_cross_account_email_leak(monkeypatch, tmp_path):
    http, dirs, owner_headers, first_id, _ = _setup_owner_with_reports(
        monkeypatch, tmp_path
    )
    other_headers = _verified_account(http, dirs, OTHER_EMAIL)
    # The other account saves the owner's report: allowed, but the
    # owner profile must never show the other account's email.
    other_saved = http.post(
        "/saved", json={"report_id": first_id}, headers=other_headers
    )
    assert other_saved.status_code == 200, other_saved.text

    _page_login(http, OWNER_EMAIL)
    for route in ("/account", "/account?tab=saved"):
        page = http.get(route, headers=HTML)
        assert page.status_code == 200, (route, page.text)
        assert OWNER_EMAIL in page.text
        assert OTHER_EMAIL not in page.text
        assert str(LAT) not in page.text
        assert str(LNG) not in page.text
        assert "mailto:" not in page.text.lower()
