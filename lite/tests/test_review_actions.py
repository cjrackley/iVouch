"""Tests for Lite spec 4, objective 4.2: review actions API.

TestClient against tmp SQLite + tmp mail/uploads dirs only -- never
the real ``lite/data/`` directory -- with the stubbed CLIP encoder
via the ``create_app(clip_encoder=...)`` seam (fast).

Covers: reviewer-only gate (403 for non-reviewers), one
``review_actions`` row per call with before/after snapshots,
taxonomy validation for ``correct`` (422), ``check_results``
immutability, the ``effective_labels`` helper shape, and the
reviewer detail route ``GET /review/api/{id}``.
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

from lite.app.config import load_config
from lite.app.server import pipeline as upload_pipeline
from lite.app.server.api import create_app, effective_labels
from lite.app.server.db import connect, make_reviewer

TEST_SECRET = "test-jwt-secret-for-review-actions-tests-0123456789"
PASSWORD = "correct-horse-9"
ADULT_DOB = (date.today() - timedelta(days=365 * 30)).isoformat()
OWNER_EMAIL = "owner@example.com"
REVIEWER_EMAIL = "reviewer@example.com"
LAT = 51.5
LNG = -0.12


class FanStub:
    """Deterministic stub encoder (same shape as the e2e suite's)."""

    def image_embed(self, image):
        assert isinstance(image, Image.Image)
        return [1.0, 1.0]

    def text_embeds(self, texts):
        return [[1.0, 0.1 * (i + 1)] for i, _ in enumerate(texts)]


def _fresh_jpeg_bytes(seed=21, size=(64, 64)) -> bytes:
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


def _mail_token(mail_dir):
    paths = sorted(Path(mail_dir).glob("*.txt"))
    assert paths, "no verification mail written"
    match = re.search(
        r"^token:\s*(\S+)\s*$",
        paths[-1].read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert match, "mail file has no token line"
    return match.group(1)


def _register_verify_login(http, mail_dir, email):
    assert http.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "date_of_birth": ADULT_DOB,
        },
    ).status_code == 200
    assert http.post(
        "/auth/verify-email", json={"token": _mail_token(mail_dir)}
    ).status_code == 200
    login = http.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _upload_report(http, headers, seed, client_report_id):
    raw = _fresh_jpeg_bytes(seed=seed)
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
            "claim_text": "a photo of a street with geometric shapes",
        },
        files={"photo": ("photo.jpg", raw, "image/jpeg")},
        headers=headers,
    )
    assert upload.status_code == 200, upload.text
    return upload.json()["report_id"]


def _setup(monkeypatch, tmp_path):
    """Build the app, an owner with one report, and a reviewer login."""
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
    http = TestClient(app)
    owner_headers = _register_verify_login(http, dirs["mail"], OWNER_EMAIL)
    reviewer_headers = _register_verify_login(
        http, dirs["mail"], REVIEWER_EMAIL
    )
    conn = connect(str(dirs["db"]))
    try:
        make_reviewer(conn, REVIEWER_EMAIL)
    finally:
        conn.close()
    report_id = _upload_report(http, owner_headers, 21, "review-seed-1")
    return http, dirs, owner_headers, reviewer_headers, report_id


