"""Tests for Lite spec 6, objective 6.10: navigation final state.

TestClient against tmp SQLite + tmp mail/uploads dirs only -- never
the real ``lite/data/`` directory. The CLIP encoder is always stubbed
through the ``create_app(clip_encoder=...)`` seam (fast; the live
model path is objective 2.5's, never here).

Approved scope only: search + notifications were NOT approved, so no
search bar, no bell, no dot may appear anywhere. The bottom tab bar
(mobile) and the desktop sidebar both hold exactly
[Feed] [Map] [Create +] [Saved] [Profile] in that order, every tab
and the header gear point at existing routes, and the Create FAB is
visible on both the map and the feed.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from PIL import Image

from lite.app.server.api import create_app

TEST_SECRET = "test-jwt-secret-for-navigation-tests-0123456789"
PASSWORD = "correct-horse-9"
ADULT_DOB = (date.today() - timedelta(days=365 * 30)).isoformat()

EMAIL = "navigator@example.com"

HTML = {"Accept": "text/html"}

TAB_HREFS = ("/feed", "/map", "/upload", "/saved", "/account")
TAB_LABELS = ("Feed", "Map", "Create +", "Saved", "Profile")
SHELL_PAGES = ("/feed", "/map", "/saved", "/upload", "/account")

NAV_RE = re.compile(
    r'<nav class="(tab-bar|sidebar)"[^>]*>(.*?)</nav>', re.DOTALL
)
LINK_RE = re.compile(
    r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL
)
FAB_RE = re.compile(
    r'<a\b[^>]*href="/upload"[^>]*>(.*?)</a>', re.DOTALL
)
GEAR_RE = re.compile(
    r'<a\b[^>]*href="/account"[^>]*>', re.DOTALL
)


class FanStub:
    """Deterministic stub encoder (same shape as the 2.3 suite's)."""

    def image_embed(self, image):
        assert isinstance(image, Image.Image)
        return [1.0, 1.0]

    def text_embeds(self, texts):
        return [[1.0, 0.1 * (i + 1)] for i, _ in enumerate(texts)]


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


def _register_verify(monkeypatch, tmp_path, email=EMAIL):
    from pathlib import Path

    http, dirs = _make_client(monkeypatch, tmp_path)
    resp = http.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "date_of_birth": ADULT_DOB,
        },
    )
    assert resp.status_code == 200, resp.text
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
    assert verify.status_code == 200, verify.text
    return http, dirs


def _page_login(http, email=EMAIL):
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


def _nav_links(body, nav_class):
    """Return (hrefs, labels) for the named shell nav block."""
    for kind, inner in NAV_RE.findall(body):
        if kind == nav_class:
            pairs = LINK_RE.findall(inner)
            hrefs = tuple(h for h, _ in pairs)
            labels = tuple(re.sub(r"\s+", " ", t).strip() for _, t in pairs)
            return hrefs, labels
    raise AssertionError(f"no <nav class={nav_class!r}> block rendered")


def test_mobile_tab_bar_exact_order_and_targets(monkeypatch, tmp_path):
    http, _ = _register_verify(monkeypatch, tmp_path)
    _page_login(http)
    for route in ("/feed", "/map"):
        page = http.get(route, headers=HTML)
        assert page.status_code == 200, (route, page.text)
        hrefs, labels = _nav_links(page.text, "tab-bar")
        assert hrefs == TAB_HREFS, (route, hrefs)
        assert labels == TAB_LABELS, (route, labels)


def test_desktop_sidebar_mirrors_tabs(monkeypatch, tmp_path):
    http, _ = _register_verify(monkeypatch, tmp_path)
    _page_login(http)
    for route in ("/feed", "/map"):
        page = http.get(route, headers=HTML)
        assert page.status_code == 200, (route, page.text)
        hrefs, labels = _nav_links(page.text, "sidebar")
        assert hrefs == TAB_HREFS, (route, hrefs)
        assert labels == TAB_LABELS, (route, labels)


def test_create_fab_on_map_and_feed(monkeypatch, tmp_path):
    http, _ = _register_verify(monkeypatch, tmp_path)
    _page_login(http)
    page = http.get("/map", headers=HTML)
    assert page.status_code == 200, page.text
    assert 'id="map_create"' in page.text
    assert 'href="/upload"' in page.text
    map_fabs = FAB_RE.findall(page.text)
    assert any("Create" in fab for fab in map_fabs), page.text

    page = http.get("/feed", headers=HTML)
    assert page.status_code == 200, page.text
    assert 'href="/upload"' in page.text
    assert 'feed-fab' in page.text
    feed_fabs = FAB_RE.findall(page.text)
    assert any("Create" in fab for fab in feed_fabs), page.text
    # The feed FAB is pure HTML/CSS: the feed carries no scripts.
    assert "<script" not in page.text.lower()


