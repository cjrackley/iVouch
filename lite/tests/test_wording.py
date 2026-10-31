"""Tests for Lite spec 3, objective 3.3: wording and honesty pass.

Static grep over template sources plus direct Jinja renders with
fabricated contexts (no app, no encoder, no network): every rendered
template has the exact label tokens stripped and must then contain no
certainty words; result pages carry the two exact honesty lines; the
label set is exactly likely-real / needs-review / likely-manipulated;
and script tags are limited to a version-pinned CDN allowlist
(MapLibre GL JS, spec-5.3) plus at most one sanctioned inline block
per template (the upload file-picker gate or the map wiring block),
identified by required marker content rather than by file name: every
other script tag (unpinned/unknown src, any further inline block)
fails. A final TestClient pass (no clip encoder attached,
no upload model involved) proves the pages render server-side, so no
browser automation is required in Lite.
"""

from __future__ import annotations

import re
from pathlib import Path

import jinja2

TESTS_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = TESTS_DIR.parent / "app" / "server" / "templates"

DEMO_LINE = (
    "Demo build \u2014 results need human review "
    "and are not evidence of authenticity."
)
DATAUSE_LINE = (
    "Visible to logged-in demo users. "
    "Your email and exact location are never shared."
)
LABELS = ("likely-real", "needs-review", "likely-manipulated")

WORD_RE = re.compile(r"\bproven\b|\bfake\b|\breal\b", re.IGNORECASE)
LABEL_RE = re.compile(r"likely-real|needs-review|likely-manipulated")
SCRIPT_OPEN_RE = re.compile(r"<script[\s>]", re.IGNORECASE)
SCRIPT_TAG_RE = re.compile(r"<script\b[^>]*>", re.IGNORECASE)
SCRIPT_CLOSE_RE = re.compile(r"</script\s*>", re.IGNORECASE)
SCRIPT_SRC_RE = re.compile(
    r"<script[^>]*\bsrc\s*=\s*\"([^\"]+)\"", re.IGNORECASE
)
# Version-pinned CDN scripts sanctioned in any template (spec-5.3
# MapLibre via CDN). Exact URLs copied from the templates themselves;
# any other src (unpinned, unknown host, unknown path) stays forbidden.
SCRIPT_SRC_ALLOWLIST = (
    "https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.js",
)
# Sanctioned inline blocks, identified by required marker content
# rather than by file name: the upload file-picker gating block, and
# the map wiring block (MapLibre init, incidents fetch, fallback).
UPLOAD_PICKER_MARKERS = ("location_consented", "upload_submit")
MAP_INLINE_MARKERS = ("maplibregl", "showFallback", "/api/incidents")
PHRASE = "verified real"

_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=True,
)


def _report_context(label: str) -> dict:
    report = {
        "report_id": 7,
        "needs_review": label != "likely-real",
        "photo_url": "/api/photos/7",
        "top_severity": "moderate",
        "verdict": label,
        "confidence": 0.42,
        "display_lat": 51.5,
        "display_lng": -0.12,
        "claim_text": "a photo of a street",
        "created_at": "2026-01-01T00:00:00",
        "incident_probs": {"fire": 0.7, "flood": 0.2},
        "severity_probs": {"moderate": 0.6, "mild": 0.4},
        "reasons": ["mock reason one", "mock reason two"],
    }
    return {
        "title": "Report 7",
        "report": report,
        "top_incident": "fire",
        "top_incident_prob": 0.7,
    }