def _action_rows(db_path):
    conn = connect(str(db_path))
    try:
        return conn.execute(
            "SELECT * FROM review_actions ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def _check_snapshot(db_path, report_id):
    conn = connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT * FROM check_results WHERE report_id = ?",
            (report_id,),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def _tops(http, owner_headers, report_id):
    detail = http.get(f"/reports/{report_id}", headers=owner_headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    incident = body["incident_probs"]
    severity = body["severity_probs"]
    return max(incident, key=incident.get), max(severity, key=severity.get)


def test_non_reviewer_gets_403_and_writes_nothing(monkeypatch, tmp_path):
    http, dirs, owner_headers, _, report_id = _setup(monkeypatch, tmp_path)
    resp = http.post(
        f"/review/{report_id}/actions",
        json={"action": "confirm"},
        headers=owner_headers,
    )
    assert resp.status_code == 403, resp.text
    assert _action_rows(dirs["db"]) == []
    detail = http.get(f"/review/api/{report_id}", headers=owner_headers)
    assert detail.status_code == 403, detail.text


def test_anonymous_gets_401(monkeypatch, tmp_path):
    http, _, _, _, report_id = _setup(monkeypatch, tmp_path)
    assert (
        http.post(
            f"/review/{report_id}/actions", json={"action": "confirm"}
        ).status_code
        == 401
    )
    assert http.get(f"/review/api/{report_id}").status_code == 401


def test_missing_report_is_404(monkeypatch, tmp_path):
    http, dirs, _, reviewer_headers, _ = _setup(monkeypatch, tmp_path)
    assert (
        http.post(
            "/review/99999/actions",
            json={"action": "confirm"},
            headers=reviewer_headers,
        ).status_code
        == 404
    )
    assert (
        http.get("/review/api/99999", headers=reviewer_headers).status_code
        == 404
    )
    assert _action_rows(dirs["db"]) == []


def test_confirm_writes_exactly_one_row(monkeypatch, tmp_path):
    http, dirs, owner_headers, reviewer_headers, report_id = _setup(
        monkeypatch, tmp_path
    )
    incident_top, severity_top = _tops(http, owner_headers, report_id)
    resp = http.post(
        f"/review/{report_id}/actions",
        json={"action": "confirm"},
        headers=reviewer_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "ok": True,
        "action": "confirm",
        "report_id": report_id,
    }
    rows = _action_rows(dirs["db"])
    assert len(rows) == 1
    assert rows[0]["action"] == "confirm"
    assert json.loads(rows[0]["before"]) == {
        "incident_top": incident_top,
        "severity": severity_top,
    }
    assert json.loads(rows[0]["after"]) == json.loads(rows[0]["before"])
    assert rows[0]["created_at"]


def test_dismiss_ignores_extras(monkeypatch, tmp_path):
    http, dirs, _, reviewer_headers, report_id = _setup(
        monkeypatch, tmp_path
    )
    resp = http.post(
        f"/review/{report_id}/actions",
        json={
            "action": "dismiss",
            "incident": "fire",
            "severity": "severe",
            "note": "not our incident",
        },
        headers=reviewer_headers,
    )
    assert resp.status_code == 200, resp.text
    rows = _action_rows(dirs["db"])
    assert len(rows) == 1
    assert json.loads(rows[0]["after"]) == json.loads(rows[0]["before"])


def test_correct_validates_taxonomy(monkeypatch, tmp_path):
    http, dirs, _, reviewer_headers, report_id = _setup(
        monkeypatch, tmp_path
    )
    cfg = load_config()
    assert len(cfg.incident_prompts) == 6
    bad_bodies = [
        {"action": "correct"},
        {"action": "correct", "incident": "fire"},
        {"action": "correct", "severity": "severe"},
        {"action": "correct", "incident": "alien_invasion",
         "severity": "severe"},
        {"action": "correct", "incident": "fire", "severity": "extreme"},
        {"action": "correct", "incident": "fire", "severity": None},
        {"action": "archive"},
    ]
    for body in bad_bodies:
        resp = http.post(
            f"/review/{report_id}/actions",
            json=body,
            headers=reviewer_headers,
        )
        assert resp.status_code == 422, (body, resp.text)
    assert _action_rows(dirs["db"]) == []


def test_correct_then_effective_labels(monkeypatch, tmp_path):
    http, dirs, _, reviewer_headers, report_id = _setup(
        monkeypatch, tmp_path
    )
    conn = connect(str(dirs["db"]))
    try:
        fresh = effective_labels(conn, report_id)
    finally:
        conn.close()
    assert fresh["corrected"] is False
    assert fresh["correction"] is None
    assert set(fresh) == {
        "incident_top",
        "severity",
        "corrected",
        "correction",
    }

    resp = http.post(
        f"/review/{report_id}/actions",
        json={
            "action": "correct",
            "incident": "fire",
            "severity": "severe",
            "note": "reviewer override",
        },
        headers=reviewer_headers,
    )
    assert resp.status_code == 200, resp.text
    rows = _action_rows(dirs["db"])
    assert len(rows) == 1
    assert json.loads(rows[0]["after"]) == {
        "incident_top": "fire",
        "severity": "severe",
    }

    conn = connect(str(dirs["db"]))
    try:
        current = effective_labels(conn, report_id)
    finally:
        conn.close()
    assert current["incident_top"] == "fire"
    assert current["severity"] == "severe"
    assert current["corrected"] is True
    assert current["correction"]["incident_top"] == "fire"
    assert current["correction"]["severity"] == "severe"
    assert current["correction"]["reviewer"] == REVIEWER_EMAIL
    assert current["correction"]["time"]


def test_actions_never_change_check_results(monkeypatch, tmp_path):
    http, dirs, _, reviewer_headers, report_id = _setup(
        monkeypatch, tmp_path
    )
    before = _check_snapshot(dirs["db"], report_id)
    assert before is not None
    for body in (
        {"action": "confirm"},
        {"action": "correct", "incident": "flood",
         "severity": "minor"},
        {"action": "dismiss"},
    ):
        resp = http.post(
            f"/review/{report_id}/actions",
            json=body,
            headers=reviewer_headers,
        )
        assert resp.status_code == 200, resp.text
    assert _check_snapshot(dirs["db"], report_id) == before
    assert len(_action_rows(dirs["db"])) == 3


def test_reviewer_detail_shape_and_history(monkeypatch, tmp_path):
    http, dirs, _, reviewer_headers, report_id = _setup(
        monkeypatch, tmp_path
    )
    detail = http.get(f"/review/api/{report_id}", headers=reviewer_headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["correction"] is None
    assert body["history"] == []
    assert body["report_id"] == report_id
    # The uploader's email is never exposed to reviewers here.
    assert OWNER_EMAIL not in json.dumps(body)

    for action_body in (
        {"action": "confirm"},
        {"action": "correct", "incident": "flood", "severity": "minor"},
    ):
        assert (
            http.post(
                f"/review/{report_id}/actions",
                json=action_body,
                headers=reviewer_headers,
            ).status_code
            == 200
        )
    detail = http.get(f"/review/api/{report_id}", headers=reviewer_headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["correction"]["incident_top"] == "flood"
    assert body["correction"]["severity"] == "minor"
    assert body["correction"]["reviewer"] == REVIEWER_EMAIL
    assert [entry["action"] for entry in body["history"]] == [
        "confirm",
        "correct",
    ]
    for entry in body["history"]:
        assert set(entry) == {
            "reviewer",
            "action",
            "before",
            "after",
            "time",
        }
        assert entry["reviewer"] == REVIEWER_EMAIL
        assert set(entry["before"]) == {"incident_top", "severity"}
        assert set(entry["after"]) == {"incident_top", "severity"}
    # before of the second action already reflects the first action's
    # effective values (confirm keeps the original tops).
    assert body["history"][1]["before"] == body["history"][0]["after"]
