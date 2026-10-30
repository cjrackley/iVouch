"""Tests for Lite spec 3, objective 3.2 (fix): cookie photo transport.

A real browser renders ``<img>`` tags with cookies only -- never an
``Authorization`` header -- so the photo URLs on the community and
result pages must serve bytes to a cookie session. Covered here:

* ``GET /shared/photos/{id}`` (page-router cookie route): 200 bytes
  for an accepted report's photo for another logged-in user, 404 for
  rejected/missing, owner-only otherwise, anonymous 404.
* The owner card's ``<img>`` (``/api/photos/{id}``) serves the same
  bytes to a cookie session, while Bearer-token and anonymous
  behavior on that URL is unchanged (200 / 401).

Every client below logs in through the page flow only (the HttpOnly
``lite_session`` cookie in the TestClient jar). No test here ever
sends an ``Authorization`` header. TestClient against tmp SQLite +
tmp mail/uploads dirs only; the CLIP encoder is stubbed (fast).
Fresh in-memory PNG bytes exercise the accept path (every committed
fixture is mock-listed); fixture bytes exercise rejection only.
"""

from __future__ import annotations

import hashlib
import io
import random
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from lite.app.server import pipeline as upload_pipeline
from lite.app.server.api import create_app
from lite.app.server.db import connect

TEST_SECRET = "test-jwt-secret-for-photo-cookie-tests-0123456789"
PASSWORD = "correct-horse-9"
ADULT_DOB = (date.today() - timedelta(days=365 * 30)).isoformat()

HTML = {"Accept": "text/html"}

OWNER_EMAIL = "cookie-owner@example.com"
OTHER_EMAIL = "cookie-other@example.com"
PAGE_CLAIM = "a photo of a street with geometric shapes"


class FanStub:
    """Deterministic stub encoder (same shape as the 3.2 suite's)."""

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
    app = create_app(
        db_path=dirs["db"],
        mail_dir=dirs["mail"],
        uploads_dir=dirs["uploads"],
        clip_encoder=FanStub(),
    )
    return app, dirs


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


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "page has no CSRF token field"
    return match.group(1)


def _cookie_login(http: TestClient, dirs, email) -> None:
    """Register + verify via API, then log in via the page.

    Returns nothing: the proof is the ``lite_session`` cookie in the
    client's jar. Never fetches a Bearer token, so every later call
    on this client is cookie-only.
    """
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
    assert "lite_session" in http.cookies, "page login set no cookie"


def _page_upload(http: TestClient, *, client_id, raw, **kwargs):
    """POST one upload through the page flow (no redirect following)."""
    landing = http.get("/upload", headers=HTML)
    assert landing.status_code == 200, landing.text
    data = {
        "csrf_token": _csrf(landing.text),
        "client_report_id": client_id,
        "location_source": "manual_pin",
        "location_lat": "51.5",
        "location_lng": "-0.12",
        "location_consented": "true",
        "claim_text": PAGE_CLAIM,
    }
    data.update(kwargs)
    return http.post(
        "/upload",
        data=data,
        files={"photo": ("photo.png", raw, "image/png")},
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


def _accepted_upload(owner: TestClient, *, client_id, seed) -> tuple[bytes, int]:
    """Upload fresh bytes through the page flow; return (raw, id)."""
    raw = _fresh_png_bytes(seed=seed)
    assert (
        hashlib.sha256(raw).hexdigest()
        not in upload_pipeline.load_mock_hashes()
    )
    resp = _page_upload(owner, client_id=client_id, raw=raw)
    assert resp.status_code == 303, resp.text
    return raw, int(resp.headers["location"].rsplit("/", 1)[-1])


def test_cookie_photo_accepted_other_user_sees_bytes(monkeypatch, tmp_path):
    """Other logged-in user fetches accepted photo bytes, cookie-only."""
    app, dirs = _make_app(monkeypatch, tmp_path)
    owner = TestClient(app)
    other = TestClient(app)
    _cookie_login(owner, dirs, OWNER_EMAIL)
    _cookie_login(other, dirs, OTHER_EMAIL)

    raw, report_id = _accepted_upload(
        owner, client_id="cookie-accept-1", seed=601
    )

    # Plain GET: cookies flow, no Authorization header anywhere.
    photo = other.get(f"/shared/photos/{report_id}")
    assert photo.status_code == 200, photo.text
    assert photo.headers["content-type"].startswith("image/")
    assert photo.content == raw

    # Owner's own cookie session sees the same bytes.
    own = owner.get(f"/shared/photos/{report_id}")
    assert own.status_code == 200, own.text
    assert own.content == raw

    # The community page points its <img> at the cookie route.
    shared = other.get(f"/shared/{report_id}", headers=HTML)
    assert shared.status_code == 200, shared.text
    assert "<img" in shared.text
    assert f"/shared/photos/{report_id}" in shared.text


def test_cookie_photo_rejected_is_404(monkeypatch, tmp_path):
    """Mock-gate rejection creates no row: cookie photo route 404s."""
    app, dirs = _make_app(monkeypatch, tmp_path)
    owner = TestClient(app)
    _cookie_login(owner, dirs, OWNER_EMAIL)
    fixture = (
        Path(__file__).resolve().parent / "fixtures" / "shapes_basic.png"
    )
    raw = fixture.read_bytes()
    assert (
        hashlib.sha256(raw).hexdigest()
        in upload_pipeline.load_mock_hashes()
    )
    resp = _page_upload(
        owner,
        client_id="cookie-reject-1",
        raw=raw,
    )
    assert resp.status_code == 200, resp.text
    assert _report_count(dirs["db"]) == 0

    assert owner.get("/shared/photos/1").status_code == 404
    assert owner.get("/shared/photos/999999").status_code == 404


def _insert_pending_report_with_photo(dirs, email, raw) -> tuple[int, int]:
    """Insert an unaccepted report row plus its stored photo file.

    Returns ``(account_id, report_id)``. No ``check_results`` row, so
    the report is not accepted and the photo stays owner-only.
    """
    conn = connect(str(dirs["db"]))
    try:
        owner_id = conn.execute(
            "SELECT id FROM accounts WHERE email = ?",
            (email.strip().lower(),),
        ).fetchone()["id"]
        cur = conn.execute(
            "INSERT INTO reports (account_id, client_report_id,"
            " sha256, status, created_at, location_lat,"
            " location_lng, location_consented, location_source)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                owner_id,
                "cookie-pending-1",
                hashlib.sha256(raw).hexdigest(),
                "pending",
                datetime.now(timezone.utc).isoformat(),
                51.5,
                -0.12,
                1,
                "manual_pin",
            ),
        )
        report_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    photo_dir = Path(dirs["uploads"]) / str(owner_id)
    photo_dir.mkdir(parents=True, exist_ok=True)
    (photo_dir / f"{report_id}.png").write_bytes(raw)
    return owner_id, report_id


