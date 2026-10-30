"""Tests for Lite spec 4, objective 4.1: reviewer role and queue pages.

TestClient against tmp SQLite + tmp mail/uploads dirs only -- never
the real ``lite/data/`` directory -- with the stubbed CLIP encoder
via the ``create_app(clip_encoder=...)`` seam (fast).

Covers: reviewer-only gates (403 for non-reviewers and anonymous
callers) on ``GET /review`` and ``GET /review/{id}``, queue order
(needs-review first, then newest) with verdict + confidence per row,
detail contents (incident/severity probabilities, provenance flags,
duplicate links, claim text, fusion reasons, original demo verdict),
no uploader email on reviewer pages, action forms with CSRF posting
to ``POST /review/{id}/actions``, the JSON actions contract still
served through that path, and the "corrected by reviewer" banner on
the owner's result page (new values plus the unchanged original
verdict).

Reviewer seeding uses the committed ``make_reviewer`` db helper --
the same function the ``make-reviewer`` CLI calls -- without
modifying ``db.py``.
"""

from __future__ import annotations

import hashlib
import io
import random
import re
from datetime import date, timedelta

from PIL import Image

from lite.app.config import load_config
from lite.app.server import pipeline as upload_pipeline
from lite.app.server.api import create_app
from lite.app.server.db import connect, make_reviewer

TEST_SECRET = "test-jwt-secret-for-review-pages-tests-0123456789"
PASSWORD = "correct-horse-9"
ADULT_DOB = (date.today() - timedelta(days=365 * 30)).isoformat()
OWNER_EMAIL = "review-page-owner@example.com"
REVIEWER_EMAIL = "review-page-reviewer@example.com"
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
    """Register + verify + Bearer login via the JSON API."""
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


def _upload_report(http, headers, raw, client_report_id, claim=CLAIM):
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
            "claim_text": claim,
        },
        files={"photo": ("photo.png", raw, "image/png")},
        headers=headers,
    )
    assert upload.status_code == 200, upload.text
    return upload.json()["report_id"]


def _setup(monkeypatch, tmp_path, seeds=(21,)):
    """Build the app, an owner with reports, and a cookie reviewer."""
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
    owner = TestClient(app)
    reviewer = TestClient(app)
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
    report_ids = [
        _upload_report(owner, owner_headers, _fresh_png_bytes(seed=seed),
                       f"review-page-{seed}")
        for seed in seeds
    ]
    return (app, owner, reviewer, dirs, owner_headers, reviewer_headers,
            report_ids)


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "page has no CSRF token field"
    return match.group(1)


