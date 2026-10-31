"""Tests for Lite spec 6, objective 6.5: upload restyle + title/category.

TestClient against tmp SQLite + tmp mail/uploads dirs only -- never
the real ``lite/data/`` directory. The CLIP encoder is always stubbed
through the ``create_app(clip_encoder=...)`` seam (fast).

Covered here:

* Upload page as an iOS form sheet: [Cancel] / "New Vouch" / [Post],
  iOS grouped cells, title field, category pill selector, and [Post]
  disabled until pin + consent + photo + description + title are set
  (single inline script, consent text byte-identical).
* Title + category persisted on upload and shown on the owner page,
  the shared page, saved cards, and the map bottom-sheet payload,
  with claim-text fallback for title-less reports.
* Category is display-only user input: it never changes the
  CLIP-derived incident type or any check output.
* Uploads still save lat/lng (never a text address); over-long titles
  and unknown categories answer 422 with nothing stored.

Note on required-ness: the title requirement is enforced by the form
itself ([Post] stays disabled until a title is entered, plus the
``required`` attribute), while the server keeps title optional with a
claim-text fallback. The locked page-flow suites POST title-less
uploads directly and must keep passing unchanged, so the server
cannot hard-require it; old title-less rows stay renderable.
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
from lite.app.server import pipeline as upload_pipeline
from lite.app.server.api import create_app
from lite.app.server.db import connect

TEST_SECRET = "test-jwt-secret-for-upload-restyle-tests-0123456789"
PASSWORD = "correct-horse-9"
ADULT_DOB = (date.today() - timedelta(days=365 * 30)).isoformat()

HTML = {"Accept": "text/html"}

CONSENT_TEXT = (
    "Your photo, claim text, approximate map location, and verdict "
    "will be visible to other logged-in demo users. "
    "Your email and exact location are never shared."
)

OWNER_EMAIL = "restyle-owner@example.com"
PAGE_CLAIM = "a photo of a street with geometric shapes"
PAGE_TITLE = "Corner shop drill"
PAGE_CATEGORY = "fire"


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
    token = http.post(
        "/auth/login",
        json={"email": email, "password": PASSWORD},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


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


def _page_upload(
    http,
    *,
    client_id,
    raw,
    filename="photo.png",
    ctype="image/png",
    claim=PAGE_CLAIM,
    title=PAGE_TITLE,
    category=PAGE_CATEGORY,
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
    }
    if claim is not None:
        data["claim_text"] = claim
    if title is not None:
        data["title"] = title
    if category is not None:
        data["category"] = category
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


def _report_row(db_path, report_id):
    conn = connect(str(db_path))
    try:
        return dict(
            conn.execute(
                "SELECT * FROM reports WHERE id = ?", (report_id,)
            ).fetchone()
        )
    finally:
        conn.close()


def test_sheet_structure_grouped_cells_and_post_gating(
    monkeypatch, tmp_path
):
    app, dirs, TestClient = _make_app(monkeypatch, tmp_path)
    http = TestClient(app)
    _verified_session(http, dirs, OWNER_EMAIL)
    page = http.get("/upload", headers=HTML)
    assert page.status_code == 200, page.text
    body = page.text

    # iOS form sheet nav: [Cancel] left, "New Vouch" centered, [Post]
    # right, where [Post] is the form submit and starts disabled.
    assert "New Vouch" in body
    cancel = re.search(
        r'<a[^>]*href="/map"[^>]*>Cancel</a>', body
    )
    assert cancel, "Cancel link to /map missing"
    submit = re.search(
        r'<button[^>]*id="upload_submit"[^>]*>', body
    )
    assert submit, "Post submit button missing"
    assert 'type="submit"' in submit.group(0)
    assert "disabled" in submit.group(0)
    assert ">Post</button>" in body

    # iOS grouped cells wrap the new fields.
    assert 'class="grouped"' in body

    # Title field: plain text, capped at 80 chars, required.
    title = re.search(
        r'<input[^>]*name="title"[^>]*>', body
    )
    assert title, "title field missing"
    assert 'type="text"' in title.group(0)
    assert 'maxlength="80"' in title.group(0)
    assert "required" in title.group(0)

    # Category pill selector: exactly the CLIP incident-type labels,
    # no invented categories.
    expected = set(load_config().incident_prompts)
    found = set(
        re.findall(r'name="category" value="([^"]+)"', body)
    )
    assert found == expected, sorted(found ^ expected)

    # Description (claim text) and photo fields stay, both required
    # so [Post] can gate on them.
    assert 'name="claim_text"' in body
    assert 'name="photo"' in body
    assert 'type="file"' in body

    # Exactly one inline script block, gating [Post] on pin +
    # consent + photo + description + title.
    assert len(re.findall(r"<script>", body)) == 1, body.count("<script>")
    script = _form_script(body)
    for marker in (
        "upload_submit",
        "location_consented",
        "location_lat",
        "location_lng",
        "report_title",
        "photo_input",
        "claim_text",
    ):
        assert marker in script, f"gate misses {marker}"
    assert re.search(
        r"submit\.disabled\s*=\s*!\(.*consent\.checked", script
    ), "submit gate does not require consent"
    assert "hasTitle" in script
    assert "hasPhoto" in script
    assert "hasClaim" in script

    # Location picker and byte-identical consent text stay.
    assert 'id="location_map"' in body
    assert 'id="use_location"' in body
    assert "Use my location" in body
    assert CONSENT_TEXT in body


def test_title_and_category_persisted_and_shown(
    monkeypatch, tmp_path
):
    app, dirs, TestClient = _make_app(monkeypatch, tmp_path)
    http = TestClient(app)
    api_headers = _verified_session(http, dirs, OWNER_EMAIL)
    raw = _fresh_png_bytes(seed=601)
    assert (
        hashlib.sha256(raw).hexdigest()
        not in upload_pipeline.load_mock_hashes()
    )
    resp = _page_upload(http, client_id="restyle-1", raw=raw)
    assert resp.status_code == 303, resp.text
    report_id = int(resp.headers["location"].rsplit("/", 1)[-1])

    # Stored on the row: lat/lng plus the new user inputs.
    row = _report_row(dirs["db"], report_id)
    assert row["title"] == PAGE_TITLE
    assert row["category"] == PAGE_CATEGORY
    assert row["location_lat"] == 51.5
    assert row["location_lng"] == -0.12

    # The owner endpoint keeps its frozen key set and still serves.
    payload = http.get(
        f"/reports/{report_id}", headers=api_headers
    ).json()
    assert payload["claim_text"] == PAGE_CLAIM
    # The map payload carries the stored inputs for the bottom sheet.
    incidents = http.get("/api/incidents", headers=api_headers).json()
    props = [
        feature["properties"]
        for feature in incidents["features"]
        if feature["properties"]["report_id"] == report_id
    ]
    assert len(props) == 1
    assert props[0]["title"] == PAGE_TITLE
    assert props[0]["category"] == PAGE_CATEGORY

    # Owner page and shared page show the title; the category shows
    # as its own field next to (never instead of) the incident type.
    owner = http.get(f"/reports/{report_id}", headers=HTML)
    assert owner.status_code == 200, owner.text
    assert PAGE_TITLE in owner.text
    assert "Category" in owner.text
    assert "fire" in owner.text
    assert "Incident type" in owner.text
    shared = http.get(f"/shared/{report_id}", headers=HTML)
    assert shared.status_code == 200, shared.text
    assert PAGE_TITLE in shared.text
    assert "Category" in shared.text

    # Map page: bottom-sheet title wiring plus the no-JS fallback
    # link using the title.
    map_page = http.get("/map", headers=HTML)
    assert map_page.status_code == 200, map_page.text
    assert 'id="sheet_title"' in map_page.text
    assert "props.title || props.claim_text" in map_page.text
    assert f">{PAGE_TITLE}</a>" in map_page.text

    # Saved card shows the title.
    csrf = _csrf(map_page.text)
    saved = http.post(
        "/saved",
        data={"report_id": str(report_id), "csrf_token": csrf},
        follow_redirects=False,
    )
    assert saved.status_code == 303, saved.text
    cards = http.get("/saved", headers=HTML)
    assert cards.status_code == 200, cards.text
    assert PAGE_TITLE in cards.text


def test_category_does_not_affect_checks(monkeypatch, tmp_path):
    app, dirs, TestClient = _make_app(monkeypatch, tmp_path)
    http = TestClient(app)
    api_headers = _verified_session(http, dirs, OWNER_EMAIL)
    first = _page_upload(
        http,
        client_id="restyle-cat-a",
        raw=_fresh_png_bytes(seed=611),
        claim=PAGE_CLAIM,
        title="First heading",
        category="fire",
    )
    assert first.status_code == 303, first.text
    second = _page_upload(
        http,
        client_id="restyle-cat-b",
        raw=_fresh_png_bytes(seed=612),
        claim=PAGE_CLAIM,
        title="Second heading",
        category="flood",
    )
    assert second.status_code == 303, second.text
    first_id = int(first.headers["location"].rsplit("/", 1)[-1])
    second_id = int(second.headers["location"].rsplit("/", 1)[-1])

    first_body = http.get(
        f"/reports/{first_id}", headers=api_headers
    ).json()
    second_body = http.get(
        f"/reports/{second_id}", headers=api_headers
    ).json()
    # Same stubbed CLIP outputs whatever the user picked: the check
    # outputs are identical while the stored categories differ.
    assert first_body["incident_probs"] == second_body["incident_probs"]
    assert first_body["severity_probs"] == second_body["severity_probs"]
    assert first_body["verdict"] == second_body["verdict"]
    assert "category" not in first_body
    assert _report_row(dirs["db"], first_id)["category"] == "fire"
    assert _report_row(dirs["db"], second_id)["category"] == "flood"
    top = max(
        first_body["incident_probs"],
        key=first_body["incident_probs"].get,
    )
    assert top in load_config().incident_prompts


def test_latlng_saved_never_address_and_bad_input_422(
    monkeypatch, tmp_path
):
    app, dirs, TestClient = _make_app(monkeypatch, tmp_path)
    http = TestClient(app)
    _verified_session(http, dirs, OWNER_EMAIL)
    raw = _fresh_png_bytes(seed=621)
    assert (
        hashlib.sha256(raw).hexdigest()
        not in upload_pipeline.load_mock_hashes()
    )

    # Over-long titles and unknown categories answer 422 with nothing
    # stored, like the spec-5.1 location rule.
    before = _report_count(dirs["db"])
    long_title = _page_upload(
        http, client_id="restyle-422-long", raw=raw, title="t" * 81
    )
    assert long_title.status_code == 422, long_title.text
    bad_category = _page_upload(
        http, client_id="restyle-422-cat", raw=raw, category="volcano"
    )
    assert bad_category.status_code == 422, bad_category.text
    assert _report_count(dirs["db"]) == before

    # A plain upload saves lat/lng; no page carries a text address.
    done = _page_upload(http, client_id="restyle-addr-1", raw=raw)
    assert done.status_code == 303, done.text
    report_id = int(done.headers["location"].rsplit("/", 1)[-1])
    row = _report_row(dirs["db"], report_id)
    assert row["location_lat"] == 51.5
    assert row["location_lng"] == -0.12
    # The form captures coordinates only: no address field exists.
    form = http.get("/upload", headers=HTML)
    assert form.status_code == 200, form.text
    assert 'name="address"' not in form.text
    assert "autocomplete" not in form.text.lower()
    for route in (f"/reports/{report_id}",
                  f"/shared/{report_id}", "/saved"):
        page = http.get(route, headers=HTML)
        assert page.status_code == 200, route
        assert "address" not in page.text.lower(), route


def test_titleless_reports_fall_back_and_render(monkeypatch, tmp_path):
    app, dirs, TestClient = _make_app(monkeypatch, tmp_path)
    http = TestClient(app)
    api_headers = _verified_session(http, dirs, OWNER_EMAIL)
    raw = _fresh_png_bytes(seed=631)
    assert (
        hashlib.sha256(raw).hexdigest()
        not in upload_pipeline.load_mock_hashes()
    )
    # The JSON route (and old rows) carry no title: still accepted.
    resp = http.post(
        "/analyze",
        data={
            "client_report_id": "restyle-untitled-1",
            "location_lat": "51.5",
            "location_lng": "-0.12",
            "location_consented": "true",
            "location_source": "browser",
            "claim_text": PAGE_CLAIM,
        },
        files={"photo": ("photo.png", raw, "image/png")},
        headers=api_headers,
    )
    assert resp.status_code == 200, resp.text
    report_id = int(resp.json()["report_id"])

    # The frozen retrieval body carries no title key; every view
    # falls back to the claim text, and old rows still render.
    payload = http.get(
        f"/reports/{report_id}", headers=api_headers
    ).json()
    assert "title" not in payload
    assert payload["claim_text"] == PAGE_CLAIM
    incidents = http.get("/api/incidents", headers=api_headers).json()
    props = [
        feature["properties"]
        for feature in incidents["features"]
        if feature["properties"]["report_id"] == report_id
    ]
    assert len(props) == 1
    assert props[0]["title"] is None
    for route in (f"/reports/{report_id}", f"/shared/{report_id}"):
        page = http.get(route, headers=HTML)
        assert page.status_code == 200, route
        assert PAGE_CLAIM in page.text, route
    fallback = http.get("/map", headers=HTML)
    assert fallback.status_code == 200, fallback.text
    assert f">{PAGE_CLAIM}</a>" in fallback.text
    csrf = _csrf(fallback.text)
    assert http.post(
        "/saved",
        data={"report_id": str(report_id), "csrf_token": csrf},
        follow_redirects=False,
    ).status_code == 303
    cards = http.get("/saved", headers=HTML)
    assert cards.status_code == 200, cards.text
    assert PAGE_CLAIM in cards.text


def test_long_claim_truncated_only_in_title_slot(
    monkeypatch, tmp_path
):
    app, dirs, TestClient = _make_app(monkeypatch, tmp_path)
    http = TestClient(app)
    api_headers = _verified_session(http, dirs, OWNER_EMAIL)
    long_claim = "witnessed damage near the market square " * 4
    long_claim = long_claim.strip()
    assert len(long_claim) > 80
    resp = http.post(
        "/analyze",
        data={
            "client_report_id": "restyle-long-1",
            "location_lat": "51.5",
            "location_lng": "-0.12",
            "location_consented": "true",
            "location_source": "browser",
            "claim_text": long_claim,
        },
        files={
            "photo": ("photo.png", _fresh_png_bytes(seed=641),
                      "image/png")
        },
        headers=api_headers,
    )
    assert resp.status_code == 200, resp.text
    report_id = int(resp.json()["report_id"])
    page = http.get(f"/shared/{report_id}", headers=HTML)
    assert page.status_code == 200, page.text
    # Title slot truncates; the description still shows the full text.
    assert (long_claim[:77] + "...") in page.text
    assert long_claim in page.text