def test_cookie_photo_unaccepted_is_owner_only(monkeypatch, tmp_path):
    """Unaccepted photo bytes: owner 200, other user 404, cookie-only."""
    app, dirs = _make_app(monkeypatch, tmp_path)
    owner = TestClient(app)
    other = TestClient(app)
    _cookie_login(owner, dirs, OWNER_EMAIL)
    _cookie_login(other, dirs, OTHER_EMAIL)

    raw = _fresh_png_bytes(seed=602)
    _, report_id = _insert_pending_report_with_photo(
        dirs, OWNER_EMAIL, raw
    )

    own = owner.get(f"/shared/photos/{report_id}")
    assert own.status_code == 200, own.text
    assert own.headers["content-type"].startswith("image/")
    assert own.content == raw

    foreign = other.get(f"/shared/photos/{report_id}")
    assert foreign.status_code == 404, foreign.text

    # Same owner-only rule through the owner card's photo URL.
    own_api = owner.get(f"/api/photos/{report_id}")
    assert own_api.status_code == 200, own_api.text
    assert own_api.content == raw
    assert other.get(f"/api/photos/{report_id}").status_code == 404


def test_cookie_photo_requires_login(monkeypatch, tmp_path):
    """Anonymous callers get 404 on the cookie route, 401 on the API."""
    app, dirs = _make_app(monkeypatch, tmp_path)
    owner = TestClient(app)
    _cookie_login(owner, dirs, OWNER_EMAIL)
    _, report_id = _accepted_upload(
        owner, client_id="cookie-anon-1", seed=603
    )

    anon = TestClient(app)
    assert anon.get(f"/shared/photos/{report_id}").status_code == 404
    assert anon.get(f"/api/photos/{report_id}").status_code == 401


def test_owner_card_photo_url_works_with_cookie(monkeypatch, tmp_path):
    """Owner card <img> URL serves bytes to a cookie session (no 401)."""
    app, dirs = _make_app(monkeypatch, tmp_path)
    owner = TestClient(app)
    _cookie_login(owner, dirs, OWNER_EMAIL)
    raw, report_id = _accepted_upload(
        owner, client_id="cookie-card-1", seed=604
    )

    card = owner.get(f"/reports/{report_id}", headers=HTML)
    assert card.status_code == 200, card.text
    assert "<img" in card.text
    assert f"/api/photos/{report_id}" in card.text

    photo = owner.get(f"/api/photos/{report_id}")
    assert photo.status_code == 200, photo.text
    assert photo.headers["content-type"].startswith("image/")
    assert photo.content == raw
