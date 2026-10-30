"""Tests for Lite spec 3, objective 3.2: upload and result pages.

TestClient against tmp SQLite + tmp mail/uploads dirs only -- never
the real ``lite/data/`` directory. The CLIP encoder is always stubbed
through the ``create_app(clip_encoder=...)`` seam (fast); the brief
allows this mock for page-flow tests.

Pages under test: ``GET /upload`` (form with both notices, disabled
submit), ``POST /upload`` (browser flow delegating to the spec-2
``POST /analyze`` rules), ``GET /reports/{id}`` (owner result card),
``GET /reports`` (own list, newest first, no image bytes),
``GET /shared/{id}`` (community page, any logged-in user), plus a
dev-server startup smoke (``python -m lite.app.server --help``).

NOTE: every committed fixture image is on the mock hash list, so
accepted-upload tests generate fresh in-memory images (never fixtures)
to exercise the accept path. Fixture bytes are used exactly once: to
exercise the mock-gate rejection page.
"""

from __future__ import annotations

import hashlib
import io
import random
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from PIL import Image

from lite.app.server import pipeline as upload_pipeline
from lite.app.server.api import create_app
from lite.app.server.db import connect

TEST_SECRET = "test-jwt-secret-for-upload-pages-tests-0123456789"
PASSWORD = "correct-horse-9"
ADULT_DOB = (date.today() - timedelta(days=365 * 30)).isoformat()

HTML = {"Accept": "text/html"}

MOCK_REJECTION_DETAIL = "upload could not be accepted"
EMERGENCY_LINE = "Not for emergencies: call your local emergency number."

OWNER_EMAIL = "page-owner@example.com"
OTHER_EMAIL = "page-other@example.com"
PAGE_CLAIM = "a photo of a street with geometric shapes"


class FanStub:
    """Deterministic stub encoder (same shape as the 2.3 suite's)."""

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


def _make_app(monkeypatch, tmp_path):
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
    return app, dirs, TestClient


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


def _verified_session(http, dirs, email):
    """Register + verify via API, then log in via the page (cookie)."""
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
        json={"token": _mail_token(dirs["mail"], email)},
    ).status_code == 200
    page = http.get("/login", headers=HTML)
    assert page.status_code == 200, page.text
    login = http.post(
        "/login",
        data={
            "email": email,
            "password": PASSWORD,
            "csrf_token": _csrf(page.text),
        },
        follow_redirects=False,
    )
    assert login.status_code == 303, login.text
    # Bearer headers for JSON assertions alongside the cookie session.
    token = http.post(
        "/auth/login",
        json={"email": email, "password": PASSWORD},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "page has no CSRF token field"
    return match.group(1)


def _page_upload(
    http,
    *,
    client_id,
    raw,
    filename="photo.png",
    ctype="image/png",
    claim=PAGE_CLAIM,
    lat="51.5",
    lng="-0.12",
    consent=True,
):
    """POST one upload through the page flow (no redirect following)."""
    landing = http.get("/upload", headers=HTML)
    assert landing.status_code == 200, landing.text
    data = {
        "csrf_token": _csrf(landing.text),
        "client_report_id": client_id,
        "location_source": "manual_pin",
        "claim_text": claim,
    }
    if lat is not None:
        data["location_lat"] = lat
    if lng is not None:
        data["location_lng"] = lng
    if consent:
        data["location_consented"] = "true"
    return http.post(
        "/upload",
        data=data,
        files={"photo": (filename, raw, ctype)},
        follow_redirects=False,
    )


def _report_count(db_path) -> int:
    conn = connect(str(db_path))
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM reports"
        ).fetchone()["n"]
    finally:
        conn.close()


