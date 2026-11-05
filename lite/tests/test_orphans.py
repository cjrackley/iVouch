"""Tests for Lite spec 6, objective 6.2: endpoint coverage (no orphans).

TestClient against tmp SQLite + tmp mail/uploads dirs only -- never
the real ``lite/data/`` directory. The CLIP encoder is always stubbed
through the ``create_app(clip_encoder=...)`` seam. Page logins go
through the page form with CSRF, like ``test_navigation.py``.

Covers the 6.2 acceptance criteria:

1. Every GET page route from the routers (``/`` redirect, ``/map``,
   ``/shared/{id}``, ``/reports/{id}``, ``/upload``, ``/reports``,
   ``/account``, ``/logout``, ``/review``, ``/review/{id}``,
   ``/audit``, ``/saved``, ``/feed``) appears as a link target on at
   least one page a logged-in user can reach. Zero orphan routes.
   ``/login``, ``/signup``, and ``/verify`` are direct-entry routes
   (redirect target, header cross-link, mailed token link): they are
   audited for anonymous reachability and cross-linking instead.
   Tab/header coverage from ``test_navigation.py`` is reused by
   reference, not duplicated -- the crawl below focuses on the
   non-shell entry points (View Details, own-reports cards, FABs,
   My Pins tab, Admin link, empty-state buttons, verify notice).
2. The Admin link (review/audit) appears only for reviewer accounts.
3. No page links to a route that does not exist: every collected href
   target resolves without a 404 (200 for a suitably logged-in user,
   303 to ``/login`` for anonymous callers on gated pages).
4. Each list page (reports, saved, feed, review queue) shows its empty
   state with a ``/map`` button when it has no items.
5. Deep links: ``/map``, ``/shared/{id}``, ``/upload`` load when
   logged in, or redirect to ``/login`` when logged out.

Static files, photo routes, JSON API routes, and form POST targets
are exempt from the orphan rule, per the spec.
"""

from __future__ import annotations

import hashlib
import io
import random
import re
from datetime import date, timedelta

from PIL import Image

from lite.app.server.api import create_app
from lite.app.server.db import connect, make_reviewer

TEST_SECRET = "test-jwt-secret-for-orphan-audit-tests-0123456789"
PASSWORD = "correct-horse-9"
ADULT_DOB = (date.today() - timedelta(days=365 * 30)).isoformat()
OWNER_EMAIL = "orphan-owner@example.com"
REVIEWER_EMAIL = "orphan-reviewer@example.com"
LAT = 51.5
LNG = -0.12
CLAIM = "a photo of a street with geometric shapes"

HTML = {"Accept": "text/html"}

HREF_RE = re.compile(r'<a\b[^>]*href="([^"]+)"', re.IGNORECASE)
MAIN_RE = re.compile(
    r'<main class="safe-area">(.*?)</main>', re.DOTALL
)

# GET page routes that must each be reachable from a rendered link.
# Derived from the routers (``pages_router`` GET routes minus the
# exempt static/photo/JSON-API paths) plus ``/``, which redirects.
#
# Direct-entry routes (``DIRECT_ENTRY_ROUTES``) are exempt from the
# logged-in inbound-link rule: the session-aware header (spec 7.4)
# offers Log in/Sign up only to anonymous visitors, and the verify
# entry hides once verified (spec 7.5). They are audited separately
# below (anonymous cross-links plus direct reachability).
DIRECT_ENTRY_ROUTES = ("/login", "/signup", "/verify")
EXPECTED_PAGE_ROUTES = (
    "/",
    "/map",
    "/shared/{id}",
    "/reports/{id}",
    "/upload",
    "/reports",
    "/account",
    "/login",
    "/signup",
    "/logout",
    "/verify",
    "/review",
    "/review/{id}",
    "/audit",
    "/saved",
    "/feed",
)

# Link targets a non-reviewer session must never resolve through.
REVIEWER_GATED = ("/review", "/review/{id}", "/audit")


class FanStub:
    """Deterministic stub encoder (same shape as the sibling suites)."""

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
    return TestClient(app), app, dirs