def _all_renders() -> list[tuple[str, str]]:
    """Render every template with representative contexts."""
    out: list[tuple[str, str]] = []
    out.append(("base.html", _env.get_template("base.html").render(
        {"title": "x"})))
    for verified in (True, False):
        out.append((f"account.html verified={verified}",
                    _env.get_template("account.html").render({
                        "title": "Your account",
                        "csrf_token": "csrf",
                        "email": "a@example.com",
                        "verified": verified,
                        "error": None,
                    })))
    out.append(("login.html", _env.get_template("login.html").render(
        {"title": "Log in", "csrf_token": "csrf", "error": None})))
    out.append(("signup.html", _env.get_template("signup.html").render(
        {"title": "Create account", "csrf_token": "csrf", "min_age": 18,
         "error": None, "info": None})))
    out.append(("verify.html", _env.get_template("verify.html").render(
        {"title": "Verify email", "csrf_token": "csrf", "message": None,
         "error": None, "email": ""})))
    out.append(("message.html", _env.get_template("message.html").render(
        {"title": "t", "heading": "h", "message": "m",
         "back": "/", "back_label": "Home"})))
    for demo_notice in ("note", None):
        out.append((f"rejection.html notice={demo_notice is not None}",
                    _env.get_template("rejection.html").render({
                        "title": "Upload not accepted",
                        "message": "upload could not be accepted",
                        "demo_notice": demo_notice,
                    })))
    out.append(("reports.html empty",
                _env.get_template("reports.html").render(
                    {"title": "Your reports", "reports": []})))
    out.append(("reports.html one",
                _env.get_template("reports.html").render({
                    "title": "Your reports",
                    "reports": [{"report_id": 7, "verdict": "needs-review",
                                 "created_at": "2026-01-01T00:00:00"}],
                })))
    for verified in (True, False):
        out.append((f"upload.html verified={verified}",
                    _env.get_template("upload.html").render({
                        "title": "Upload", "csrf_token": "csrf",
                        "verified": verified,
                        "client_report_id": "abc123",
                        "error": None,
                    })))
    for label in LABELS:
        out.append((f"report.html {label}",
                    _env.get_template("report.html").render(
                        _report_context(label))))
        out.append((f"shared.html {label}",
                    _env.get_template("shared.html").render(
                        _report_context(label))))
    return out


def _stripped(text: str) -> str:
    for token in LABELS:
        text = text.replace(token, "")
    return text


def test_no_certainty_words_in_rendered_templates():
    for name, body in _all_renders():
        cleaned = _stripped(body)
        assert WORD_RE.search(cleaned) is None, (
            f"{name} uses a certainty word: "
            f"{WORD_RE.search(cleaned).group(0)!r}"
        )
        if not name.startswith("account.html"):
            assert PHRASE not in cleaned.lower(), (
                f"{name} contains the phrase {PHRASE!r}"
            )


def test_account_template_never_says_real():
    source = (TEMPLATES_DIR / "account.html").read_text(encoding="utf-8")
    assert WORD_RE.search(_stripped(source)) is None
    assert PHRASE not in source.lower()
    for verified in (True, False):
        body = _env.get_template("account.html").render({
            "title": "Your account",
            "csrf_token": "csrf",
            "email": "a@example.com",
            "verified": verified,
            "error": None,
        })
        assert WORD_RE.search(_stripped(body)) is None, verified
        assert PHRASE not in body.lower(), verified
    # The verified-state wording keeps "verified" with no adjacent "real".
    assert "Email verified" in source or "verified." in source


def test_result_pages_carry_demo_and_datause_lines():
    for name in ("report.html", "shared.html"):
        source = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
        assert DEMO_LINE in source, name
        assert DATAUSE_LINE in source, name
        for label in LABELS:
            body = _env.get_template(name).render(_report_context(label))
            assert DEMO_LINE in body, (name, label)
            assert DATAUSE_LINE in body, (name, label)


def test_labels_are_exactly_the_three():
    found: set[str] = set()
    sources = [TESTS_DIR.parent / "app" / "checks" / "fusion.py",
               TESTS_DIR.parent / "app" / "server" / "pages.py"]
    sources += sorted(TEMPLATES_DIR.glob("*.html"))
    for path in sources:
        found.update(
            LABEL_RE.findall(path.read_text(encoding="utf-8"))
        )
    assert found == set(LABELS), sorted(found)
    # Result pages render the verdict variable; they never hardcode one.
    for name in ("report.html", "shared.html"):
        source = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
        assert "report.verdict" in source, name


def test_no_javascript_except_sanctioned_map_scripts():
    for path in sorted(TEMPLATES_DIR.glob("*.html")):
        source = path.read_text(encoding="utf-8")
        opens = list(SCRIPT_TAG_RE.finditer(source))
        closes = len(SCRIPT_CLOSE_RE.findall(source))
        assert closes == len(opens), path.name
        inline_bodies: list[str] = []
        for tag in opens:
            src = SCRIPT_SRC_RE.search(tag.group(0))
            if src is not None:
                assert src.group(1) in SCRIPT_SRC_ALLOWLIST, (
                    f"{path.name} loads unsanctioned script src "
                    f"{src.group(1)!r}"
                )
                continue
            rest = source[tag.end():]
            close = SCRIPT_CLOSE_RE.search(rest)
            assert close is not None, path.name
            inline_bodies.append(rest[:close.start()])
        assert len(inline_bodies) <= 1, (
            f"{path.name} carries {len(inline_bodies)} inline scripts"
        )
        for body in inline_bodies:
            assert (
                all(m in body for m in UPLOAD_PICKER_MARKERS)
                or all(m in body for m in MAP_INLINE_MARKERS)
            ), f"{path.name} carries an unsanctioned inline script"
        if path.name == "upload.html":
            assert any(
                all(m in body for m in UPLOAD_PICKER_MARKERS)
                for body in inline_bodies
            ), "upload page lost its file-picker gating script"


