"""Tests for Lite spec 6, objective 6.4: report detail page.

TestClient against tmp SQLite + tmp mail/uploads dirs only -- never
the real ``lite/data/`` directory. The CLIP encoder is always stubbed
through the ``create_app(clip_encoder=...)`` seam (fast; the live
model path is objective 2.5's, never here).

Covered here: both pages load for the right users (owner page stays
unreachable for others); the mini-map uses the jittered display
point (no exact coordinates, no address); vouch toggle + derived
counts; comment post/list + escaping + caps; Save syncs with /saved
state; owner Edit/Delete visible only to the owner and enforced
server-side (non-owner POST 403); Share control present.
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

TEST_SECRET = "test-jwt-secret-for-detail-tests-0123456789"
PASSWORD = "correct-horse-9"
ADULT_DOB = (date.today() - timedelta(days=365 * 30)).isoformat()

OWNER_EMAIL = "detail-owner@example.com"
OTHER_EMAIL = "detail-viewer@example.com"

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
    """Register, verify via console mail, log in; return Bearer [REDACTED]"""
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


def _page_csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "page has no CSRF token field"
    return match.group(1)


def _setup_owner_with_report(monkeypatch, tmp_path, seed=401):
    http, dirs = _make_client(monkeypatch, tmp_path)
    owner_headers = _verified_account(http, dirs, OWNER_EMAIL)
    other_headers = _verified_account(http, dirs, OTHER_EMAIL)
    upload = _upload(
        http,
        owner_headers,
        _fresh_jpeg_bytes(seed=seed),
        OWNER_CLAIM,
        f"detail-owner-{seed}",
    )
    assert "report_id" in upload, upload
    return http, dirs, owner_headers, other_headers, upload["report_id"]


def _setup_pending_report(monkeypatch, tmp_path):
    """One accepted report plus one row with no check row (pending)."""
    http, dirs, owner_headers, other_headers, report_id = (
        _setup_owner_with_report(monkeypatch, tmp_path)
    )
    conn = connect(str(dirs["db"]))
    try:
        account_id = conn.execute(
            "SELECT id FROM accounts WHERE email = ?",
            (OWNER_EMAIL,),
        ).fetchone()["id"]
        pending_id, created = create_report(
            conn,
            account_id=account_id,
            client_report_id="detail-pending-1",
            location_lat=LAT,
            location_lng=LNG,
            location_consented=1,
            location_source="browser",
        )
        assert created
    finally:
        conn.close()
    return http, dirs, owner_headers, other_headers, report_id, pending_id


def test_both_pages_load_for_right_users(monkeypatch, tmp_path):
    http, dirs, _, _, report_id = _setup_owner_with_report(
        monkeypatch, tmp_path
    )[:5]
    _page_login(http, OWNER_EMAIL)

    owner_page = http.get(f"/reports/{report_id}", headers=HTML)
    assert owner_page.status_code == 200, owner_page.text
    assert OWNER_CLAIM in owner_page.text
    assert "<img" in owner_page.text
    assert "Vouches (" in owner_page.text
    assert "Comments" in owner_page.text
    assert 'id="comment_form"' in owner_page.text
    assert 'id="action_row"' in owner_page.text

    http.cookies.clear()
    _page_login(http, OTHER_EMAIL)
    shared_page = http.get(f"/shared/{report_id}", headers=HTML)
    assert shared_page.status_code == 200, shared_page.text
    assert OWNER_CLAIM in shared_page.text
    assert "<img" in shared_page.text
    assert "Vouches (" in shared_page.text

    # Anonymous browsers go to login for both pages.
    http.cookies.clear()
    anon_shared = http.get(
        f"/shared/{report_id}", headers=HTML, follow_redirects=False
    )
    assert anon_shared.status_code == 303, anon_shared.text
    assert anon_shared.headers["location"] == "/login"
    anon_owner = http.get(
        f"/reports/{report_id}", headers=HTML, follow_redirects=False
    )
    assert anon_owner.status_code == 303, anon_owner.text
    assert anon_owner.headers["location"] == "/login"


def test_owner_page_blocked_for_other_accounts(monkeypatch, tmp_path):
    http, dirs, owner_headers, other_headers, report_id = (
        _setup_owner_with_report(monkeypatch, tmp_path)
    )
    # JSON owner contract unchanged: blocked for others (spec-2 test).
    blocked = http.get(f"/reports/{report_id}", headers=other_headers)
    assert blocked.status_code in (403, 404), blocked.text

    # HTML owner page is likewise unreachable for other accounts.
    _page_login(http, OTHER_EMAIL)
    page = http.get(f"/reports/{report_id}", headers=HTML)
    assert page.status_code in (403, 404), page.text
    assert OWNER_CLAIM not in page.text


def test_minimap_uses_jittered_point(monkeypatch, tmp_path):
    http, dirs, owner_headers, other_headers, report_id = (
        _setup_owner_with_report(monkeypatch, tmp_path)
    )
    shared = http.get(f"/shared/{report_id}", headers=other_headers)
    assert shared.status_code == 200, shared.text
    payload = shared.json()
    display = (payload["display_lat"], payload["display_lng"])
    assert tuple(display) != (LAT, LNG)

    _page_login(http, OTHER_EMAIL)
    for route in (f"/shared/{report_id}",):
        page = http.get(route, headers=HTML)
        assert page.status_code == 200, page.text
        body = page.text
        # Mini-map markup at the jittered point only.
        assert 'id="mini_map"' in body
        assert 'id="mini_fallback"' in body
        assert "Approximate location preview." in body
        # No exact coordinates and no street address anywhere new.
        assert str(LAT) not in body, body[:500]
        assert str(LNG) not in body, body[:500]
        assert "address" not in body.lower()
        assert OWNER_EMAIL not in body
        assert OTHER_EMAIL not in body
        assert "/uploads/" not in body.replace("\\", "/")

    http.cookies.clear()
    _page_login(http, OWNER_EMAIL)
    owner_page = http.get(f"/reports/{report_id}", headers=HTML)
    assert owner_page.status_code == 200, owner_page.text
    assert str(LAT) not in owner_page.text
    assert str(LNG) not in owner_page.text
    assert "address" not in owner_page.text.lower()


def test_vouch_toggle_and_derived_counts(monkeypatch, tmp_path):
    http, dirs, owner_headers, other_headers, report_id = (
        _setup_owner_with_report(monkeypatch, tmp_path)
    )
    # Vouch is idempotent: a repeat vouch keeps a single row.
    first = http.post(
        "/vouches", json={"report_id": report_id}, headers=other_headers
    )
    assert first.status_code == 200, first.text
    assert first.json() == {
        "ok": True,
        "vouched": True,
        "report_id": report_id,
        "vouch_count": 1,
    }
    repeat = http.post(
        "/vouches", json={"report_id": report_id}, headers=other_headers
    )
    assert repeat.status_code == 200, repeat.text
    assert repeat.json()["vouch_count"] == 1

    # A second account vouches: the derived count grows.
    owner_vouch = http.post(
        "/vouches", json={"report_id": report_id}, headers=owner_headers
    )
    assert owner_vouch.status_code == 200, owner_vouch.text
    assert owner_vouch.json()["vouch_count"] == 2

    # Unvouch drops back to one; unvouch again is a no-op success.
    removed = http.post(
        f"/vouches/{report_id}/unvouch", json={}, headers=other_headers
    )
    assert removed.status_code == 200, removed.text
    assert removed.json() == {
        "ok": True,
        "vouched": False,
        "report_id": report_id,
        "vouch_count": 1,
    }
    again = http.post(
        f"/vouches/{report_id}/unvouch", json={}, headers=other_headers
    )
    assert again.status_code == 200, again.text
    assert again.json()["vouch_count"] == 1

    # The page shows the derived count and the toggle state.
    _page_login(http, OWNER_EMAIL)
    page = http.get(f"/shared/{report_id}", headers=HTML)
    assert page.status_code == 200, page.text
    assert "Vouches (1)" in page.text
    assert "Vouched" in page.text
    assert f'action="/vouches/{report_id}/unvouch"' in page.text

    # Form toggle to zero vouches.
    csrf = _page_csrf(page.text)
    off = http.post(
        f"/vouches/{report_id}/unvouch",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert off.status_code == 303, off.text
    assert off.headers["location"] == f"/shared/{report_id}"
    empty = http.get(f"/shared/{report_id}", headers=HTML)
    assert "Vouches (0)" in empty.text
    assert "No vouches yet." in empty.text
    assert 'action="/vouches"' in empty.text

    # Form toggle back on.
    csrf = _page_csrf(empty.text)
    on = http.post(
        "/vouches",
        data={"report_id": str(report_id), "csrf_token": csrf},
        follow_redirects=False,
    )
    assert on.status_code == 303, on.text
    full = http.get(f"/shared/{report_id}", headers=HTML)
    assert "Vouches (1)" in full.text


def test_vouch_and_comment_need_accepted_report(monkeypatch, tmp_path):
    http, dirs, owner_headers, other_headers, report_id, pending_id = (
        _setup_pending_report(monkeypatch, tmp_path)
    )
    # Pending rows (no check row) are not vouchable/commentable.
    vouch = http.post(
        "/vouches", json={"report_id": pending_id}, headers=other_headers
    )
    assert vouch.status_code == 404, vouch.text
    unvouch = http.post(
        f"/vouches/{pending_id}/unvouch", json={}, headers=other_headers
    )
    assert unvouch.status_code == 404, unvouch.text
    comment = http.post(
        "/comments",
        json={"report_id": pending_id, "body": "hello"},
        headers=other_headers,
    )
    assert comment.status_code == 404, comment.text
    listed = http.get(
        f"/api/reports/{pending_id}/comments", headers=other_headers
    )
    assert listed.status_code == 404, listed.text
    missing = http.post(
        "/vouches", json={"report_id": 999999}, headers=other_headers
    )
    assert missing.status_code == 404, missing.text

    _page_login(http, OTHER_EMAIL)
    page = http.get(f"/shared/{report_id}", headers=HTML)
    csrf = _page_csrf(page.text)
    form_vouch = http.post(
        "/vouches",
        data={"report_id": str(pending_id), "csrf_token": csrf},
    )
    assert form_vouch.status_code == 404, form_vouch.text
    form_comment = http.post(
        "/comments",
        data={"report_id": str(pending_id), "body": "hi",
              "csrf_token": csrf},
    )
    assert form_comment.status_code == 404, form_comment.text


def test_comment_post_list_escaping_and_caps(monkeypatch, tmp_path):
    http, dirs, owner_headers, other_headers, report_id = (
        _setup_owner_with_report(monkeypatch, tmp_path)
    )
    first = http.post(
        "/comments",
        json={"report_id": report_id, "body": "comment-alpha"},
        headers=other_headers,
    )
    assert first.status_code == 200, first.text
    assert first.json()["ok"] is True
    assert first.json()["comment"]["body"] == "comment-alpha"
    second = http.post(
        "/comments",
        json={"report_id": report_id, "body": "comment-beta"},
        headers=owner_headers,
    )
    assert second.status_code == 200, second.text

    # Newest last in both the JSON list and the page.
    listed = http.get(
        f"/api/reports/{report_id}/comments", headers=other_headers
    )
    assert listed.status_code == 200, listed.text
    assert listed.json() == {
        "report_id": report_id,
        "comments": [
            {"id": first.json()["comment"]["id"],
             "body": "comment-alpha",
             "created_at": first.json()["comment"]["created_at"]},
            {"id": second.json()["comment"]["id"],
             "body": "comment-beta",
             "created_at": second.json()["comment"]["created_at"]},
        ],
    }
    assert OWNER_EMAIL not in listed.text
    assert OTHER_EMAIL not in listed.text

    _page_login(http, OTHER_EMAIL)
    page = http.get(f"/shared/{report_id}", headers=HTML)
    assert page.status_code == 200, page.text
    assert "comment-alpha" in page.text
    assert "comment-beta" in page.text
    assert page.text.index("comment-alpha") < page.text.index(
        "comment-beta"
    )

    # HTML in a comment is escaped plain text, never markup.
    evil = "<b>bold</b> & <script>alert(1)</script>"
    posted = http.post(
        "/comments",
        json={"report_id": report_id, "body": evil},
        headers=other_headers,
    )
    assert posted.status_code == 200, posted.text
    rendered = http.get(f"/shared/{report_id}", headers=HTML)
    assert rendered.status_code == 200, rendered.text
    assert evil not in rendered.text
    assert "&lt;b&gt;bold&lt;/b&gt;" in rendered.text
    assert "&lt;script&gt;" in rendered.text

    # Empty bodies and over-long bodies are rejected (both modes).
    empty = http.post(
        "/comments",
        json={"report_id": report_id, "body": "   "},
        headers=other_headers,
    )
    assert empty.status_code == 422, empty.text
    long_body = http.post(
        "/comments",
        json={"report_id": report_id, "body": "x" * 501},
        headers=other_headers,
    )
    assert long_body.status_code == 422, long_body.text
    capped = http.post(
        "/comments",
        json={"report_id": report_id, "body": "y" * 500},
        headers=other_headers,
    )
    assert capped.status_code == 200, capped.text

    csrf = _page_csrf(rendered.text)
    form_empty = http.post(
        "/comments",
        data={"report_id": str(report_id), "body": "  ",
              "csrf_token": csrf},
    )
    assert form_empty.status_code == 422, form_empty.text
    assert "Write a comment" in form_empty.text
    form_long = http.post(
        "/comments",
        data={"report_id": str(report_id), "body": "z" * 501,
              "csrf_token": csrf},
    )
    assert form_long.status_code == 422, form_long.text

    # Anonymous callers cannot comment.
    http.cookies.clear()
    anon = http.post(
        "/comments",
        json={"report_id": report_id, "body": "hi"},
    )
    assert anon.status_code == 401, anon.text


def test_save_syncs_with_saved_state(monkeypatch, tmp_path):
    http, dirs, owner_headers, other_headers, report_id = (
        _setup_owner_with_report(monkeypatch, tmp_path)
    )
    saved = http.post(
        "/saved", json={"report_id": report_id}, headers=other_headers
    )
    assert saved.status_code == 200, saved.text

    _page_login(http, OTHER_EMAIL)
    page = http.get(f"/shared/{report_id}", headers=HTML)
    assert page.status_code == 200, page.text
    assert f'action="/saved/{report_id}/unsave"' in page.text
    assert "Unsave" in page.text

    # Unsave through the detail form flips the control back to Save.
    csrf = _page_csrf(page.text)
    removed = http.post(
        f"/saved/{report_id}/unsave",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert removed.status_code == 303, removed.text
    flipped = http.get(f"/shared/{report_id}", headers=HTML)
    assert flipped.status_code == 200, flipped.text
    assert 'action="/saved"' in flipped.text
    assert ">Save</button>" in flipped.text

    gone = http.get("/saved", headers=HTML)
    assert gone.status_code == 200, gone.text
    assert "No saved vouches yet" in gone.text


def test_edit_delete_visible_only_to_owner(monkeypatch, tmp_path):
    http, dirs, owner_headers, other_headers, report_id = (
        _setup_owner_with_report(monkeypatch, tmp_path)
    )
    _page_login(http, OWNER_EMAIL)
    owner_page = http.get(f"/reports/{report_id}", headers=HTML)
    assert owner_page.status_code == 200, owner_page.text
    assert 'id="edit_form"' in owner_page.text
    assert 'id="delete_form"' in owner_page.text
    assert f'action="/reports/{report_id}/edit"' in owner_page.text
    assert f'action="/reports/{report_id}/delete"' in owner_page.text

    http.cookies.clear()
    _page_login(http, OTHER_EMAIL)
    shared_page = http.get(f"/shared/{report_id}", headers=HTML)
    assert shared_page.status_code == 200, shared_page.text
    assert 'id="edit_form"' not in shared_page.text
    assert 'id="delete_form"' not in shared_page.text


def test_edit_enforced_server_side(monkeypatch, tmp_path):
    http, dirs, owner_headers, other_headers, report_id = (
        _setup_owner_with_report(monkeypatch, tmp_path)
    )
    # Non-owner POSTs answer 403 in both modes.
    denied_json = http.post(
        f"/reports/{report_id}/edit",
        json={"claim_text": "hijacked"},
        headers=other_headers,
    )
    assert denied_json.status_code == 403, denied_json.text

    _page_login(http, OTHER_EMAIL)
    page = http.get(f"/shared/{report_id}", headers=HTML)
    denied_form = http.post(
        f"/reports/{report_id}/edit",
        data={"claim_text": "hijacked", "csrf_token": _page_csrf(page.text)},
    )
    assert denied_form.status_code == 403, denied_form.text
    assert "Only the owner" in denied_form.text

    # The description is unchanged after the denied attempts.
    kept = http.get(f"/shared/{report_id}", headers=other_headers)
    assert kept.status_code == 200, kept.text
    assert kept.json()["claim_text"] == OWNER_CLAIM

    # The owner edits the description; both pages show the new text.
    edited = http.post(
        f"/reports/{report_id}/edit",
        json={"claim_text": "updated description"},
        headers=owner_headers,
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["claim_text"] == "updated description"

    changed = http.get(f"/shared/{report_id}", headers=other_headers)
    assert changed.json()["claim_text"] == "updated description"

    _page_login(http, OWNER_EMAIL)
    owner_page = http.get(f"/reports/{report_id}", headers=HTML)
    assert "updated description" in owner_page.text
    csrf = _page_csrf(owner_page.text)
    form_edit = http.post(
        f"/reports/{report_id}/edit",
        data={"claim_text": "form description", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert form_edit.status_code == 303, form_edit.text
    assert form_edit.headers["location"] == f"/reports/{report_id}"
    again = http.get(f"/reports/{report_id}", headers=HTML)
    assert "form description" in again.text

    # Over-long descriptions are rejected.
    too_long = http.post(
        f"/reports/{report_id}/edit",
        json={"claim_text": "q" * 2001},
        headers=owner_headers,
    )
    assert too_long.status_code == 422, too_long.text


def test_delete_enforced_server_side(monkeypatch, tmp_path):
    http, dirs, owner_headers, other_headers, report_id = (
        _setup_owner_with_report(monkeypatch, tmp_path)
    )
    # Non-owner POSTs answer 403 in both modes.
    denied_json = http.post(
        f"/reports/{report_id}/delete",
        json={"confirm": "yes"},
        headers=other_headers,
    )
    assert denied_json.status_code == 403, denied_json.text

    _page_login(http, OTHER_EMAIL)
    page = http.get(f"/shared/{report_id}", headers=HTML)
    denied_form = http.post(
        f"/reports/{report_id}/delete",
        data={"confirm": "yes", "csrf_token": _page_csrf(page.text)},
    )
    assert denied_form.status_code == 403, denied_form.text

    # Missing confirm keeps the report, with an error (confirm-once).
    _page_login(http, OWNER_EMAIL)
    owner_page = http.get(f"/reports/{report_id}", headers=HTML)
    nag = http.post(
        f"/reports/{report_id}/delete",
        data={"csrf_token": _page_csrf(owner_page.text)},
    )
    assert nag.status_code == 400, nag.text
    assert "confirmation box" in nag.text
    assert http.get(
        f"/reports/{report_id}", headers=owner_headers
    ).status_code == 200

    # Confirm deletes: owner list, shared, photo, and comments go 404.
    done = http.post(
        f"/reports/{report_id}/delete",
        data={"confirm": "yes",
              "csrf_token": _page_csrf(nag.text)},
        follow_redirects=False,
    )
    assert done.status_code == 303, done.text
    assert done.headers["location"] == "/reports"
    assert http.get(
        f"/reports/{report_id}", headers=owner_headers
    ).status_code == 404
    gone_page = http.get(f"/reports/{report_id}", headers=HTML)
    assert gone_page.status_code == 404, gone_page.text
    assert http.get(
        f"/shared/{report_id}", headers=other_headers
    ).status_code == 404
    assert http.get(
        f"/api/photos/{report_id}", headers=other_headers
    ).status_code == 404
    assert http.get(
        f"/api/reports/{report_id}/comments", headers=other_headers
    ).status_code == 404


def test_share_control_present(monkeypatch, tmp_path):
    http, dirs, owner_headers, other_headers, report_id = (
        _setup_owner_with_report(monkeypatch, tmp_path)
    )
    _page_login(http, OTHER_EMAIL)
    page = http.get(f"/shared/{report_id}", headers=HTML)
    assert page.status_code == 200, page.text
    # Polish hook plus a no-JS fallback link showing the URL text.
    assert "navigator.share" in page.text
    assert 'id="share_link"' in page.text
    assert f'href="/shared/{report_id}"' in page.text
    assert f">/shared/{report_id}</a>" in page.text
    # At most one inline script block on the page (plus the single
    # allowlisted map-library src).
    opens = re.findall(r"<script\b[^>]*>", page.text)
    closes = re.findall(r"</script\s*>", page.text)
    assert len(opens) == len(closes) == 2, page.text
    inline = [tag for tag in opens if "src=" not in tag]
    assert len(inline) == 1, page.text