def _mail_token(mail_dir, email) -> str:
    stem = "".join(
        ch if ch.isalnum() else "_" for ch in email.lower()
    )[:64]
    candidates = sorted(mail_dir.glob(f"verify_{stem}_*.txt"))
    assert candidates, f"no verification mail found for {email}"
    match = re.search(
        r"^token:\s*(\S+)\s*$",
        candidates[-1].read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert match, f"mail file {candidates[-1].name} has no token line"
    return match.group(1)


def _register_verify_login(http, mail_dir, email):
    """Register + verify + Bearer [REDACTED] via the JSON API."""
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
        json={"token": _mail_token(mail_dir, email)},
    ).status_code == 200
    login = http.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _page_login(http, email):
    """Log in through the page form (sets the cookie session)."""
    page = http.get("/login", headers=HTML)
    assert page.status_code == 200, page.text
    match = re.search(
        r'name="csrf_token" value="([^"]+)"', page.text
    )
    assert match, "login page has no CSRF token field"
    login = http.post(
        "/login",
        data={
            "email": email,
            "password": PASSWORD,
            "csrf_token": match.group(1),
        },
        follow_redirects=False,
    )
    assert login.status_code == 303, login.text


def _upload_report(http, headers, raw, client_report_id):
    from lite.app.server import pipeline as upload_pipeline

    assert (
        hashlib.sha256(raw).hexdigest()
        not in upload_pipeline.load_mock_hashes()
    )
    upload = http.post(
        "/analyze",
        data={
            "client_report_id": client_report_id,
            "location_lat": str(LAT),
            "location_lng": str(LNG),
            "location_consented": "true",
            "location_source": "browser",
            "claim_text": CLAIM,
        },
        files={"photo": ("photo.png", raw, "image/png")},
        headers=headers,
    )
    assert upload.status_code == 200, upload.text
    return upload.json()["report_id"]


def _setup(monkeypatch, tmp_path):
    """Owner (+1 report, +1 save) and a cookie-logged-in reviewer."""
    http, app, dirs = _make_client(monkeypatch, tmp_path)
    from fastapi.testclient import TestClient

    owner = TestClient(app)
    reviewer = TestClient(app)
    owner_headers = _register_verify_login(
        owner, dirs["mail"], OWNER_EMAIL
    )
    _register_verify_login(reviewer, dirs["mail"], REVIEWER_EMAIL)
    conn = connect(str(dirs["db"]))
    try:
        make_reviewer(conn, REVIEWER_EMAIL)
    finally:
        conn.close()
    _page_login(owner, OWNER_EMAIL)
    _page_login(reviewer, REVIEWER_EMAIL)
    report_id = _upload_report(
        owner, owner_headers, _fresh_png_bytes(seed=7), "orphan-seed-7"
    )
    saved = owner.post(
        "/saved", json={"report_id": report_id}, headers=owner_headers
    )
    assert saved.status_code == 200, saved.text
    return owner, reviewer, app, dirs, report_id


def _normalize_href(href: str) -> str | None:
    """Map a rendered href to a route pattern, or None if exempt."""
    if href.startswith(("http://", "https://", "mailto:", "#")):
        return None
    if href.startswith(("javascript:", "data:")):
        return None
    path = href.split("#", 1)[0].split("?", 1)[0]
    if not path.startswith("/"):
        return None
    if path.startswith(("/static/", "/api/")):
        return None
    if re.fullmatch(r"/shared/photos/\d+", path):
        return None
    for prefix in ("/shared/", "/reports/", "/review/"):
        if path.startswith(prefix) and path[len(prefix):].isdigit():
            return f"{prefix}{{id}}"
    return path or "/"


def _crawl_hrefs(clients_pages) -> tuple[set, set]:
    """Collect (raw hrefs, normalized patterns) from page bodies."""
    raw: set = set()
    patterns: set = set()
    for http, routes in clients_pages:
        for route in routes:
            page = http.get(route, headers=HTML)
            assert page.status_code in (200, 403, 404), (
                route,
                page.status_code,
            )
            for href in HREF_RE.findall(page.text):
                if href.startswith(("http", "mailto:", "#", "javascript")):
                    continue
                raw.add(href)
                pattern = _normalize_href(href)
                if pattern is not None:
                    patterns.add(pattern)
    return raw, patterns


