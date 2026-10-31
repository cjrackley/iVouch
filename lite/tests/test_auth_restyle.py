"""Tests for Lite spec 6, objective 6.9: login/signup restyle.

Restyle only (user decision 2026-10-31): no OAuth buttons, no
forgot-password link, no auth-logic changes. TestClient against tmp
SQLite + tmp mail/uploads dirs only -- never the real ``lite/data/``
directory. No browser automation: page HTML and inline CSS classes
prove the centered onboarding structure on mobile and desktop widths.

Covered here:

* Centered onboarding: logo (32px bold), iOS-cell inputs, full-width
  48px gradient primary button, all text centered.
* Signup keeps the spec-3.1 age gate, demo disclaimer, and data-use
  notice; the form POSTs to the same target with the same field names.
* No Apple/Google OAuth or forgot-password markup, no scripts.
* Login error path still renders (same context keys/branches).
* Centering holds on mobile and desktop widths via CSS classes.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lite.app.server.api import (
    GENERIC_LOGIN_DETAIL,
    GENERIC_REGISTER_MESSAGE,
    create_app,
)

TEST_SECRET = "test-jwt-secret-for-auth-restyle-tests-0123456789"
PASSWORD = "correct-horse-9"
ADULT_DOB = (date.today() - timedelta(days=365 * 30)).isoformat()

HTML = {"Accept": "text/html"}
HEX_RE = re.compile(r"(?<!&)#[0-9A-Fa-f]{3,8}\b")

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "app" / "server" / "templates"


@pytest.fixture()
def secret(monkeypatch):
    monkeypatch.setenv("LITE_JWT_SECRET", TEST_SECRET)


@pytest.fixture()
def client(secret, tmp_path):
    dirs = {
        "db": tmp_path / "test.db",
        "mail": tmp_path / "mail",
        "uploads": tmp_path / "uploads",
    }
    app = create_app(
        db_path=dirs["db"],
        mail_dir=dirs["mail"],
        uploads_dir=dirs["uploads"],
    )
    return TestClient(app), dirs


def _csrf_token(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "page has no CSRF token field"
    return match.group(1)


def test_login_centered_onboarding_structure(client):
    http, _ = client
    page = http.get("/login", headers=HTML)
    assert page.status_code == 200, page.text
    body = page.text
    # Centered onboarding wrapper plus logo.
    assert 'class="auth-wrap"' in body
    assert 'class="auth-logo"' in body
    assert ">iVouch</p>" in body
    # Logo is 32px bold.
    assert "font-size: 32px" in body
    assert "font-weight: 700" in body
    # iOS-cell inputs: same targets, names, and attributes as before.
    assert '<form class="auth-form" method="post" action="/login">' in body
    assert 'name="csrf_token"' in body
    assert 'type="email" name="email"' in body
    assert 'type="password" name="password"' in body
    assert 'autocomplete="email"' in body
    assert 'autocomplete="current-password"' in body
    # Full-width 48px gradient primary button: the button carries the
    # shared gradient class (its gradient rule lives in style.css), and
    # the template sets the full-width 48px geometry.
    assert 'class="btn btn-primary auth-submit"' in body
    assert "min-height: 48px" in body
    assert "width: 100%" in body
    css = (TEMPLATES_DIR.parent / "static" / "style.css").read_text(
        encoding="utf-8"
    )
    assert "var(--gradient-primary)" in css
    # All text centered.
    assert "text-align: center" in body
    # Switch link kept, as a button-styled link.
    assert 'href="/signup"' in body


def test_signup_centered_with_gate_disclaimer_notice(client):
    http, _ = client
    page = http.get("/signup", headers=HTML)
    assert page.status_code == 200, page.text
    body = page.text
    assert 'class="auth-wrap"' in body
    assert 'class="auth-logo"' in body
    assert "font-size: 32px" in body
    assert '<form class="auth-form" method="post" action="/signup">' in body
    assert 'type="email" name="email"' in body
    assert 'type="password" name="password"' in body
    assert 'minlength="8"' in body
    assert 'class="btn btn-primary auth-submit"' in body
    assert "min-height: 48px" in body
    assert "width: 100%" in body
    # Spec-3.1 age gate.
    assert 'name="date_of_birth"' in body
    assert "or older to create an account." in body
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
    assert 'href="/login"' in body


def test_no_oauth_forgot_or_scripts(client):
    http, _ = client
    for route in ("/login", "/signup"):
        page = http.get(route, headers=HTML)
        assert page.status_code == 200, route
        lowered = page.text.lower()
        for banned in ("apple", "google", "oauth", "forgot"):
            assert banned not in lowered, (route, banned)
        assert "<script" not in lowered, route


def test_templates_use_variables_not_literals():
    for name in ("login.html", "signup.html"):
        source = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
        assert not HEX_RE.search(source), (
            f"{name} carries a literal colour instead of a CSS variable"
        )
        assert "times" not in source.lower(), f"{name} mentions Times"


def test_login_error_path_still_renders(client):
    http, _ = client
    assert http.post(
        "/auth/register",
        json={
            "email": "member@example.com",
            "password": PASSWORD,
            "date_of_birth": ADULT_DOB,
        },
    ).status_code == 200
    page = http.get("/login", headers=HTML)
    resp = http.post(
        "/login",
        data={
            "email": "member@example.com",
            "password": "wrong-pass-1",
            "csrf_token": _csrf_token(page.text),
        },
    )
    assert resp.status_code == 401, resp.text
    assert GENERIC_LOGIN_DETAIL in resp.text
    # Error renders inside the centered onboarding shell; form intact.
    assert 'class="auth-wrap"' in resp.text
    assert 'class="error"' in resp.text
    assert '<form class="auth-form" method="post" action="/login">' in resp.text
    assert 'name="csrf_token"' in resp.text


def test_signup_success_info_path_still_renders(client):
    http, _ = client
    page = http.get("/signup", headers=HTML)
    resp = http.post(
        "/signup",
        data={
            "email": "grown@example.com",
            "password": PASSWORD,
            "date_of_birth": ADULT_DOB,
            "csrf_token": _csrf_token(page.text),
        },
    )
    assert resp.status_code == 200, resp.text
    assert GENERIC_REGISTER_MESSAGE in resp.text
    assert 'class="auth-wrap"' in resp.text
    assert 'class="info"' in resp.text
    assert 'name="date_of_birth"' in resp.text


def test_centering_css_mobile_and_desktop(client):
    http, _ = client
    for route in ("/login", "/signup"):
        page = http.get(route, headers=HTML)
        assert page.status_code == 200, route
        body = page.text
        # Mobile: wrapper auto-margins plus centered text.
        assert "margin-left: auto" in body
        assert "margin-right: auto" in body
        assert ".auth-wrap" in body
        # Desktop: an explicit min-width media rule keeps the same
        # wrapper centered (no browser needed; class-level check).
        assert "@media (min-width: 768px)" in body
        media_tail = body.split("@media (min-width: 768px)", 1)[1]
        assert ".auth-wrap" in media_tail
        assert "margin-left: auto" in media_tail
        assert "text-align: center" in media_tail