def test_pages_render_server_side_without_javascript(
    monkeypatch, tmp_path
):
    """Manual no-JS render check, recorded via TestClient GETs.

    The TestClient executes no JavaScript by construction; every page
    below returns its full content as plain HTML, which proves the
    pages render server-side. No browser automation is required in
    Lite. No clip encoder is attached: none of these paths run the
    upload model (the rejection flow below stops at the mock hash
    gate, before any encoder use).
    """
    from datetime import date, timedelta

    monkeypatch.setenv(
        "LITE_JWT_SECRET", "test-jwt-secret-for-wording-tests-0123456789"
    )
    from fastapi.testclient import TestClient

    from lite.app.server.api import create_app

    db_path = tmp_path / "test.db"
    mail_dir = tmp_path / "mail"
    uploads_dir = tmp_path / "uploads"
    app = create_app(
        db_path=db_path, mail_dir=mail_dir, uploads_dir=uploads_dir
    )
    http = TestClient(app)
    html = {"Accept": "text/html"}

    # Anonymous pages render with full server-side content.
    for route in ("/signup", "/login", "/verify"):
        page = http.get(route, headers=html)
        assert page.status_code == 200, route
        assert "<form" in page.text, route

    # Register, verify, and log in through the page (cookie session).
    email = "wording-owner@example.com"
    password = "correct-horse-9"
    dob = (date.today() - timedelta(days=365 * 30)).isoformat()
    assert http.post("/auth/register", json={
        "email": email, "password": password, "date_of_birth": dob,
    }).status_code == 200
    stem = "".join(
        ch if ch.isalnum() else "_" for ch in email.lower()
    )[:64]
    candidates = sorted(mail_dir.glob(f"verify_{stem}_*.txt"))
    assert candidates, "no verification mail written"
    match = re.search(
        r"^token:\s*(\S+)\s*$",
        candidates[-1].read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert match, "verification mail has no token line"
    assert http.post("/auth/verify-email", json={
        "token": match.group(1),
    }).status_code == 200
    login_page = http.get("/login", headers=html)
    csrf = re.search(
        r'name="csrf_token" value="([^"]+)"', login_page.text
    )
    assert csrf, "login page has no CSRF token field"
    login = http.post("/login", data={
        "email": email, "password": password,
        "csrf_token": csrf.group(1),
    }, follow_redirects=False)
    assert login.status_code == 303, login.text

    # Authenticated pages render server-side. Only the upload form
    # may carry JavaScript: its single file-picker gating script.
    for route in ("/account", "/upload", "/reports"):
        page = http.get(route, headers=html)
        assert page.status_code == 200, (route, page.text)
        scripts = len(SCRIPT_OPEN_RE.findall(page.text))
        if route == "/upload":
            assert scripts == 1, page.text
        else:
            assert scripts == 0, route
    account = http.get("/account", headers=html)
    assert "Email status:" in account.text

    # A mock-listed fixture stops at the mock hash gate and renders
    # the rejection page server-side (generic message plus notice).
    raw = (TESTS_DIR / "fixtures" / "shapes_basic.png").read_bytes()
    landing = http.get("/upload", headers=html)
    csrf = re.search(
        r'name="csrf_token" value="([^"]+)"', landing.text
    )
    assert csrf, "upload page has no CSRF token field"
    resp = http.post("/upload", data={
        "csrf_token": csrf.group(1),
        "client_report_id": "wording-reject-1",
        "location_source": "manual_pin",
        "location_lat": "51.5",
        "location_lng": "-0.12",
        "location_consented": "true",
        "claim_text": "",
    }, files={"photo": ("shapes_basic.png", raw, "image/png")},
        follow_redirects=False)
    assert resp.status_code == 200, resp.text
    assert "Upload not accepted" in resp.text
    assert "Not for emergencies" in resp.text
    assert "<script" not in resp.text.lower()