OWNER_PAGES = (
    "/map",
    "/feed",
    "/saved",
    "/account",
    "/account?tab=saved",
    "/reports",
    "/upload",
    "/verify",
    "/shared/PLACEHOLDER",
    "/reports/PLACEHOLDER",
    "/shared/999999",
    "/review",
)

REVIEWER_PAGES = (
    "/review",
    "/review/PLACEHOLDER",
    "/audit",
    "/account",
)


def _rendered_pages(owner, reviewer, report_id):
    """Fetch every reachable page body for both roles."""
    bodies: list = []
    owner_routes = [
        r.replace("PLACEHOLDER", str(report_id)) for r in OWNER_PAGES
    ]
    reviewer_routes = [
        r.replace("PLACEHOLDER", str(report_id)) for r in REVIEWER_PAGES
    ]
    for http, routes in (
        (owner, owner_routes),
        (reviewer, reviewer_routes),
    ):
        for route in routes:
            page = http.get(route, headers=HTML)
            assert page.status_code in (200, 303, 403, 404), (
                route,
                page.status_code,
            )
            if page.status_code == 200:
                bodies.append(page.text)
    return bodies


def test_every_page_route_is_linked(monkeypatch, tmp_path):
    """Zero orphan routes: each GET page route is a link target."""
    owner, reviewer, app, _, report_id = _setup(
        monkeypatch, tmp_path
    )
    owner_routes = [
        r.replace("PLACEHOLDER", str(report_id)) for r in OWNER_PAGES
    ]
    reviewer_routes = [
        r.replace("PLACEHOLDER", str(report_id)) for r in REVIEWER_PAGES
    ]
    _, patterns = _crawl_hrefs(
        [(owner, owner_routes), (reviewer, reviewer_routes)]
    )
    missing = [
        route
        for route in EXPECTED_PAGE_ROUTES
        if route not in patterns and route not in DIRECT_ENTRY_ROUTES
    ]
    assert not missing, f"orphan page routes with no inbound link: {missing}"
    from fastapi.testclient import TestClient

    anon = TestClient(app)
    _, anon_patterns = _crawl_hrefs(
        [(anon, ["/login", "/signup", "/verify"])]
    )
    # Anonymous entry points stay mutually linked for the visitors
    # who need them (session-aware header cross-links).
    for route in ("/login", "/signup"):
        assert route in anon_patterns, (
            f"anonymous entry point with no inbound link: {route}"
        )
    for route in DIRECT_ENTRY_ROUTES:
        direct = anon.get(route, headers=HTML)
        assert direct.status_code == 200, (route, direct.status_code)
    # The verify entry is mailed out of band; its one in-app inbound
    # link is the unverified account page (hidden once verified).
    fresh = TestClient(app)
    assert fresh.post(
        "/auth/register",
        json={
            "email": "orphan-fresh@example.com",
            "password": PASSWORD,
            "date_of_birth": ADULT_DOB,
        },
    ).status_code == 200
    _page_login(fresh, "orphan-fresh@example.com")
    unverified = fresh.get("/account", headers=HTML)
    assert unverified.status_code == 200, unverified.text
    assert 'href="/verify"' in unverified.text


def test_router_get_routes_match_expected_set(monkeypatch, tmp_path):
    """The audit pins the router's GET page-route list itself."""
    from lite.app.server.pages import pages_router

    _make_client(monkeypatch, tmp_path)
    router_paths: set = set()
    for route in pages_router.routes:
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", "")
        if "GET" not in methods or not path.startswith("/"):
            continue
        if path.startswith(("/static/", "/api/")):
            continue
        if path == "/shared/photos/{report_id}":
            continue
        router_paths.add(
            re.sub(r"\{[^}]*\}", "{id}", path)
        )
    expected = set(EXPECTED_PAGE_ROUTES) - {"/"}
    assert router_paths == expected, (
        sorted(router_paths ^ expected),
        sorted(router_paths),
    )


def test_root_redirects_to_map(monkeypatch, tmp_path):
    """``GET /`` redirects to ``/map`` for logged-in and anonymous."""
    owner, _, app, _, _ = _setup(monkeypatch, tmp_path)
    from fastapi.testclient import TestClient

    anon = TestClient(app)
    for client in (owner, anon):
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 303, (resp.status_code, resp.text)
        assert resp.headers["location"] == "/map"