def _action_rows(db_path):
    conn = connect(str(db_path))
    try:
        return conn.execute(
            "SELECT * FROM review_actions ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def _set_verdict(db_path, report_id, verdict):
    """Test setup only: force a stored verdict to shape queue order."""
    conn = connect(str(db_path))
    try:
        conn.execute(
            "UPDATE check_results SET verdict = ? WHERE report_id = ?",
            (verdict, report_id),
        )
        conn.commit()
    finally:
        conn.close()


def test_queue_and_detail_forbidden_for_non_reviewer(
    monkeypatch, tmp_path
):
    from fastapi.testclient import TestClient

    app, owner, _, _, _, _, report_ids = _setup(monkeypatch, tmp_path)
    report_id = report_ids[0]
    queue = owner.get("/review", headers=HTML)
    assert queue.status_code == 403, queue.text
    assert "Reviewer access required" in queue.text
    detail = owner.get(f"/review/{report_id}", headers=HTML)
    assert detail.status_code == 403, detail.text
    assert "Reviewer access required" in detail.text
    # A fresh client holds no session cookie: still 403, never login.
    anon = TestClient(app)
    assert anon.get("/review", headers=HTML).status_code == 403
    assert anon.get(
        f"/review/{report_id}", headers=HTML
    ).status_code == 403


def test_queue_order_needs_review_first_then_newest(
    monkeypatch, tmp_path
):
    _, _, reviewer, dirs, owner_headers, _, report_ids = _setup(
        monkeypatch, tmp_path, seeds=(31, 32, 33)
    )
    first, second, third = report_ids
    assert first < second < third
    # Force the middle report to the no-review label; the queue must
    # still lead with needs-review rows, newest first.
    _set_verdict(dirs["db"], second, "likely-real")

    queue = reviewer.get("/review", headers=HTML)
    assert queue.status_code == 200, queue.text
    body = queue.text
    for report_id in report_ids:
        assert f"/review/{report_id}" in body
    assert body.index(f"/review/{third}") < body.index(
        f"/review/{first}"
    ) < body.index(f"/review/{second}")

    # Every row carries its stored verdict and confidence, and the
    # uploader's email appears nowhere on the page.
    expected = reviewer.get(
        f"/reports/{third}", headers=owner_headers
    ).json()
    assert f"/review/{third}" in body
    assert expected["verdict"] in body
    assert str(expected["confidence"]) in body
    assert OWNER_EMAIL not in body
    assert REVIEWER_EMAIL not in body


def test_detail_contents_and_no_uploader_email(
    monkeypatch, tmp_path
):
    _, owner, reviewer, _, owner_headers, _, report_ids = _setup(
        monkeypatch, tmp_path, seeds=(41,)
    )
    report_id = report_ids[0]
    # A second report with identical bytes is an exact duplicate.
    twin = _upload_report(
        owner, owner_headers, _fresh_png_bytes(seed=41),
        "review-page-41-twin",
    )
    assert twin != report_id

    expected = owner.get(
        f"/reports/{report_id}", headers=owner_headers
    ).json()
    assert expected["reasons"], "stub verdict carries no reasons"

    detail = reviewer.get(f"/review/{report_id}", headers=HTML)
    assert detail.status_code == 200, detail.text
    body = detail.text
    top_incident = max(
        expected["incident_probs"], key=expected["incident_probs"].get
    )
    assert top_incident in body
    assert str(expected["incident_probs"][top_incident]) in body
    assert expected["top_severity"] in body
    assert str(expected["severity_probs"][
        expected["top_severity"]]) in body
    for flag in ("exif_present", "time_plausible", "gps_present"):
        assert flag in body, f"provenance flag missing: {flag}"
    assert f"/review/{twin}" in body
    assert CLAIM in body
    for reason in expected["reasons"]:
        assert reason in body, f"fusion reason missing: {reason}"
    assert expected["verdict"] in body
    assert OWNER_EMAIL not in body


def test_detail_missing_report_is_404(monkeypatch, tmp_path):
    _, _, reviewer, _, _, _, _ = _setup(monkeypatch, tmp_path)
    missing = reviewer.get("/review/999999", headers=HTML)
    assert missing.status_code == 404, missing.text
    assert "Not found" in missing.text


def test_detail_forms_and_taxonomy_selects(monkeypatch, tmp_path):
    _, _, reviewer, _, _, _, report_ids = _setup(
        monkeypatch, tmp_path
    )
    detail = reviewer.get(f"/review/{report_ids[0]}", headers=HTML)
    assert detail.status_code == 200, detail.text
    body = detail.text
    assert 'name="csrf_token"' in body
    for action in ("confirm", "correct", "dismiss"):
        assert f'action="/review/{report_ids[0]}/actions"' in body, action
        assert f'value="{action}"' in body, action
    cfg = load_config()
    assert len(cfg.incident_prompts) == 6
    for label in cfg.incident_prompts:
        assert f'value="{label}"' in body, label
    for severity in ("minor", "moderate", "severe"):
        assert f'value="{severity}"' in body, severity


def _post_form(client, report_id, fields):
    detail = client.get(f"/review/{report_id}", headers=HTML)
    assert detail.status_code == 200, detail.text
    return client.post(
        f"/review/{report_id}/actions",
        data={"csrf_token": _csrf(detail.text), **fields},
        follow_redirects=False,
    )


def test_confirm_via_form_writes_one_row(monkeypatch, tmp_path):
    _, _, reviewer, dirs, _, _, report_ids = _setup(
        monkeypatch, tmp_path
    )
    report_id = report_ids[0]
    resp = _post_form(reviewer, report_id, {"action": "confirm"})
    assert resp.status_code == 303, resp.text
    assert resp.headers["location"] == f"/review/{report_id}"
    rows = _action_rows(dirs["db"])
    assert len(rows) == 1
    assert rows[0]["action"] == "confirm"
    followed = reviewer.get(
        resp.headers["location"], headers=HTML
    )
    assert followed.status_code == 200, followed.text
    assert "confirm" in followed.text


def test_dismiss_via_form_keeps_values(monkeypatch, tmp_path):
    _, _, reviewer, dirs, _, _, report_ids = _setup(
        monkeypatch, tmp_path
    )
    report_id = report_ids[0]
    resp = _post_form(
        reviewer, report_id,
        {"action": "dismiss", "note": "not our incident"},
    )
    assert resp.status_code == 303, resp.text
    rows = _action_rows(dirs["db"])
    assert len(rows) == 1
    assert rows[0]["action"] == "dismiss"


def test_correct_via_form_then_owner_banner(monkeypatch, tmp_path):
    _, owner, reviewer, dirs, owner_headers, _, report_ids = _setup(
        monkeypatch, tmp_path
    )
    report_id = report_ids[0]
    original = owner.get(
        f"/reports/{report_id}", headers=owner_headers
    ).json()["verdict"]
    resp = _post_form(
        reviewer, report_id,
        {"action": "correct", "incident": "fire",
         "severity": "severe"},
    )
    assert resp.status_code == 303, resp.text
    rows = _action_rows(dirs["db"])
    assert len(rows) == 1

    detail = reviewer.get(f"/review/{report_id}", headers=HTML)
    assert detail.status_code == 200, detail.text
    assert "Corrected by reviewer" in detail.text
    assert "fire" in detail.text
    assert "severe" in detail.text
    assert original in detail.text

    card = owner.get(f"/reports/{report_id}", headers=HTML)
    assert card.status_code == 200, card.text
    assert "Corrected by reviewer" in card.text
    assert "fire" in card.text
    assert "severe" in card.text
    assert original in card.text


def test_bad_correct_via_form_is_422_and_writes_nothing(
    monkeypatch, tmp_path
):
    _, _, reviewer, dirs, _, _, report_ids = _setup(
        monkeypatch, tmp_path
    )
    report_id = report_ids[0]
    resp = _post_form(
        reviewer, report_id,
        {"action": "correct", "incident": "alien_invasion",
         "severity": "severe"},
    )
    assert resp.status_code == 422, resp.text
    assert _action_rows(dirs["db"]) == []


def test_form_without_csrf_is_rejected(monkeypatch, tmp_path):
    _, _, reviewer, dirs, _, _, report_ids = _setup(
        monkeypatch, tmp_path
    )
    resp = reviewer.post(
        f"/review/{report_ids[0]}/actions",
        data={"action": "confirm", "csrf_token": "wrong"},
        follow_redirects=False,
    )
    assert resp.status_code == 403, resp.text
    assert _action_rows(dirs["db"]) == []


def test_json_actions_contract_preserved(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    app, owner, _, _, owner_headers, reviewer_headers, report_ids = (
        _setup(monkeypatch, tmp_path)
    )
    report_id = report_ids[0]
    # The pages router shadows the JSON route, so it delegates JSON
    # bodies to the same implementation with the same contract.
    denied = owner.post(
        f"/review/{report_id}/actions", json={"action": "confirm"},
        headers=owner_headers,
    )
    assert denied.status_code == 403, denied.text
    anon = TestClient(app)
    assert anon.post(
        f"/review/{report_id}/actions", json={"action": "confirm"}
    ).status_code == 401
    ok = anon.post(
        f"/review/{report_id}/actions", json={"action": "confirm"},
        headers=reviewer_headers,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json() == {
        "ok": True,
        "action": "confirm",
        "report_id": report_id,
    }