def test_header_gear_links_to_account_on_every_shell_page(
    monkeypatch, tmp_path
):
    http, _ = _register_verify(monkeypatch, tmp_path)
    _page_login(http)
    for route in SHELL_PAGES:
        page = http.get(route, headers=HTML)
        assert page.status_code == 200, (route, page.text)
        gears = GEAR_RE.findall(page.text)
        assert gears, f"{route} has no header link to /account"
        assert any("top-bar-gear" in tag for tag in gears), route


def test_search_and_notifications_absent(monkeypatch, tmp_path):
    http, _ = _register_verify(monkeypatch, tmp_path)
    _page_login(http)
    for route in SHELL_PAGES:
        page = http.get(route, headers=HTML)
        assert page.status_code == 200, (route, page.text)
        lowered = page.text.lower()
        assert "search" not in lowered, route
        assert "bell" not in lowered, route
        assert "notification" not in lowered, route
        assert "/notifications" not in page.text, route
        assert "/search" not in page.text, route


def test_every_tab_and_header_target_resolves(monkeypatch, tmp_path):
    http, _ = _register_verify(monkeypatch, tmp_path)
    _page_login(http)
    for target in TAB_HREFS:
        page = http.get(target, headers=HTML)
        assert page.status_code == 200, (target, page.text)


def test_anonymous_tab_targets_redirect_to_login(monkeypatch, tmp_path):
    http, _ = _make_client(monkeypatch, tmp_path)
    for target in TAB_HREFS:
        page = http.get(target, headers=HTML, follow_redirects=False)
        assert page.status_code == 303, (target, page.text)
        assert page.headers["location"] == "/login", target


HEADER_RE = re.compile(
    r'<header class="top-bar">(.*?)</header>', re.DOTALL
)
TAG_RE = re.compile(r"<a\b[^>]*>", re.DOTALL)


def _header(body):
    """The top-bar header block (header links live here, not page wide)."""
    match = HEADER_RE.search(body)
    assert match, "no top-bar header rendered"
    return match.group(1)


def _nav_inner(body, nav_class):
    """Inner HTML of one named shell nav block."""
    for kind, inner in NAV_RE.findall(body):
        if kind == nav_class:
            return inner
    raise AssertionError(f"no <nav class={nav_class!r}> block rendered")


def _active_hrefs(nav_inner):
    """Hrefs of the tabs carrying is-active in one nav block."""
    active = []
    for tag in TAG_RE.findall(nav_inner):
        cls = re.search(r'class="([^"]*)"', tag)
        href = re.search(r'href="([^"]+)"', tag)
        if (
            cls is not None
            and href is not None
            and "is-active" in cls.group(1).split()
        ):
            active.append(href.group(1))
    return active


def test_exactly_one_active_tab_matching_page(monkeypatch, tmp_path):
    http, _ = _register_verify(monkeypatch, tmp_path)
    _page_login(http)
    for route in SHELL_PAGES:
        page = http.get(route, headers=HTML)
        assert page.status_code == 200, (route, page.text)
        for nav_class in ("tab-bar", "sidebar"):
            inner = _nav_inner(page.text, nav_class)
            assert _active_hrefs(inner) == [route], (
                route, nav_class,
            )


def test_anonymous_header_login_signup_only(monkeypatch, tmp_path):
    http, _ = _make_client(monkeypatch, tmp_path)
    for route in ("/login", "/signup"):
        page = http.get(route, headers=HTML)
        assert page.status_code == 200, (route, page.text)
        header = _header(page.text)
        assert 'href="/login"' in header, route
        assert 'href="/signup"' in header, route
        assert 'href="/logout"' not in header, route
        assert "top-bar-gear" not in header, route
        assert "Admin" not in header, route


def test_owner_header_gear_logout_without_signup(monkeypatch, tmp_path):
    http, _ = _register_verify(monkeypatch, tmp_path)
    _page_login(http)
    for route in SHELL_PAGES:
        page = http.get(route, headers=HTML)
        assert page.status_code == 200, (route, page.text)
        header = _header(page.text)
        assert 'href="/logout"' in header, route
        assert "top-bar-gear" in header, route
        assert 'href="/login"' not in header, route
        assert 'href="/signup"' not in header, route
        assert "Admin" not in header, route
        assert "Sign up" not in page.text, route


def test_reviewer_header_shows_admin(monkeypatch, tmp_path):
    from lite.app.server.db import connect, make_reviewer

    http, dirs = _register_verify(monkeypatch, tmp_path)
    _page_login(http)
    conn = connect(str(dirs["db"]))
    try:
        make_reviewer(conn, EMAIL)
    finally:
        conn.close()
    for route in SHELL_PAGES:
        page = http.get(route, headers=HTML)
        assert page.status_code == 200, (route, page.text)
        header = _header(page.text)
        assert 'href="/review"' in header, route
        assert "Admin" in header, route
        assert 'href="/logout"' in header, route
        assert "top-bar-gear" in header, route
        assert 'href="/signup"' not in header, route