def test_upload_form_notices_and_disabled_submit(monkeypatch, tmp_path):
    app, dirs, TestClient = _make_app(monkeypatch, tmp_path)
    http = TestClient(app)
    _verified_session(http, dirs, OWNER_EMAIL)
    page = http.get("/upload", headers=HTML)
    assert page.status_code == 200, page.text
    body = page.text

    # Demo content notice: what Lite checks, mock screening, emergency.
    assert "Lite checks" in body
    assert "mock" in body
    assert EMERGENCY_LINE in body
    # Data-use notice: shared vs never shared.
    for word in ("photo", "claim text", "approximate map location",
                 "verdict"):
        assert word in body
    assert "other logged-in demo users" in body
    assert "email" in body.lower()
    assert "exact coordinates" in body
    assert "file paths" in body
    assert "never" in body
    # Both notices sit above the file picker.
    picker = body.index('name="photo"')
    assert body.index("Lite checks") < picker
    assert body.index("Data use:") < picker
    assert 'type="file"' in body

    # Location picker: two number inputs plus a required consent box.
    assert 'name="location_lat"' in body
    assert 'name="location_lng"' in body
    consent = re.search(
        r'<input[^>]*name="location_consented"[^>]*>', body
    )
    assert consent, "consent checkbox missing"
    assert "required" in consent.group(0)
    assert 'name="csrf_token"' in body

    # Submit starts disabled; the one allowed script gates on
    # location + consent.
    submit = re.search(
        r"<button[^>]*type=\"submit\"[^>]*>", body
    )
    assert submit, "submit button missing"
    assert "disabled" in submit.group(0)
    assert "<script>" in body
    assert "location_consented" in body


def test_upload_requires_location_and_consent_422(
    monkeypatch, tmp_path
):
    app, dirs, TestClient = _make_app(monkeypatch, tmp_path)
    http = TestClient(app)
    _verified_session(http, dirs, OWNER_EMAIL)
    raw = _fresh_png_bytes(seed=21)
    assert (
        hashlib.sha256(raw).hexdigest()
        not in upload_pipeline.load_mock_hashes()
    )
    variants = [
        ("page-422-no-loc", {"lat": None, "lng": None, "consent": True}),
        ("page-422-no-consent", {"lat": "51.5", "lng": "-0.12",
                                 "consent": False}),
    ]
    for client_id, kwargs in variants:
        before = _report_count(dirs["db"])
        resp = _page_upload(http, client_id=client_id, raw=raw, **kwargs)
        assert resp.status_code == 422, (client_id, resp.text)
        # Server re-renders the form with an error (submit still gated).
        assert 'name="csrf_token"' in resp.text
        assert 'name="photo"' in resp.text
        assert _report_count(dirs["db"]) == before


def test_result_card_fields_and_needs_review_banner(
    monkeypatch, tmp_path
):
    app, dirs, TestClient = _make_app(monkeypatch, tmp_path)
    http = TestClient(app)
    api_headers = _verified_session(http, dirs, OWNER_EMAIL)
    raw = _fresh_png_bytes(seed=31)
    assert (
        hashlib.sha256(raw).hexdigest()
        not in upload_pipeline.load_mock_hashes()
    )
    resp = _page_upload(http, client_id="page-result-1", raw=raw)
    assert resp.status_code == 303, resp.text
    location = resp.headers["location"]
    assert location.startswith("/reports/")

    expected = http.get(location, headers=api_headers).json()
    assert expected["needs_review"] is True
    assert expected["reasons"], "stub verdict carries no reasons"

    card = http.get(location, headers=HTML)
    assert card.status_code == 200, card.text
    body = card.text
    # Incident type + probability, severity, confidence.
    top_incident = max(
        expected["incident_probs"], key=expected["incident_probs"].get
    )
    assert top_incident in body
    assert str(expected["incident_probs"][top_incident]) in body
    assert expected["top_severity"] in body
    assert str(expected["confidence"]) in body
    # Authenticity label with every reason listed.
    assert expected["verdict"] in body
    for reason in expected["reasons"]:
        assert reason in body, f"reason missing: {reason}"
    # Needs-review verdict is prominent.
    assert "needs human review" in body
    # Owner sees their own image back (link, never raw paths).
    assert "<img" in body
    assert expected["photo_url"] in body
    assert str(dirs["uploads"]) not in body


