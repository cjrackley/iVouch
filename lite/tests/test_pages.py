"""Tests for Lite spec 3, objective 3.1: account pages.

TestClient against tmp SQLite + tmp mail/uploads dirs only -- never
the real ``lite/data/`` directory. The JWT secret comes from the
``LITE_JWT_SECRET`` env var (set per-test here).
"""

from __future__ import annotations

import re
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from lite.app.server.api import (
    GENERIC_LOGIN_DETAIL,
    GENERIC_REGISTER_MESSAGE,
    create_app,
)
from lite.app.server.db import connect

TEST_SECRET = "test-jwt-secret-for-pages-tests-0123456789"
PASSWORD = "correct-horse-9"
ADULT_DOB = (date.today() - timedelta(days=365 * 30)).isoformat()
TEEN_DOB = (date.today() - timedelta(days=365 * 10)).isoformat()

HTML = {"Accept": "text/html"}


@pytest.fixture()
def secret(monkeypatch):
    monkeypatch.setenv("LITE_JWT_SECRET", TEST_SECRET)


@pytest.fixture()
def app_dirs(tmp_path):
    return {
        "db": tmp_path / "test.db",
        "mail": tmp_path / "mail",
        "uploads": tmp_path / "uploads",
    }


@pytest.fixture()
def client(secret, app_dirs):
    app = create_app(
        db_path=app_dirs["db"],
        mail_dir=app_dirs["mail"],
        uploads_dir=app_dirs["uploads"],
    )
    return TestClient(app), app_dirs


