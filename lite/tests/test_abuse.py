"""Tests for Lite spec 4, objective 4.3: abuse and safety basics.

TestClient against tmp SQLite + tmp mail/uploads dirs only -- never
the real ``lite/data/`` directory -- with the stubbed CLIP encoder
via the ``create_app(clip_encoder=...)`` seam (fast).

Covers: the per-account upload cap (429 past the cap with nothing
stored), per-IP login rate limiting (429 past a lowered test budget,
success again after the store is cleared), a repo-wide
committed-secrets grep (no secret shapes outside an exact-path
allowlist), and the reviewer-only ``GET /audit`` listing (mock
rejections show hash, time, and account only -- never image bytes or
claim text).
"""

from __future__ import annotations

import hashlib
import io
import random
import re
from datetime import date, timedelta
from pathlib import Path

from PIL import Image

from lite.app.config import load_config
from lite.app.server import api as api_module
from lite.app.server import pipeline as upload_pipeline
from lite.app.server.api import create_app
from lite.app.server.db import connect, make_reviewer
from lite.app.server.pipeline import MOCK_REJECTION_DETAIL

TEST_SECRET = "test-jwt-secret-for-abuse-tests-0123456789"
PASSWORD = "correct-horse-9"
ADULT_DOB = (date.today() - timedelta(days=365 * 30)).isoformat()
OWNER_EMAIL = "abuse-owner@example.com"
REVIEWER_EMAIL = "abuse-reviewer@example.com"
TEMP_EMAIL = "abuse-leaver@example.com"
LAT = 51.5
LNG = -0.12
CLAIM = "a photo of a street with geometric shapes"

HTML = {"Accept": "text/html"}


class FanStub:
    """Deterministic stub encoder (same shape as the sibling suites')."""

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


def _register_verify_login(http, mail_dir, email):
    """Register + verify + JSON login; return Bearer [REDACTED]"""
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
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
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


def _make_app(monkeypatch, tmp_path):
    """Build the app on tmp dirs with the stub encoder."""
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
    return app, TestClient(app), dirs


def _upload_data(client_report_id, claim=CLAIM):
    return {
        "client_report_id": client_report_id,
        "location_lat": str(LAT),
        "location_lng": str(LNG),
        "location_consented": "true",
        "location_source": "browser",
        "claim_text": claim,
    }


def _report_count(db_path) -> int:
    conn = connect(str(db_path))
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM reports"
        ).fetchone()["n"]
    finally:
        conn.close()


def _audit_count(db_path) -> int:
    conn = connect(str(db_path))
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM audit_events"
        ).fetchone()["n"]
    finally:
        conn.close()


def _stored_files(uploads_dir) -> list:
    root = Path(uploads_dir)
    if not root.is_dir():
        return []
    return [p for p in root.rglob("*") if p.is_file()]


def test_upload_cap_returns_429_and_stores_nothing(
    monkeypatch, tmp_path
):
    cap = load_config().upload_cap_per_account
    _, http, dirs = _make_app(monkeypatch, tmp_path)
    headers = _register_verify_login(http, dirs["mail"], OWNER_EMAIL)
    mock_hashes = upload_pipeline.load_mock_hashes()
    for i in range(cap):
        raw = _fresh_jpeg_bytes(seed=1000 + i)
        assert hashlib.sha256(raw).hexdigest() not in mock_hashes
        resp = http.post(
            "/analyze",
            data=_upload_data(f"cap-{i}"),
            files={"photo": (f"cap-{i}.jpg", raw, "image/jpeg")},
            headers=headers,
        )
        assert resp.status_code == 200, (i, resp.text)
        assert "report_id" in resp.json()
    assert _report_count(dirs["db"]) == cap
    before_audits = _audit_count(dirs["db"])
    before_files = _stored_files(dirs["uploads"])
    raw = _fresh_jpeg_bytes(seed=99999)
    assert hashlib.sha256(raw).hexdigest() not in mock_hashes
    resp = http.post(
        "/analyze",
        data=_upload_data("cap-over"),
        files={"photo": ("cap-over.jpg", raw, "image/jpeg")},
        headers=headers,
    )
    assert resp.status_code == 429, resp.text
    assert _report_count(dirs["db"]) == cap
    assert _audit_count(dirs["db"]) == before_audits
    assert _stored_files(dirs["uploads"]) == before_files


def test_login_rate_limit_per_ip(monkeypatch, tmp_path):
    from dataclasses import replace

    app, http, dirs = _make_app(monkeypatch, tmp_path)
    assert http.post(
        "/auth/register",
        json={
            "email": OWNER_EMAIL,
            "password": PASSWORD,
            "date_of_birth": ADULT_DOB,
        },
    ).status_code == 200
    assert http.post(
        "/auth/verify-email",
        json={"token": _mail_token(dirs["mail"], OWNER_EMAIL)},
    ).status_code == 200
    # Lower only the rate-limit budget via the loader seam; every
    # other threshold keeps its committed value. Never edit config.
    lowered = replace(
        api_module.load_config(),
        login_ratelimit_max_attempts=3,
        login_ratelimit_window_seconds=600,
    )
    monkeypatch.setattr(
        api_module, "load_config", lambda path=None: lowered
    )
    bad = {"email": OWNER_EMAIL, "password": "wrong-pass-1"}
    for _ in range(3):
        resp = http.post("/auth/login", json=bad)
        assert resp.status_code == 401, resp.text
        assert resp.json() == {"detail": api_module.GENERIC_LOGIN_DETAIL}
    # The 4th attempt is rejected before credentials are checked,
    # even with the right password.
    blocked = http.post(
        "/auth/login", json={"email": OWNER_EMAIL, "password": PASSWORD}
    )
    assert blocked.status_code == 429, blocked.text
    # After the window entries are cleared, login succeeds again.
    app.state.login_attempts.clear()
    good = http.post(
        "/auth/login", json={"email": OWNER_EMAIL, "password": PASSWORD}
    )
    assert good.status_code == 200, good.text
    assert good.json()["email_verified"] is True