def test_mock_rejection_page_generic_only(monkeypatch, tmp_path):
    app, dirs, TestClient = _make_app(monkeypatch, tmp_path)
    http = TestClient(app)
    _verified_session(http, dirs, OWNER_EMAIL)
    fixture = (
        Path(__file__).resolve().parent / "fixtures" / "shapes_basic.png"
    )
    raw = fixture.read_bytes()
    assert (
        hashlib.sha256(raw).hexdigest()
        in upload_pipeline.load_mock_hashes()
    )
    resp = _page_upload(
        http,
        client_id="page-mock-1",
        raw=raw,
        filename="shapes_basic.png",
        claim="this claim text must never surface on rejection",
    )
    assert resp.status_code == 200, resp.text
    body = resp.text
    assert MOCK_REJECTION_DETAIL in body
    assert EMERGENCY_LINE in body
    lowered = body.lower()
    for leaked in ("<img", "confidence", "incident", "severity",
                   "verdict", "reasons", "report", "photo_url", "photo"):
        assert leaked not in lowered, f"rejection page shows {leaked}"
    assert "this claim text must never surface" not in body
    assert _report_count(dirs["db"]) == 0


def test_reports_list_own_only_newest_first_no_images(
    monkeypatch, tmp_path
):
    app, dirs, TestClient = _make_app(monkeypatch, tmp_path)
    owner = TestClient(app)
    other = TestClient(app)
    _verified_session(owner, dirs, OWNER_EMAIL)
    _verified_session(other, dirs, OTHER_EMAIL)

    first = _page_upload(
        owner, client_id="page-list-1", raw=_fresh_png_bytes(seed=41)
    )
    assert first.status_code == 303, first.text
    second = _page_upload(
        owner, client_id="page-list-2", raw=_fresh_png_bytes(seed=42)
    )
    assert second.status_code == 303, second.text
    foreign = _page_upload(
        other, client_id="page-list-other-1",
        raw=_fresh_png_bytes(seed=43),
    )
    assert foreign.status_code == 303, foreign.text

    own_first = int(first.headers["location"].rsplit("/", 1)[-1])
    own_second = int(second.headers["location"].rsplit("/", 1)[-1])
    foreign_id = int(foreign.headers["location"].rsplit("/", 1)[-1])
    assert own_first < own_second

    listing = owner.get("/reports", headers=HTML)
    assert listing.status_code == 200, listing.text
    body = listing.text
    assert f"/reports/{own_first}" in body
    assert f"/reports/{own_second}" in body
    assert f"/reports/{foreign_id}" not in body
    # Newest first.
    assert body.index(f"/reports/{own_second}") < body.index(
        f"/reports/{own_first}"
    )
    # Links only: no image bytes on this page.
    assert "<img" not in body


def test_shared_page_visible_to_other_user_and_404_for_missing(
    monkeypatch, tmp_path
):
    app, dirs, TestClient = _make_app(monkeypatch, tmp_path)
    owner = TestClient(app)
    other = TestClient(app)
    _verified_session(owner, dirs, OWNER_EMAIL)
    other_api = _verified_session(other, dirs, OTHER_EMAIL)

    done = _page_upload(
        owner, client_id="page-shared-1", raw=_fresh_png_bytes(seed=51)
    )
    assert done.status_code == 303, done.text
    report_id = int(done.headers["location"].rsplit("/", 1)[-1])

    shared = other.get(f"/shared/{report_id}", headers=HTML)
    assert shared.status_code == 200, shared.text
    assert PAGE_CLAIM in shared.text
    assert "<img" in shared.text

    # The photo itself is reachable for the other logged-in user.
    expected = other.get(
        f"/shared/{report_id}", headers=other_api
    ).json()
    photo = other.get(expected["photo_url"], headers=other_api)
    assert photo.status_code == 200, photo.text
    assert photo.headers["content-type"].startswith("image/")
    assert photo.content

    # Rejected uploads create no row: missing ids answer with the page.
    missing = other.get("/shared/999999", headers=HTML)
    assert missing.status_code == 404, missing.text
    assert "Not found" in missing.text


def test_dev_server_help_and_signup_wiring(monkeypatch, tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [sys.executable, "-m", "lite.app.server", "--help"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "usage" in proc.stdout.lower()

    # Wiring smoke: the app builds and serves the signup page.
    app, _, TestClient = _make_app(monkeypatch, tmp_path)
    assert TestClient(app).get("/signup").status_code == 200
