"""Tests for Lite spec 5, objective 5.1: required location capture.

TestClient against tmp SQLite + tmp mail/uploads dirs only -- never
the real ``lite/data/`` directory. The CLIP encoder is always stubbed
through the ``create_app(clip_encoder=...)`` seam (fast).

Pages under test: ``GET /upload`` gains (a) a "Use my location"
button filling the lat/lng inputs via browser geolocation, (b) a
small clickable picker map (MapLibre GL JS via CDN plus OpenFreeMap
tiles: click sets the pin and the inputs), (c) consent-off clearing
the pin/inputs before submit, and (d) the exact consent text next to
the checkbox. Server behavior is unchanged: ``POST /upload`` without
a pin or consent answers 422 with nothing stored (repeated here at
page level). No browser automation is required: the geolocation, map
click, and clear behaviors are asserted as wired handler code in the
single allowed upload-form script.
"""

from __future__ import annotations

import io
import random
import re
from datetime import date, timedelta

from PIL import Image

from lite.app.server.api import create_app
from lite.app.server.db import connect

TEST_SECRET = "test-jwt-secret-for-location-capture-tests-0123456789"
PASSWORD = "correct-horse-9"
ADULT_DOB = (date.today() - timedelta(days=365 * 30)).isoformat()

HTML = {"Accept": "text/html"}

CONSENT_TEXT = (
    "Your photo, claim text, approximate map location, and verdict "
    "will be visible to other logged-in demo users. "
    "Your email and exact location are never shared."
)

OWNER_EMAIL = "location-owner@example.com"


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
    from fastapi.testclient import TestClient

    app = create_app(
        db_path=dirs["db"],
        mail_dir=dirs["mail"],
        uploads_dir=dirs["uploads"],
        clip_encoder=FanStub(),
    )
    return app, dirs, TestClient


def _mail_token(mail_dir, email) -> str:
    from pathlib import Path

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


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "page has no CSRF token field"
    return match.group(1)


def _form_script(body: str) -> str:
    """The single allowed upload-form script block."""
    match = re.search(
        r"<script>(.*?)</script>", body, re.DOTALL | re.IGNORECASE
    )
    assert match, "upload page has no script block"
    return match.group(1)


def _report_count(db_path) -> int:
    conn = connect(str(db_path))
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM reports"
        ).fetchone()["n"]
    finally:
        conn.close()


def _page_upload(
    http,
    *,
    client_id,
    raw,
    filename="photo.png",
    ctype="image/png",
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
        "claim_text": "a photo of a street with geometric shapes",
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


def test_geolocate_button_and_picker_map_present(monkeypatch, tmp_path):
    app, dirs, TestClient = _make_app(monkeypatch, tmp_path)
    http = TestClient(app)
    _verified_session(http, dirs, OWNER_EMAIL)
    page = http.get("/upload", headers=HTML)
    assert page.status_code == 200, page.text
    body = page.text

    # (a) "Use my location" button filling the inputs via geolocation.
    geo = re.search(
        r'<button[^>]*id="use_location"[^>]*>(.*?)</button>',
        body,
        re.DOTALL,
    )
    assert geo, "geolocate button missing"
    assert 'type="button"' in geo.group(0)
    assert "Use my location" in geo.group(1)
    script = _form_script(body)
    assert "use_location" in script
    assert "navigator.geolocation" in script
    assert "getCurrentPosition" in script

    # (b) Small clickable picker map: container plus MapLibre via CDN
    # plus OpenFreeMap tiles; a map click sets the pin and inputs.
    assert 'id="location_map"' in body
    assert "maplibre-gl" in body
    assert "tiles.openfreemap.org" in body
    assert "location_map" in script
    assert re.search(r'\.on\(\s*"click"', script), (
        "picker map has no click handler"
    )

    # (d) The exact consent text next to the checkbox.
    consent = re.search(
        r'<input[^>]*name="location_consented"[^>]*>', body
    )
    assert consent, "consent checkbox missing"
    labels = re.findall(r"<label>(.*?)</label>", body, re.DOTALL)
    consent_labels = [
        block for block in labels if 'name="location_consented"' in block
    ]
    assert consent_labels, "consent label missing"
    assert CONSENT_TEXT in consent_labels[0]


def test_submit_gated_on_pin_and_consent(monkeypatch, tmp_path):
    app, dirs, TestClient = _make_app(monkeypatch, tmp_path)
    http = TestClient(app)
    _verified_session(http, dirs, OWNER_EMAIL)
    page = http.get("/upload", headers=HTML)
    assert page.status_code == 200, page.text
    body = page.text

    # Submit starts disabled.
    submit = re.search(r"<button[^>]*type=\"submit\"[^>]*>", body)
    assert submit, "submit button missing"
    assert "disabled" in submit.group(0)

    # The gate needs both a pin (lat/lng filled) and consent checked.
    script = _form_script(body)
    assert "upload_submit" in script
    assert "location_consented" in script
    assert re.search(
        r"submit\.disabled\s*=\s*!\(.*consent\.checked", script
    ), "submit gate does not require consent"
    assert "location_lat" in script and "location_lng" in script


def test_consent_off_clears_pin(monkeypatch, tmp_path):
    app, dirs, TestClient = _make_app(monkeypatch, tmp_path)
    http = TestClient(app)
    _verified_session(http, dirs, OWNER_EMAIL)
    page = http.get("/upload", headers=HTML)
    assert page.status_code == 200, page.text
    script = _form_script(page.text)

    # The script wires the consent checkbox to a clear handler: when
    # consent is unchecked, the pin and inputs are cleared (values
    # emptied and the map marker removed) before submit.
    assert re.search(
        r"consent\.addEventListener\(\s*\"change\"", script
    ), "no consent change handler"
    assert re.search(r"if\s*\(\s*!consent\.checked\s*\)", script), (
        "consent handler does not branch on unchecked"
    )
    assert re.search(
        r"function clearPin\(\).*?marker\.remove\(\)",
        script,
        re.DOTALL,
    ), "no pin-clearing handler removing the marker"


def test_upload_without_pin_or_consent_422_nothing_stored(
    monkeypatch, tmp_path
):
    app, dirs, TestClient = _make_app(monkeypatch, tmp_path)
    http = TestClient(app)
    _verified_session(http, dirs, OWNER_EMAIL)
    raw = _fresh_png_bytes(seed=61)
    variants = [
        ("capture-422-no-pin", {"lat": None, "lng": None,
                                "consent": True}),
        ("capture-422-no-consent", {"lat": "51.5", "lng": "-0.12",
                                    "consent": False}),
    ]
    for client_id, kwargs in variants:
        before = _report_count(dirs["db"])
        resp = _page_upload(http, client_id=client_id, raw=raw, **kwargs)
        assert resp.status_code == 422, (client_id, resp.text)
        assert _report_count(dirs["db"]) == before