def _mail_tokens(mail_dir):
    tokens = []
    for path in sorted(mail_dir.glob("*.txt")):
        match = re.search(
            r"^token:\s*(\S+)\s*$",
            path.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        assert match, f"mail file {path.name} has no token line"
        tokens.append(match.group(1))
    return tokens


def _csrf_token(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "page has no CSRF token field"
    return match.group(1)


def _account_count(db_path) -> int:
    conn = connect(str(db_path))
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM accounts"
        ).fetchone()["n"]
    finally:
        conn.close()


def _signup_form(http, email, dob=ADULT_DOB):
    page = http.get("/signup", headers=HTML)
    assert page.status_code == 200, page.text
    return {
        "email": email,
        "password": PASSWORD,
        "date_of_birth": dob,
        "csrf_token": _csrf_token(page.text),
    }


def _login_form(http, email, password=PASSWORD):
    page = http.get("/login", headers=HTML)
    assert page.status_code == 200, page.text
    return {
        "email": email,
        "password": password,
        "csrf_token": _csrf_token(page.text),
    }


def test_signup_page_shows_gate_disclaimer_notice(client):
    http, _ = client
    page = http.get("/signup", headers=HTML)
    assert page.status_code == 200
    body = page.text
    # Age gate.
    assert 'name="date_of_birth"' in body
    # Demo disclaimer.
    assert "Demo build" in body
    assert "mock" in body
    # Data-use notice: shared vs never shared.
    for word in ("photo", "claim text", "approximate map location",
                 "verdict"):
        assert word in body
    assert "never" in body
    assert "email" in body.lower()
    assert "exact coordinates" in body
    assert "file paths" in body
    assert 'name="csrf_token"' in body


def test_signup_underage_rejected_generically_via_api(client):
    http, dirs = client
    resp = http.post(
        "/signup", data=_signup_form(http, "teen@example.com", TEEN_DOB)
    )
    assert resp.status_code == 200, resp.text
    assert GENERIC_REGISTER_MESSAGE in resp.text
    assert _account_count(dirs["db"]) == 0
    assert list(dirs["mail"].glob("*.txt")) == []


def test_signup_adult_creates_account_with_generic_reply(client):
    http, dirs = client
    resp = http.post(
        "/signup", data=_signup_form(http, "grown@example.com")
    )
    assert resp.status_code == 200, resp.text
    assert GENERIC_REGISTER_MESSAGE in resp.text
    assert _account_count(dirs["db"]) == 1
    assert len(_mail_tokens(dirs["mail"])) == 1


def test_login_sets_httponly_session_cookie(client):
    http, dirs = client
    assert http.post(
        "/auth/register",
        json={
            "email": "member@example.com",
            "password": PASSWORD,
            "date_of_birth": ADULT_DOB,
        },
    ).status_code == 200
    resp = http.post(
        "/login",
        data=_login_form(http, "member@example.com"),
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    assert resp.headers["location"] == "/account"
    jar = resp.headers.get_list("set-cookie")
    session = [c for c in jar if c.startswith("lite_session=")]
    assert session, jar
    assert "httponly" in session[0].lower()
    value = session[0].split(";", 1)[0].split("=", 1)[1]
    assert len(value.split(".")) == 3  # the spec-2 JWT

    # The cookie authenticates the account page.
    page = http.get("/account", headers=HTML)
    assert page.status_code == 200, page.text
    assert "member@example.com" in page.text


def test_login_failure_is_generic(client):
    http, _ = client
    assert http.post(
        "/auth/register",
        json={
            "email": "m@example.com",
            "password": PASSWORD,
            "date_of_birth": ADULT_DOB,
        },
    ).status_code == 200
    resp = http.post(
        "/login", data=_login_form(http, "m@example.com", "wrong-pass-1")
    )
    assert resp.status_code == 401, resp.text
    assert GENERIC_LOGIN_DETAIL in resp.text


def _post_forms(html: str) -> list:
    forms = re.findall(
        r"<form\b.*?</form>", html, flags=re.IGNORECASE | re.DOTALL
    )
    return [
        form
        for form in forms
        if re.search(r'method\s*=\s*["\']?post', form, re.IGNORECASE)
    ]


def test_every_post_form_has_csrf_token_field(client):
    http, _ = client
    assert http.post(
        "/auth/register",
        json={
            "email": "forms@example.com",
            "password": PASSWORD,
            "date_of_birth": ADULT_DOB,
        },
    ).status_code == 200
    http.post(
        "/login", data=_login_form(http, "forms@example.com")
    )
    pages = [
        http.get("/signup", headers=HTML).text,
        http.get("/login", headers=HTML).text,
        http.get("/account", headers=HTML).text,
        http.get("/upload", headers=HTML).text,
    ]
    assert any(_post_forms(page) for page in pages)
    for page in pages:
        for form in _post_forms(page):
            assert 'name="csrf_token"' in form, form[:200]


def test_posts_without_csrf_token_are_rejected(client):
    http, _ = client
    http.cookies.clear()
    assert http.post(
        "/signup",
        data={
            "email": "x@example.com",
            "password": PASSWORD,
            "date_of_birth": ADULT_DOB,
        },
    ).status_code == 403
    assert http.post(
        "/login",
        data={"email": "x@example.com", "password": PASSWORD},
    ).status_code == 403
    assert http.post("/account/delete").status_code == 403
    assert http.post("/verify-resend").status_code == 403
    # All rejected: nothing was stored (schema is lazy, so ensure it first).
    from lite.app.server.db import init_db

    init_db(str(client[1]["db"]))
    assert _account_count(client[1]["db"]) == 0
    assert list(client[1]["mail"].glob("*.txt")) == []


def test_unverified_upload_landing_shows_verify_prompt(client):
    http, dirs = client
    assert http.post(
        "/auth/register",
        json={
            "email": "new@example.com",
            "password": PASSWORD,
            "date_of_birth": ADULT_DOB,
        },
    ).status_code == 200
    http.post("/login", data=_login_form(http, "new@example.com"))
    landing = http.get("/upload", headers=HTML)
    assert landing.status_code == 200, landing.text
    assert "verify your email" in landing.text
    assert 'name="csrf_token"' in landing.text

    # Resend action writes a fresh verification mail.
    before = len(_mail_tokens(dirs["mail"]))
    resend = http.post(
        "/verify-resend",
        data={"csrf_token": _csrf_token(landing.text)},
    )
    assert resend.status_code == 200, resend.text
    assert len(_mail_tokens(dirs["mail"])) == before + 1

    # After verifying, the gate lifts.
    token = _mail_tokens(dirs["mail"])[-1]
    assert http.post(
        "/auth/verify-email", json={"token": token}
    ).status_code == 200
    http.cookies.clear()
    http.post("/login", data=_login_form(http, "new@example.com"))
    lifted = http.get("/upload", headers=HTML)
    assert lifted.status_code == 200, lifted.text
    assert "verify your email" not in lifted.text


def test_account_page_and_delete_flow(client):
    http, dirs = client
    assert http.post(
        "/auth/register",
        json={
            "email": "leaver@example.com",
            "password": PASSWORD,
            "date_of_birth": ADULT_DOB,
        },
    ).status_code == 200
    token = _mail_tokens(dirs["mail"])[0]
    assert http.post(
        "/auth/verify-email", json={"token": token}
    ).status_code == 200
    login = http.post(
        "/auth/login",
        json={"email": "leaver@example.com", "password": PASSWORD},
    ).json()
    api_headers = {
        "Authorization": f"Bearer {login['access_token']}"
    }
    http.post("/login", data=_login_form(http, "leaver@example.com"))

    page = http.get("/account", headers=HTML)
    assert page.status_code == 200, page.text
    assert "leaver@example.com" in page.text
    assert "verified" in page.text
    assert 'action="/account/delete"' in page.text

    # Single confirm missing -> stays, with an error.
    csrf = _csrf_token(page.text)
    nag = http.post("/account/delete", data={"csrf_token": csrf})
    assert nag.status_code == 400, nag.text
    assert _account_count(dirs["db"]) == 1

    # Confirm -> deleted, back at login.
    done = http.post(
        "/account/delete",
        data={"csrf_token": csrf, "confirm": "yes"},
        follow_redirects=False,
    )
    assert done.status_code == 303, done.text
    assert done.headers["location"] == "/login"
    assert _account_count(dirs["db"]) == 0
    assert http.get("/account", headers=api_headers).status_code == 401
    relogin = http.post(
        "/auth/login",
        json={"email": "leaver@example.com", "password": PASSWORD},
    )
    assert relogin.status_code == 401


def test_verify_landing_posts_to_verify_api(client):
    http, dirs = client
    assert http.post(
        "/auth/register",
        json={
            "email": "vv@example.com",
            "password": PASSWORD,
            "date_of_birth": ADULT_DOB,
        },
    ).status_code == 200
    token = _mail_tokens(dirs["mail"])[0]

    # No query -> token entry form, no result yet.
    blank = http.get("/verify", headers=HTML)
    assert blank.status_code == 200
    assert 'name="token"' in blank.text

    # Valid token query -> verified result.
    good = http.get(f"/verify?token={token}", headers=HTML)
    assert good.status_code == 200, good.text
    assert "Email verified." in good.text

    # Bad token -> error result.
    bad = http.get("/verify?token=garbage", headers=HTML)
    assert bad.status_code == 200, bad.text
    assert "Invalid or expired verification token." in bad.text


def test_logout_clears_session_cookie(client):
    http, _ = client
    assert http.post(
        "/auth/register",
        json={
            "email": "bye@example.com",
            "password": PASSWORD,
            "date_of_birth": ADULT_DOB,
        },
    ).status_code == 200
    http.post("/login", data=_login_form(http, "bye@example.com"))
    assert http.get("/account", headers=HTML).status_code == 200
    out = http.get("/logout", headers=HTML, follow_redirects=False)
    assert out.status_code == 303
    assert out.headers["location"] == "/login"
    assert http.get(
        "/account", headers=HTML, follow_redirects=False
    ).status_code == 303


def test_api_account_json_contract_preserved(client):
    http, _ = client
    assert http.post(
        "/auth/register",
        json={
            "email": "json@example.com",
            "password": PASSWORD,
            "date_of_birth": ADULT_DOB,
        },
    ).status_code == 200
    login = http.post(
        "/auth/login",
        json={"email": "json@example.com", "password": PASSWORD},
    ).json()
    me = http.get(
        "/account",
        headers={"Authorization": f"Bearer {login['access_token']}"},
    )
    assert me.status_code == 200
    assert set(me.json()) == {
        "id", "email", "email_verified", "status", "created_at",
    }
    anon = http.get("/account")
    assert anon.status_code == 401
    assert anon.json() == {"detail": "Not authenticated."}
