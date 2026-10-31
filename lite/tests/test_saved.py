"""Tests for Lite spec 6, objective 6.6: saved places.

TestClient against tmp SQLite + tmp mail/uploads dirs only -- never
the real ``lite/data/`` directory. The CLIP encoder is always stubbed
through the ``create_app(clip_encoder=...)`` seam (fast; the live
model path is objective 2.5's, never here).

Endpoints under test: ``GET /saved`` (login required, redirect to
``/login`` when logged out), ``POST /saved`` (save toggle-add, form
or JSON), and ``POST /saved/{id}/unsave`` (remove, no-op success
when the save is missing).
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

TEST_SECRET = "test-jwt-secret-for-saved-tests-0123456789"
PASSWORD = "correct-horse-9"
ADULT_DOB = (date.today() - timedelta(days=365 * 30)).isoformat()

OWNER_EMAIL = "saver@example.com"
OTHER_EMAIL = "bystander@example.com"

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


def _upload(http, headers, raw, claim, client_id):
    resp = http.post(
        "/analyze",
        data={
            "client_report_id": client_id,
            "location_lat": str(LAT),
            "location_lng": str(LNG),
            "location_consented": "true",
            "location_source": "browser",
            "claim_text": claim,
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
    # Any page carrying a POST form echoes the CSRF cookie value; the
    # /saved page has no form while its list is empty, so use /account.
    page = http.get("/account", headers=HTML)
    assert page.status_code == 200, page.text
    match = re.search(
        r'name="csrf_token" value="([^"]+)"', page.text
    )
    assert match, "/account has no CSRF token field"
    return match.group(1)


def _setup_owner_with_report(monkeypatch, tmp_path, seed=201):
    http, dirs = _make_client(monkeypatch, tmp_path)
    owner_headers, _ = _verified_account(http, dirs, OWNER_EMAIL)
    upload = _upload(
        http,
        owner_headers,
        _fresh_jpeg_bytes(seed=seed),
        OWNER_CLAIM,
        f"saved-owner-{seed}",
    )
    assert "report_id" in upload, upload
    return http, dirs, owner_headers, upload["report_id"]


def test_saved_page_requires_login(monkeypatch, tmp_path):
    http, _ = _make_client(monkeypatch, tmp_path)
    page = http.get("/saved", headers=HTML, follow_redirects=False)
    assert page.status_code == 303, page.text
    assert page.headers["location"] == "/login"

    # Form POSTs check the CSRF token first (like every page POST),
    # so present a valid anonymous token to reach the login gate.
    login_page = http.get("/login", headers=HTML)
    assert login_page.status_code == 200, login_page.text
    match = re.search(
        r'name="csrf_token" value="([^"]+)"', login_page.text
    )
    assert match, "login page has no CSRF token field"
    token = match.group(1)

    added = http.post(
        "/saved",
        data={"report_id": "1", "csrf_token": token},
        follow_redirects=False,
    )
    assert added.status_code == 303, added.text
    assert added.headers["location"] == "/login"

    removed = http.post(
        "/saved/1/unsave",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert removed.status_code == 303, removed.text
    assert removed.headers["location"] == "/login"


def test_empty_state_with_map_button(monkeypatch, tmp_path):
    http, dirs, _, _ = _setup_owner_with_report(monkeypatch, tmp_path)
    _page_login(http, OWNER_EMAIL)
    page = http.get("/saved", headers=HTML)
    assert page.status_code == 200, page.text
    assert "Saved Places" in page.text
    assert "0 saved" in page.text
    assert "No saved vouches yet" in page.text
    assert 'href="/map"' in page.text
    assert "Explore Map" in page.text
    # Segmented List | Map toggle as plain links.
    assert 'href="/saved"' in page.text
    # No card links yet.
    assert "/shared/" not in page.text
    assert "<script" not in page.text.lower()


def test_save_adds_and_unsave_removes_via_forms(
    monkeypatch, tmp_path
):
    http, dirs, owner_headers, report_id = _setup_owner_with_report(
        monkeypatch, tmp_path
    )
    _page_login(http, OWNER_EMAIL)

    csrf = _page_csrf(http)
    added = http.post(
        "/saved",
        data={"report_id": str(report_id), "csrf_token": csrf},
        follow_redirects=False,
    )
    assert added.status_code == 303, added.text
    assert added.headers["location"] == "/saved"

    page = http.get("/saved", headers=HTML)
    assert page.status_code == 200, page.text
    assert "Saved Places" in page.text
    assert "1 saved" in page.text
    assert f'href="/shared/{report_id}"' in page.text
    assert f'src="/shared/photos/{report_id}"' in page.text
    assert OWNER_CLAIM in page.text
    assert "No saved vouches yet" not in page.text
    assert f'action="/saved/{report_id}/unsave"' in page.text

    csrf = _page_csrf(http)
    removed = http.post(
        f"/saved/{report_id}/unsave",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert removed.status_code == 303, removed.text

    page = http.get("/saved", headers=HTML)
    assert page.status_code == 200, page.text
    assert "0 saved" in page.text
    assert "No saved vouches yet" in page.text
    assert f"/shared/{report_id}" not in page.text


def test_save_is_idempotent(monkeypatch, tmp_path):
    http, dirs, owner_headers, report_id = _setup_owner_with_report(
        monkeypatch, tmp_path
    )
    first = http.post(
        "/saved", json={"report_id": report_id}, headers=owner_headers
    )
    assert first.status_code == 200, first.text
    second = http.post(
        "/saved", json={"report_id": report_id}, headers=owner_headers
    )
    assert second.status_code == 200, second.text
    assert second.json() == {
        "ok": True,
        "saved": True,
        "report_id": report_id,
    }
    _page_login(http, OWNER_EMAIL)
    page = http.get("/saved", headers=HTML)
    assert page.status_code == 200, page.text
    assert "1 saved" in page.text
    assert page.text.count(f"/shared/{report_id}") >= 1


def test_sync_across_json_endpoints_and_page(monkeypatch, tmp_path):
    http, dirs, owner_headers, report_id = _setup_owner_with_report(
        monkeypatch, tmp_path
    )
    saved = http.post(
        "/saved", json={"report_id": report_id}, headers=owner_headers
    )
    assert saved.status_code == 200, saved.text

    _page_login(http, OWNER_EMAIL)
    page = http.get("/saved", headers=HTML)
    assert page.status_code == 200, page.text
    assert f'href="/shared/{report_id}"' in page.text

    removed = http.post(
        f"/saved/{report_id}/unsave", json={}, headers=owner_headers
    )
    assert removed.status_code == 200, removed.text
    assert removed.json() == {
        "ok": True,
        "saved": False,
        "report_id": report_id,
    }
    page = http.get("/saved", headers=HTML)
    assert page.status_code == 200, page.text
    assert "No saved vouches yet" in page.text


def test_save_missing_or_unaccepted_report_404s(monkeypatch, tmp_path):
    http, dirs, owner_headers, _ = _setup_owner_with_report(
        monkeypatch, tmp_path
    )
    missing = http.post(
        "/saved", json={"report_id": 999999}, headers=owner_headers
    )
    assert missing.status_code == 404, missing.text

    _page_login(http, OWNER_EMAIL)
    csrf = _page_csrf(http)
    form_missing = http.post(
        "/saved",
        data={"report_id": "999999", "csrf_token": csrf},
    )
    assert form_missing.status_code == 404, form_missing.text

    # A report row with no accepted check row cannot be saved.
    conn = connect(str(dirs["db"]))
    try:
        account_id = conn.execute(
            "SELECT id FROM accounts WHERE email = ?",
            (OWNER_EMAIL,),
        ).fetchone()["id"]
        pending_id, _ = create_report(
            conn,
            account_id=account_id,
            client_report_id="saved-pending-1",
            location_lat=LAT,
            location_lng=LNG,
            location_consented=1,
            location_source="browser",
        )
    finally:
        conn.close()
    pending = http.post(
        "/saved", json={"report_id": pending_id}, headers=owner_headers
    )
    assert pending.status_code == 404, pending.text


def test_unsave_missing_save_is_noop_success(monkeypatch, tmp_path):
    http, dirs, owner_headers, _ = _setup_owner_with_report(
        monkeypatch, tmp_path
    )
    missing = http.post(
        "/saved/999999/unsave", json={}, headers=owner_headers
    )
    assert missing.status_code == 200, missing.text
    assert missing.json()["ok"] is True

    _page_login(http, OWNER_EMAIL)
    csrf = _page_csrf(http)
    form_missing = http.post(
        "/saved/999999/unsave",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert form_missing.status_code == 303, form_missing.text
    page = http.get("/saved", headers=HTML)
    assert page.status_code == 200, page.text
    assert "No saved vouches yet" in page.text


def test_saves_are_per_account(monkeypatch, tmp_path):
    http, dirs = _make_client(monkeypatch, tmp_path)
    owner_headers, _ = _verified_account(http, dirs, OWNER_EMAIL)
    other_headers, _ = _verified_account(http, dirs, OTHER_EMAIL)
    upload = _upload(
        http,
        owner_headers,
        _fresh_jpeg_bytes(seed=301),
        OWNER_CLAIM,
        "saved-isolation-1",
    )
    report_id = upload["report_id"]

    # The other account saves the shared report: allowed, but scoped.
    other_saved = http.post(
        "/saved", json={"report_id": report_id}, headers=other_headers
    )
    assert other_saved.status_code == 200, other_saved.text

    _page_login(http, OWNER_EMAIL)
    owner_page = http.get("/saved", headers=HTML)
    assert owner_page.status_code == 200, owner_page.text
    assert "No saved vouches yet" in owner_page.text

    http.cookies.clear()
    _page_login(http, OTHER_EMAIL)
    other_page = http.get("/saved", headers=HTML)
    assert other_page.status_code == 200, other_page.text
    assert f'href="/shared/{report_id}"' in other_page.text

    # The owner unsaving (a no-op: never saved) leaves the other's row.
    owner_unsave = http.post(
        f"/saved/{report_id}/unsave", json={}, headers=owner_headers
    )
    assert owner_unsave.status_code == 200, owner_unsave.text
    other_page = http.get("/saved", headers=HTML)
    assert f'href="/shared/{report_id}"' in other_page.text


def test_saved_page_shows_shared_fields_only(monkeypatch, tmp_path):
    http, dirs, owner_headers, report_id = _setup_owner_with_report(
        monkeypatch, tmp_path
    )
    saved = http.post(
        "/saved", json={"report_id": report_id}, headers=owner_headers
    )
    assert saved.status_code == 200, saved.text

    _page_login(http, OWNER_EMAIL)
    page = http.get("/saved", headers=HTML)
    assert page.status_code == 200, page.text
    assert OWNER_EMAIL not in page.text
    assert OTHER_EMAIL not in page.text
    assert str(LAT) not in page.text
    assert str(LNG) not in page.text
    assert "/uploads/" not in page.text.replace("\\", "/")
    assert "mailto:" not in page.text.lower()