def test_admin_links_reviewer_only(monkeypatch, tmp_path):
    """Admin (review/audit) links appear only for reviewer accounts."""
    owner, reviewer, _, _, report_id = _setup(monkeypatch, tmp_path)
    admin = reviewer.get("/account", headers=HTML)
    assert admin.status_code == 200, admin.text
    assert 'href="/review"' in admin.text, (
        "reviewer account page has no Admin link to /review"
    )
    bodies = _rendered_pages(owner, reviewer, report_id)
    _ = bodies  # reviewer bodies are allowed admin links; checked below
    owner_routes = [
        r.replace("PLACEHOLDER", str(report_id)) for r in OWNER_PAGES
    ]
    for route in owner_routes:
        page = owner.get(route, headers=HTML)
        if page.status_code != 200:
            continue
        for href in HREF_RE.findall(page.text):
            normalized = _normalize_href(href)
            assert normalized not in REVIEWER_GATED, (
                route,
                href,
                "non-reviewer page links a reviewer-only route",
            )


def test_no_page_links_to_missing_route(monkeypatch, tmp_path):
    """Every href target resolves: never 404, correctly gated."""
    owner, reviewer, app, _, report_id = _setup(monkeypatch, tmp_path)
    from fastapi.testclient import TestClient

    anon = TestClient(app)
    owner_routes = [
        r.replace("PLACEHOLDER", str(report_id)) for r in OWNER_PAGES
    ]
    reviewer_routes = [
        r.replace("PLACEHOLDER", str(report_id)) for r in REVIEWER_PAGES
    ]
    raw, _ = _crawl_hrefs(
        [(owner, owner_routes), (reviewer, reviewer_routes)]
    )
    targets = sorted(
        {
            href.split("#", 1)[0]
            for href in raw
            if href.startswith("/") and not href.startswith(("/static/"))
        }
    )
    assert targets, "crawl collected no same-origin href targets"
    for target in targets:
        pattern = _normalize_href(target)
        if pattern == "/logout":
            # Probed in isolation after the loop: GET /logout clears
            # the session cookie, so it must not run on the shared
            # owner/reviewer clients mid-loop.
            continue
        owner_resp = owner.get(
            target, headers=HTML, follow_redirects=False
        )
        reviewer_resp = reviewer.get(
            target, headers=HTML, follow_redirects=False
        )
        anon_resp = anon.get(
            target, headers=HTML, follow_redirects=False
        )
        assert owner_resp.status_code != 404, ("owner", target)
        if pattern == "/reports/{id}":
            # Owner-private page of another account: non-owner access is
            # blocked, 403 or 404 allowed per locked spec-2 contract
            # (test_retrieval.py:347-348).
            assert reviewer_resp.status_code in (403, 404), (
                "reviewer",
                target,
            )
        else:
            assert reviewer_resp.status_code != 404, ("reviewer", target)
        assert anon_resp.status_code != 404, ("anonymous", target)
        if pattern in REVIEWER_GATED:
            assert reviewer_resp.status_code == 200, (
                target,
                reviewer_resp.status_code,
            )
            assert owner_resp.status_code == 403, (
                target,
                owner_resp.status_code,
            )
        elif pattern in ("/login", "/signup"):
            assert owner_resp.status_code == 303, (target, owner_resp.text)
            assert anon_resp.status_code == 200, (target, anon_resp.text)
        elif pattern == "/verify":
            assert owner_resp.status_code == 200, target
            assert anon_resp.status_code == 200, target
        else:
            assert owner_resp.status_code == 200, (
                target,
                owner_resp.status_code,
            )
            assert anon_resp.status_code == 303, (
                target,
                anon_resp.status_code,
                anon_resp.text,
            )
            assert anon_resp.headers["location"] == "/login", target
    # Isolated /logout probe (same assertions as before, unchanged):
    # GET /logout clears the session cookie, so a throwaway logged-in
    # client is used and the shared loop clients stay logged in.
    logout_probe = TestClient(app)
    _page_login(logout_probe, OWNER_EMAIL)
    logout_resp = logout_probe.get(
        "/logout", headers=HTML, follow_redirects=False
    )
    assert logout_resp.status_code == 303, "/logout"
    assert logout_resp.headers["location"] == "/login", "/logout"
    anon_logout_resp = anon.get(
        "/logout", headers=HTML, follow_redirects=False
    )
    assert anon_logout_resp.status_code != 404, ("anonymous", "/logout")


