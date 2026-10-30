"""Tests for Lite spec 2, objective 2.4: report retrieval.

TestClient against tmp SQLite + tmp mail/uploads dirs only -- never
the real ``lite/data/`` directory. The CLIP encoder is always stubbed
through the ``create_app(clip_encoder=...)`` seam (fast; the live
model path is objective 2.5's, never here).

Endpoints under test: ``GET /reports``, ``GET /reports/{id}``
(owner-only), ``GET /api/incidents`` (shared FeatureCollection),
``GET /shared/{id}`` (shared community entry), and
``GET /api/photos/{report_id}`` (shared photo bytes).

NOTE: every committed fixture image is on the mock hash list, so
accepted-upload tests generate fresh in-memory JPEG bytes (never
fixtures). Fixture bytes are used exactly once: to exercise the
mock-gate rejection path, which must leave no retrievable report.
"""

from __future__ import annotations

import hashlib
import io
import json
import random
import re
from datetime import date, timedelta
from pathlib import Path

from PIL import Image

from lite.app.server import pipeline as upload_pipeline
from lite.app.server.api import create_app
from lite.app.server.db import connect

TEST_SECRET = "test-jwt-secret-for-retrieval-tests-0123456789"
PASSWORD = "correct-horse-9"
ADULT_DOB = (date.today() - timedelta(days=365 * 30)).isoformat()

OWNER_EMAIL = "owner@example.com"
OTHER_EMAIL = "other@example.com"

# Exact coordinates: fractional on purpose, so a jittered display
# value can share a string prefix with them (e.g. 51.507 vs 51.5074)
# and only an exact-float comparison is a valid leak check.
LAT = 51.50745
LNG = -0.12762
OWNER_CLAIM = "a photo of a street with geometric shapes"
OTHER_CLAIM = "a photo of a flooded road at night"
MOCK_REJECTION_DETAIL = "upload could not be accepted"

OWNER_KEYS = {
    "report_id",
    "status",
    "client_report_id",
    "photo_url",
    "claim_text",
    "display_lat",
    "display_lng",
    "incident_probs",
    "severity_probs",
    "top_severity",
    "verdict",
    "reasons",
    "confidence",
    "needs_review",
    "created_at",
}
SHARED_KEYS = {
    "report_id",
    "photo_url",
    "claim_text",
    "display_lat",
    "display_lng",
    "incident_probs",
    "severity_probs",
    "top_severity",
    "verdict",
    "reasons",
    "confidence",
    "created_at",
}


class FanStub:
    """Deterministic stub encoder (same shape as the 2.3 suite's)."""

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


def _make_client(monkeypatch, tmp_path, encoder=None):
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
        clip_encoder=encoder if encoder is not None else FanStub(),
    )
    return TestClient(app), dirs