def test_no_committed_secret_patterns():
    """No secret shapes anywhere in the repo outside the allowlist.

    Literal substrings ``AKIA`` / ``sk-`` / ``ghp_`` / ``HF_TOKEN=``
    plus PEM private-key headers. Exact-path allowlist only: this
    file (it names the patterns under test), the spec-4 criterion
    text (it names the same patterns), the phase-8 hardening prose
    (it names key patterns), and the models config (whose
    ``task-splitter`` role name merely contains ``sk-``). Runtime and
    machine-local paths (``.git``, caches, ``lite/data/`` uploads and
    mail, ``.env``) are not committed content and are skipped.
    """
    root = Path(__file__).resolve().parents[2]
    allowlist = {
        "lite/tests/test_abuse.py",
        "lite/specs/spec-4-review-hardening.md",
        "specs/phase-8-hardening.md",
        "lite/agents/models.yaml",
    }
    literals = ("AKIA", "sk-", "ghp_", "HF_TOKEN=")
    key_header = re.compile(r"BEGIN [^\n\r]*PRIVATE KEY")
    skip_dirs = {".git", "__pycache__", ".venv", "node_modules"}
    violations = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        parts = rel.split("/")
        if any(part in skip_dirs for part in parts):
            continue
        if path.suffix == ".pyc":
            continue
        if len(parts) > 1 and parts[0] == "lite" and parts[1] == "data":
            continue
        if path.name == ".env" or path.name.startswith(".env."):
            continue
        if rel in allowlist:
            continue
        try:
            text = path.read_bytes().decode("utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        hits = sorted(p for p in literals if p in text)
        if key_header.search(text):
            hits.append("BEGIN * PRIVATE KEY")
        if hits:
            violations.append(f"{rel}: {', '.join(hits)}")
    assert violations == [], (
        "possible committed secrets:\n" + "\n".join(violations)
    )


def test_audit_listing_reviewer_only(monkeypatch, tmp_path):
    app, _, dirs = _make_app(monkeypatch, tmp_path)
    from fastapi.testclient import TestClient

    owner = TestClient(app)
    reviewer = TestClient(app)
    anon = TestClient(app)
    owner_headers = _register_verify_login(owner, dirs["mail"], OWNER_EMAIL)
    reviewer_headers = _register_verify_login(
        reviewer, dirs["mail"], REVIEWER_EMAIL
    )
    conn = connect(str(dirs["db"]))
    try:
        make_reviewer(conn, REVIEWER_EMAIL)
    finally:
        conn.close()
    _page_login(owner, OWNER_EMAIL)
    _page_login(reviewer, REVIEWER_EMAIL)

    # 1. A mock-gate rejection: listed fixture + a claim that must
    # never appear in the listing.
    fixture = (
        Path(__file__).resolve().parent / "fixtures" / "shapes_basic.png"
    )
    raw_fixture = fixture.read_bytes()
    digest = hashlib.sha256(raw_fixture).hexdigest()
    assert digest in upload_pipeline.load_mock_hashes()
    probe_claim = "audit probe claim text that must never be stored"
    rejected = owner.post(
        "/analyze",
        data=_upload_data("audit-mock", claim=probe_claim),
        files={"photo": ("shapes_basic.png", raw_fixture, "image/png")},
        headers=owner_headers,
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["detail"] == MOCK_REJECTION_DETAIL
    assert "report_id" not in rejected.json()

    # 2. An accepted upload plus one reviewer action.
    fresh = _fresh_jpeg_bytes(seed=4242)
    assert hashlib.sha256(fresh).hexdigest() not in (
        upload_pipeline.load_mock_hashes()
    )
    upload = owner.post(
        "/analyze",
        data=_upload_data("audit-ok"),
        files={"photo": ("audit-ok.jpg", fresh, "image/jpeg")},
        headers=owner_headers,
    )
    assert upload.status_code == 200, upload.text
    report_id = upload.json()["report_id"]
    action = reviewer.post(
        f"/review/{report_id}/actions",
        json={"action": "confirm"},
        headers=reviewer_headers,
    )
    assert action.status_code == 200, action.text

    # 3. An account deletion (separate account, verified then deleted).
    temp_headers = _register_verify_login(owner, dirs["mail"], TEMP_EMAIL)
    deleted = owner.delete("/account", headers=temp_headers)
    assert deleted.status_code == 200, deleted.text

    # The reviewer sees all three kinds; the rejection shows hash,
    # time, and account only -- never image bytes or claim text.
    page = reviewer.get("/audit", headers=HTML)
    assert page.status_code == 200, page.text
    html = page.text
    assert "mock_rejection" in html
    assert digest in html
    assert "review_action" in html
    assert "account_deletion" in html
    assert TEMP_EMAIL in html
    assert probe_claim not in html
    assert raw_fixture not in page.content
    assert OWNER_EMAIL not in html
    assert REVIEWER_EMAIL not in html
    assert "text/html" in page.headers["content-type"]

    # Non-reviewers get 403, never the listing (or a login redirect).
    denied = owner.get("/audit", headers=HTML)
    assert denied.status_code == 403, denied.text
    assert digest not in denied.text
    assert anon.get("/audit", headers=HTML).status_code == 403