def _main_after_marker(page_text: str, marker: str) -> str:
    """Return the <main> body starting at the empty-state marker."""
    match = MAIN_RE.search(page_text)
    assert match, "page has no <main class=\"safe-area\"> block"
    main = match.group(1)
    index = main.find(marker)
    assert index >= 0, f"empty-state marker missing: {marker!r}"
    return main[index:]


def test_empty_reports_has_map_button(monkeypatch, tmp_path):
    """Empty own-reports list shows its empty state + /map button."""
    http, _, dirs = _make_client(monkeypatch, tmp_path)
    _register_verify_login(http, dirs["mail"], OWNER_EMAIL)
    _page_login(http, OWNER_EMAIL)
    page = http.get("/reports", headers=HTML)
    assert page.status_code == 200, page.text
    after = _main_after_marker(page.text, "No reports yet.")
    assert 'href="/map"' in after, (
        "empty /reports list has no /map button after its empty state"
    )


def test_empty_saved_has_map_button(monkeypatch, tmp_path):
    """Empty saved places shows its empty state + /map button."""
    http, _, dirs = _make_client(monkeypatch, tmp_path)
    _register_verify_login(http, dirs["mail"], OWNER_EMAIL)
    _page_login(http, OWNER_EMAIL)
    page = http.get("/saved", headers=HTML)
    assert page.status_code == 200, page.text
    after = _main_after_marker(page.text, "No saved vouches yet")
    assert 'href="/map"' in after, (
        "empty /saved list has no /map button after its empty state"
    )


def test_empty_feed_has_map_button(monkeypatch, tmp_path):
    """Empty feed shows its empty state + /map button."""
    http, _, dirs = _make_client(monkeypatch, tmp_path)
    _register_verify_login(http, dirs["mail"], OWNER_EMAIL)
    _page_login(http, OWNER_EMAIL)
    page = http.get("/feed", headers=HTML)
    assert page.status_code == 200, page.text
    after = _main_after_marker(page.text, "No vouches to show yet")
    assert 'href="/map"' in after, (
        "empty /feed has no /map button after its empty state"
    )


def test_empty_review_queue_has_map_button(monkeypatch, tmp_path):
    """Empty review queue shows its empty state + /map button."""
    http, _, dirs = _make_client(monkeypatch, tmp_path)
    _register_verify_login(http, dirs["mail"], REVIEWER_EMAIL)
    conn = connect(str(dirs["db"]))
    try:
        make_reviewer(conn, REVIEWER_EMAIL)
    finally:
        conn.close()
    _page_login(http, REVIEWER_EMAIL)
    page = http.get("/review", headers=HTML)
    assert page.status_code == 200, page.text
    after = _main_after_marker(page.text, "No reports yet.")
    assert 'href="/map"' in after, (
        "empty /review queue has no /map button after its empty state"
    )


def test_deep_links_logged_in(monkeypatch, tmp_path):
    """``/map``, ``/shared/{id}``, ``/upload`` load when logged in."""
    owner, _, _, _, report_id = _setup(monkeypatch, tmp_path)
    for route in ("/map", f"/shared/{report_id}", "/upload"):
        page = owner.get(route, headers=HTML)
        assert page.status_code == 200, (route, page.text)


def test_deep_links_anonymous_redirect_to_login(monkeypatch, tmp_path):
    """Logged-out deep links redirect to ``/login`` (never 404)."""
    _, _, app, dirs, _ = _setup(monkeypatch, tmp_path)
    from fastapi.testclient import TestClient

    probe = TestClient(app)
    # A shared deep link needs an accepted report to exist.
    report_id = _upload_report(
        probe,
        _register_verify_login(
            probe, dirs["mail"], "deep-link-owner@example.com"
        ),
        _fresh_png_bytes(seed=11),
        "orphan-deep-11",
    )
    anon = TestClient(app)
    for route in ("/map", f"/shared/{report_id}", "/upload"):
        resp = anon.get(route, headers=HTML, follow_redirects=False)
        assert resp.status_code == 303, (route, resp.text)
        assert resp.headers["location"] == "/login", route