def _verified_account(http, dirs, email):
    """Register, verify via console mail, log in; return (headers, id)."""
    resp = http.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "date_of_birth": ADULT_DOB,
        },
    )
    assert resp.status_code == 200
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
    assert verify.status_code == 200
    login = http.post(
        "/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert login.status_code == 200
    assert login.json()["email_verified"] is True
    headers = {
        "Authorization": f"Bearer {login.json()['access_token']}"
    }
    me = http.get("/account", headers=headers)
    assert me.status_code == 200
    return headers, me.json()["id"]


def _upload(http, headers, raw, claim, client_id):
    resp = http.post(
        "/analyze",
        data={
            "client_report_id": client_id,
            "location_lat": str(LAT),
            "location_lng": str(LNG),
            "location_consented": "true",
            "location_source": "browser",
            "claim_text": claim,
        },
        files={"photo": ("photo.jpg", raw, "image/jpeg")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _setup_two_accounts(monkeypatch, tmp_path):
    """Two verified accounts, one accepted JPEG upload each."""
    http, dirs = _make_client(monkeypatch, tmp_path)
    owner_headers, _ = _verified_account(http, dirs, OWNER_EMAIL)
    other_headers, _ = _verified_account(http, dirs, OTHER_EMAIL)
    owner_raw = _fresh_jpeg_bytes(seed=101)
    other_raw = _fresh_jpeg_bytes(seed=102)
    assert owner_raw != other_raw
    owner_upload = _upload(
        http, owner_headers, owner_raw, OWNER_CLAIM, "retrieval-owner-1"
    )
    assert "report_id" in owner_upload
    other_upload = _upload(
        http, other_headers, other_raw, OTHER_CLAIM, "retrieval-other-1"
    )
    assert "report_id" in other_upload
    assert owner_upload["report_id"] != other_upload["report_id"]
    return http, dirs, owner_headers, other_headers, owner_upload, other_upload


def _report_list(http, headers):
    resp = http.get("/reports", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    if isinstance(body, dict):
        assert "reports" in body, f"unexpected /reports shape: {body!r}"[:500]
        body = body["reports"]
    assert isinstance(body, list), f"unexpected /reports shape: {body!r}"[:500]
    return body


def _list_ids(items):
    ids = set()
    for item in items:
        assert isinstance(item, dict), f"unexpected list entry: {item!r}"[:300]
        assert "report_id" in item or "id" in item, (
            f"list entry has no report id: {sorted(item)}"
        )
        ids.add(item.get("report_id", item.get("id")))
    return ids


def _walk_floats(node):
    """Yield every float (or int) leaf in parsed JSON, recursively."""
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk_floats(value)
    elif isinstance(node, (list, tuple)):
        for value in node:
            yield from _walk_floats(value)
    elif isinstance(node, bool):
        return
    elif isinstance(node, (int, float)):
        yield node


def _find_display(node):
    """Find (display_lat, display_lng) anywhere nested; else None."""
    if isinstance(node, dict):
        if "display_lat" in node and "display_lng" in node:
            return (node["display_lat"], node["display_lng"])
        for value in node.values():
            found = _find_display(value)
            if found is not None:
                return found
    elif isinstance(node, (list, tuple)):
        for value in node:
            found = _find_display(value)
            if found is not None:
                return found
    return None


def _find_feature(features, report_id):
    """Locate the feature/entry mentioning report_id (any nesting)."""
    for feature in features:
        if report_id in set(_walk_floats(feature)):
            return feature
        if str(report_id) in json.dumps(feature):
            return feature
    return None


def _assert_no_leaks(parsed, raw_text, dirs):
    """Shared-surface sweep: no emails, exact coords, or file paths."""
    assert OWNER_EMAIL not in raw_text
    assert OTHER_EMAIL not in raw_text
    floats = list(_walk_floats(parsed))
    assert LAT not in floats, f"exact lat {LAT} leaked: {raw_text[:300]}"
    assert LNG not in floats, f"exact lng {LNG} leaked: {raw_text[:300]}"
    assert str(dirs["uploads"]) not in raw_text
    assert str(dirs["db"]) not in raw_text
    assert "/uploads/" not in raw_text.replace("\\", "/")


def _db_status(dirs, report_id):
    conn = connect(str(dirs["db"]))
    try:
        row = conn.execute(
            "SELECT status FROM reports WHERE id = ?", (report_id,)
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    return row["status"]


def test_owner_endpoints_exact_keys_and_list_isolation(
    monkeypatch, tmp_path
):
    http, dirs, owner_headers, other_headers, owner_upload, other_upload = (
        _setup_two_accounts(monkeypatch, tmp_path)
    )
    owner_id = owner_upload["report_id"]
    other_id = other_upload["report_id"]

    owner_items = _report_list(http, owner_headers)
    assert owner_id in _list_ids(owner_items)
    assert other_id not in _list_ids(owner_items)

    other_items = _report_list(http, other_headers)
    assert other_id in _list_ids(other_items)
    assert owner_id not in _list_ids(other_items)

    detail = http.get(f"/reports/{owner_id}", headers=owner_headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert set(body) == OWNER_KEYS, f"owner keys: {sorted(body)}"
    assert body["report_id"] == owner_id
    assert body["client_report_id"] == "retrieval-owner-1"
    assert body["claim_text"] == OWNER_CLAIM
    assert body["status"] == _db_status(dirs, owner_id)
    assert isinstance(body["photo_url"], str) and str(owner_id) in body[
        "photo_url"
    ]
    # Retrieval mirrors the finished pipeline output unchanged.
    for key in (
        "incident_probs",
        "severity_probs",
        "top_severity",
        "verdict",
        "reasons",
        "confidence",
        "needs_review",
    ):
        assert body[key] == owner_upload[key], key
    assert body["created_at"]


def test_other_account_blocked_from_owner_but_shared_allowed(
    monkeypatch, tmp_path
):
    http, dirs, owner_headers, other_headers, owner_upload, _ = (
        _setup_two_accounts(monkeypatch, tmp_path)
    )
    owner_id = owner_upload["report_id"]

    blocked = http.get(f"/reports/{owner_id}", headers=other_headers)
    assert blocked.status_code in (403, 404), blocked.text

    anon = http.get("/reports")
    assert anon.status_code == 401, anon.text
    anon_detail = http.get(f"/reports/{owner_id}")
    assert anon_detail.status_code == 401, anon_detail.text

    incidents = http.get("/api/incidents", headers=other_headers)
    assert incidents.status_code == 200, incidents.text
    payload = incidents.json()
    assert payload.get("type") == "FeatureCollection"
    assert isinstance(payload.get("features"), list)
    feature = _find_feature(payload["features"], owner_id)
    assert feature is not None, "accepted report missing from incidents"

    shared = http.get(f"/shared/{owner_id}", headers=other_headers)
    assert shared.status_code == 200, shared.text
    shared_body = shared.json()
    assert set(shared_body) == SHARED_KEYS, f"shared keys: {sorted(shared_body)}"
    assert shared_body["report_id"] == owner_id
    assert shared_body["claim_text"] == OWNER_CLAIM
    for key in (
        "incident_probs",
        "severity_probs",
        "top_severity",
        "verdict",
        "reasons",
        "confidence",
    ):
        assert shared_body[key] == owner_upload[key], key
    assert shared_body["created_at"]


def test_forbidden_fields_sweep_and_display_stability(
    monkeypatch, tmp_path
):
    http, dirs, owner_headers, other_headers, owner_upload, other_upload = (
        _setup_two_accounts(monkeypatch, tmp_path)
    )
    owner_id = owner_upload["report_id"]

    first = http.get(f"/reports/{owner_id}", headers=owner_headers)
    second = http.get(f"/reports/{owner_id}", headers=owner_headers)
    assert first.status_code == 200 and second.status_code == 200
    display_owner = (first.json()["display_lat"], first.json()["display_lng"])
    assert (second.json()["display_lat"], second.json()["display_lng"]) == (
        display_owner
    )

    shared_first = http.get(f"/shared/{owner_id}", headers=other_headers)
    shared_second = http.get(f"/shared/{owner_id}", headers=other_headers)
    assert shared_first.status_code == 200
    assert shared_second.status_code == 200
    display_shared = (
        shared_first.json()["display_lat"],
        shared_first.json()["display_lng"],
    )
    assert (
        shared_second.json()["display_lat"],
        shared_second.json()["display_lng"],
    ) == display_shared
    assert display_shared == display_owner

    incidents_first = http.get("/api/incidents", headers=other_headers)
    incidents_second = http.get("/api/incidents", headers=other_headers)
    assert incidents_first.status_code == 200
    feature = _find_feature(incidents_first.json()["features"], owner_id)
    assert feature is not None
    assert _find_display(feature) == display_owner
    feature_again = _find_feature(
        incidents_second.json()["features"], owner_id
    )
    assert _find_display(feature_again) == display_owner

    # The display point is jittered: never the exact coordinates.
    assert tuple(display_owner) != (LAT, LNG)

    owner_list = http.get("/reports", headers=owner_headers)
    assert owner_list.status_code == 200
    photo = http.get(f"/api/photos/{owner_id}", headers=other_headers)
    assert photo.status_code == 200

    bodies = [
        first.json(),
        owner_list.json(),
        shared_first.json(),
        incidents_first.json(),
    ]
    for parsed in bodies:
        _assert_no_leaks(parsed, json.dumps(parsed), dirs)
    headers_text = json.dumps(dict(photo.headers))
    _assert_no_leaks({}, headers_text, dirs)


def test_photo_bytes_for_other_user(monkeypatch, tmp_path):
    http, dirs, owner_headers, other_headers, owner_upload, _ = (
        _setup_two_accounts(monkeypatch, tmp_path)
    )
    owner_id = owner_upload["report_id"]
    detail = http.get(f"/reports/{owner_id}", headers=owner_headers)
    assert detail.status_code == 200

    photo = http.get(f"/api/photos/{owner_id}", headers=other_headers)
    assert photo.status_code == 200, photo.text
    assert photo.headers["content-type"].startswith("image/")
    assert photo.content, "empty photo body"

    via_url = http.get(detail.json()["photo_url"], headers=other_headers)
    assert via_url.status_code == 200, via_url.text
    assert via_url.headers["content-type"].startswith("image/")
    assert via_url.content == photo.content

    anon_photo = http.get(f"/api/photos/{owner_id}")
    assert anon_photo.status_code == 401, anon_photo.text


def test_mock_rejected_upload_has_no_retrievable_report(
    monkeypatch, tmp_path
):
    http, dirs = _make_client(monkeypatch, tmp_path)
    owner_headers, _ = _verified_account(http, dirs, OWNER_EMAIL)
    other_headers, _ = _verified_account(http, dirs, OTHER_EMAIL)

    before = _report_list(http, owner_headers)
    fixture = (
        Path(__file__).resolve().parent / "fixtures" / "shapes_basic.png"
    )
    raw = fixture.read_bytes()
    assert (
        hashlib.sha256(raw).hexdigest()
        in upload_pipeline.load_mock_hashes()
    )
    resp = http.post(
        "/analyze",
        data={
            "client_report_id": "retrieval-mock-1",
            "location_lat": str(LAT),
            "location_lng": str(LNG),
            "location_consented": "true",
            "location_source": "browser",
        },
        files={"photo": ("shapes_basic.png", raw, "image/png")},
        headers=owner_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["detail"] == MOCK_REJECTION_DETAIL
    assert "report_id" not in resp.json()

    after = _report_list(http, owner_headers)
    assert _list_ids(after) == _list_ids(before)

    bogus = 999999
    for headers in (owner_headers, other_headers):
        assert (
            http.get(f"/reports/{bogus}", headers=headers).status_code
            == 404
        )
        assert (
            http.get(f"/shared/{bogus}", headers=headers).status_code
            == 404
        )
        assert (
            http.get(f"/api/photos/{bogus}", headers=headers).status_code
            == 404
        )


def test_only_accepted_reports_appear_in_shared_surfaces(
    monkeypatch, tmp_path
):
    http, dirs, owner_headers, other_headers, owner_upload, other_upload = (
        _setup_two_accounts(monkeypatch, tmp_path)
    )
    accepted_ids = {owner_upload["report_id"], other_upload["report_id"]}
    accepted_status = _db_status(dirs, owner_upload["report_id"])
    assert _db_status(dirs, other_upload["report_id"]) == accepted_status

    incidents = http.get("/api/incidents", headers=other_headers)
    assert incidents.status_code == 200, incidents.text
    features = incidents.json()["features"]
    assert features, "accepted reports missing from shared surfaces"
    assert accepted_ids <= {
        entry
        for feature in features
        for entry in _walk_floats(feature)
        if isinstance(entry, int)
    }

    # Every shared id maps to a report row carrying the accepted
    # status: rows in any other (non-accepted) state never surface.
    conn = connect(str(dirs["db"]))
    try:
        rows = conn.execute("SELECT id, status FROM reports").fetchall()
    finally:
        conn.close()
    non_accepted = {
        row["id"] for row in rows if row["status"] != accepted_status
    }
    surfaced = {
        entry
        for feature in features
        for entry in _walk_floats(feature)
        if isinstance(entry, int)
    }
    assert not (surfaced & non_accepted), (
        f"non-accepted rows surfaced: {surfaced & non_accepted}"
    )
    for report_id in accepted_ids:
        shared = http.get(f"/shared/{report_id}", headers=owner_headers)
        assert shared.status_code == 200, (report_id, shared.text)
