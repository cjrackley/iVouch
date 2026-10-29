"""Tests for Lite spec 2, objective 2.3: upload and processing pipeline.

TestClient against tmp SQLite + tmp mail/uploads dirs only -- never
the real ``lite/data/`` directory. The CLIP encoder is always stubbed
through the pipeline encoder seam (``create_app(clip_encoder=...)``);
the live model path is covered by objective 2.5, never here.

Endpoint under test: ``POST /analyze`` (multipart: photo + optional
claim text + ``client_report_id`` + required ``location_lat``,
``location_lng``, ``location_consented``, ``location_source``).

NOTE: every committed fixture image is on the mock hash list, so
completed-upload tests generate fresh in-memory images (never fixtures)
to exercise the accept path.
"""

from __future__ import annotations

import hashlib
import io
import random
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

from lite.app.checks import clip_checks
from lite.app.checks import duplicates as duplicates_mod
from lite.app.checks import files as files_mod
from lite.app.checks import provenance as provenance_mod
from lite.app.checks.fusion import AllChecks, fuse
from lite.app.config import load_config
from lite.app.server import pipeline as upload_pipeline
from lite.app.server.api import create_app
from lite.app.server.db import connect

TEST_SECRET = "test-jwt-secret-for-upload-tests-0123456789"
PASSWORD = "correct-horse-9"
ADULT_DOB = (date.today() - timedelta(days=365 * 30)).isoformat()

MOCK_REJECTION_DETAIL = "upload could not be accepted"
EXPECTED_REPORT_KEYS = {
    "report_id",
    "incident_probs",
    "severity_probs",
    "top_severity",
    "verdict",
    "reasons",
    "confidence",
    "needs_review",
}
CLAIM_TEXT = "a photo of a street with geometric shapes"


class FanStub:
    """Deterministic stub encoder: text vectors fan out by position so
    the resulting distribution is non-uniform but valid."""

    def image_embed(self, image):
        assert isinstance(image, Image.Image)
        return [1.0, 1.0]

    def text_embeds(self, texts):
        return [[1.0, 0.1 * (i + 1)] for i, _ in enumerate(texts)]


def _fresh_image_bytes(fmt="PNG", seed=0, size=(64, 64)) -> bytes:
    """Generate fresh random-noise image bytes (never mock-listed)."""
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
    img.save(buf, format=fmt)
    return buf.getvalue()


def _mail_token(mail_dir) -> str:
    paths = sorted(Path(mail_dir).glob("*.txt"))
    assert len(paths) == 1, f"expected one mail file, got {paths}"
    match = re.search(
        r"^token:\s*(\S+)\s*$",
        paths[0].read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert match, "mail file has no token line"
    return match.group(1)


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
    paths = sorted(Path(dirs["mail"]).glob("*.txt"))
    tokens = []
    for path in paths:
        match = re.search(
            r"^token:\s*(\S+)\s*$",
            path.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        assert match, f"mail file {path.name} has no token line"
        tokens.append((path.name, match.group(1)))
    assert tokens, "no verification mail found"
    token = tokens[-1][1]
    verify = http.post("/auth/verify-email", json={"token": token})
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


def _valid_data(client_report_id, **overrides):
    data = {
        "client_report_id": client_report_id,
        "location_lat": "51.5",
        "location_lng": "-0.12",
        "location_consented": "true",
        "location_source": "browser",
    }
    data.update(overrides)
    return data


def _report_count(db_path) -> int:
    conn = connect(str(db_path))
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM reports"
        ).fetchone()["n"]
    finally:
        conn.close()


def _audit_rows(db_path):
    conn = connect(str(db_path))
    try:
        return conn.execute("SELECT * FROM audit_events").fetchall()
    finally:
        conn.close()


def _stored_files(uploads_dir) -> list:
    root = Path(uploads_dir)
    if not root.is_dir():
        return []
    return [p for p in root.rglob("*") if p.is_file()]


def test_jpeg_and_png_accepted(monkeypatch, tmp_path):
    http, dirs = _make_client(monkeypatch, tmp_path)
    headers, _ = _verified_account(http, dirs, "up@example.com")
    for fmt, name, seed in (
        ("PNG", "photo.png", 11),
        ("JPEG", "photo.jpg", 12),
    ):
        raw = _fresh_image_bytes(fmt, seed=seed)
        assert hashlib.sha256(raw).hexdigest() not in (
            upload_pipeline.load_mock_hashes()
        )
        resp = http.post(
            "/analyze",
            data=_valid_data(f"client-{fmt}"),
            files={"photo": (name, raw, "image/octet-stream")},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert set(resp.json()) == EXPECTED_REPORT_KEYS


def test_unsupported_types_rejected_415(monkeypatch, tmp_path):
    http, dirs = _make_client(monkeypatch, tmp_path)
    headers, _ = _verified_account(http, dirs, "up@example.com")
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (9, 9, 9)).save(buf, format="GIF")
    cases = [
        ("note.txt", b"this is not an image at all", "text/plain"),
        ("photo.gif", buf.getvalue(), "image/gif"),
    ]
    for idx, (filename, raw, ctype) in enumerate(cases):
        resp = http.post(
            "/analyze",
            data=_valid_data(f"client-415-{idx}"),
            files={"photo": (filename, raw, ctype)},
            headers=headers,
        )
        assert resp.status_code == 415, resp.text
    assert _report_count(dirs["db"]) == 0
    assert _stored_files(dirs["uploads"]) == []


def test_oversize_rejected_413(monkeypatch, tmp_path):
    http, dirs = _make_client(monkeypatch, tmp_path)
    headers, _ = _verified_account(http, dirs, "up@example.com")
    max_bytes = load_config().max_upload_bytes
    raw = b"\x00" * (max_bytes + 1)
    resp = http.post(
        "/analyze",
        data=_valid_data("client-oversize"),
        files={"photo": ("big.png", raw, "image/png")},
        headers=headers,
    )
    assert resp.status_code == 413, resp.status_code
    assert _report_count(dirs["db"]) == 0
    assert _stored_files(dirs["uploads"]) == []


def test_missing_location_or_consent_422_stores_nothing(
    monkeypatch, tmp_path
):
    http, dirs = _make_client(monkeypatch, tmp_path)
    headers, _ = _verified_account(http, dirs, "up@example.com")
    raw = _fresh_image_bytes("PNG", seed=21)
    variants = [
        ("no-lat-lng", {"location_lat": None, "location_lng": None}),
        ("no-consent-flag", {"location_consented": None}),
        ("consent-false", {"location_consented": "false"}),
    ]
    for client_id, removals in variants:
        data = _valid_data(client_id)
        for key, value in removals.items():
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
        before_reports = _report_count(dirs["db"])
        before_audits = len(_audit_rows(dirs["db"]))
        before_files = _stored_files(dirs["uploads"])
        resp = http.post(
            "/analyze",
            data=data,
            files={"photo": ("photo.png", raw, "image/png")},
            headers=headers,
        )
        assert resp.status_code == 422, (client_id, resp.text)
        assert _report_count(dirs["db"]) == before_reports
        assert len(_audit_rows(dirs["db"])) == before_audits
        assert _stored_files(dirs["uploads"]) == before_files


def test_unverified_account_cannot_upload_403(monkeypatch, tmp_path):
    http, dirs = _make_client(monkeypatch, tmp_path)
    resp = http.post(
        "/auth/register",
        json={
            "email": "fresh@example.com",
            "password": PASSWORD,
            "date_of_birth": ADULT_DOB,
        },
    )
    assert resp.status_code == 200
    login = http.post(
        "/auth/login",
        json={"email": "fresh@example.com", "password": PASSWORD},
    )
    assert login.status_code == 200
    assert login.json()["email_verified"] is False
    headers = {
        "Authorization": f"Bearer {login.json()['access_token']}"
    }
    raw = _fresh_image_bytes("PNG", seed=31)
    resp = http.post(
        "/analyze",
        data=_valid_data("client-unverified"),
        files={"photo": ("photo.png", raw, "image/png")},
        headers=headers,
    )
    assert resp.status_code == 403, resp.text
    assert _report_count(dirs["db"]) == 0
    assert _stored_files(dirs["uploads"]) == []


def test_mock_hash_match_generic_rejection_only(monkeypatch, tmp_path):
    http, dirs = _make_client(monkeypatch, tmp_path)
    headers, account_id = _verified_account(
        http, dirs, "up@example.com"
    )
    fixture = (
        Path(__file__).resolve().parent / "fixtures" / "shapes_basic.png"
    )
    raw = fixture.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    assert digest in upload_pipeline.load_mock_hashes()
    claim = "this claim text must never be stored on rejection"
    resp = http.post(
        "/analyze",
        data=_valid_data("client-mock", claim_text=claim),
        files={"photo": ("shapes_basic.png", raw, "image/png")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Assert the generic detail only; a demo notice key may be present.
    assert body["detail"] == MOCK_REJECTION_DETAIL
    assert "report_id" not in body
    # Nothing stored: no file on disk, no report row.
    assert _stored_files(dirs["uploads"]) == []
    assert _report_count(dirs["db"]) == 0
    # Exactly one mock_rejection audit event: hash + time + account,
    # never image bytes or claim text.
    audits = _audit_rows(dirs["db"])
    assert len(audits) == 1
    event = audits[0]
    assert event["kind"] == "mock_rejection"
    assert event["report_id"] is None
    assert event["actor_account_id"] == account_id
    assert digest in (event["detail"] or "")
    assert str(account_id) in (event["detail"] or "")
    assert event["created_at"]
    assert claim not in (event["detail"] or "")
    assert len(event["detail"] or "") < 500


def test_pipeline_order_mock_gate_before_clip(monkeypatch, tmp_path):
    http, dirs = _make_client(monkeypatch, tmp_path)
    headers, _ = _verified_account(http, dirs, "up@example.com")
    calls: list = []
    orig_mock = files_mod.mock_hash_match
    orig_incident = clip_checks.incident_probs
    orig_severity = clip_checks.severity_probs
    orig_claim = clip_checks.claim_similarity

    def mock_spy(raw, hashes):
        calls.append("mock_hash_match")
        return orig_mock(raw, hashes)

    def incident_spy(img, encoder=None):
        calls.append("clip:incident_probs")
        return orig_incident(img, encoder=encoder)

    def severity_spy(img, encoder=None):
        calls.append("clip:severity_probs")
        return orig_severity(img, encoder=encoder)

    def claim_spy(img, claim, encoder=None):
        calls.append("clip:claim_similarity")
        return orig_claim(img, claim, encoder=encoder)

    monkeypatch.setattr(files_mod, "mock_hash_match", mock_spy)
    monkeypatch.setattr(clip_checks, "incident_probs", incident_spy)
    monkeypatch.setattr(clip_checks, "severity_probs", severity_spy)
    monkeypatch.setattr(clip_checks, "claim_similarity", claim_spy)
    raw = _fresh_image_bytes("PNG", seed=41)
    resp = http.post(
        "/analyze",
        data=_valid_data("client-order", claim_text=CLAIM_TEXT),
        files={"photo": ("photo.png", raw, "image/png")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert "mock_hash_match" in calls
    clip_calls = [c for c in calls if c.startswith("clip:")]
    assert clip_calls, "expected CLIP checks to run"
    assert calls.index("mock_hash_match") < min(
        calls.index(c) for c in clip_calls
    )


def test_completed_upload_matches_spec1_passthrough(
    monkeypatch, tmp_path
):
    stub = FanStub()
    http, dirs = _make_client(monkeypatch, tmp_path, encoder=stub)
    headers, _ = _verified_account(http, dirs, "up@example.com")
    raw = _fresh_image_bytes("PNG", seed=51)
    resp = http.post(
        "/analyze",
        data=_valid_data("client-complete", claim_text=CLAIM_TEXT),
        files={"photo": ("photo.png", raw, "image/png")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == EXPECTED_REPORT_KEYS
    # Spec-1 values pass through unchanged: compare against direct
    # clip_checks / fuse calls with the same stub encoder.
    expected_incident = clip_checks.incident_probs(raw, encoder=stub)
    expected_severity = clip_checks.severity_probs(raw, encoder=stub)
    expected_claim = clip_checks.claim_similarity(
        raw, CLAIM_TEXT, encoder=stub
    )
    expected_provenance = provenance_mod.provenance_signals(
        raw, datetime.now(timezone.utc)
    )
    cfg = load_config()
    expected_verdict = fuse(
        AllChecks(
            file_ok=True,
            file_reason=None,
            mock_match=False,
            provenance=expected_provenance,
            duplicate_ids=[],
            claimed_time=None,
            prior_time=None,
            incident=dict(expected_incident),
            severity=dict(expected_severity),
            claim_sim=expected_claim,
        ),
        cfg,
    )
    assert body["incident_probs"] == expected_incident
    assert body["severity_probs"] == expected_severity
    assert body["top_severity"] == max(
        expected_severity, key=expected_severity.get
    )
    assert body["verdict"] == expected_verdict.label
    assert body["reasons"] == list(expected_verdict.reasons)
    assert body["confidence"] == expected_verdict.confidence
    assert body["confidence"] == max(expected_incident.values())
    assert body["needs_review"] == expected_verdict.needs_review


def test_idempotent_client_report_id_replay(monkeypatch, tmp_path):
    http, dirs = _make_client(monkeypatch, tmp_path)
    headers, _ = _verified_account(http, dirs, "up@example.com")
    first_raw = _fresh_image_bytes("PNG", seed=61)
    second_raw = _fresh_image_bytes("PNG", seed=62)
    assert first_raw != second_raw
    first = http.post(
        "/analyze",
        data=_valid_data("client-dedupe"),
        files={"photo": ("first.png", first_raw, "image/png")},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    reports_after_first = _report_count(dirs["db"])
    files_after_first = _stored_files(dirs["uploads"])
    assert reports_after_first == 1
    assert len(files_after_first) == 1
    # Repeat with the same client_report_id but different bytes:
    # same report_id, no new rows or files.
    second = http.post(
        "/analyze",
        data=_valid_data("client-dedupe"),
        files={"photo": ("second.png", second_raw, "image/png")},
        headers=headers,
    )
    assert second.status_code == 200, second.text
    assert second.json()["report_id"] == first.json()["report_id"]
    assert second.json() == first.json()
    assert _report_count(dirs["db"]) == reports_after_first
    assert _stored_files(dirs["uploads"]) == files_after_first
    # The duplicates module agrees the second bytes differ from store.
    conn = connect(str(dirs["db"]))
    try:
        store = upload_pipeline.prior_report_rows(conn)
    finally:
        conn.close()
    assert duplicates_mod.exact_match(
        hashlib.sha256(second_raw).hexdigest(), store
    ) is None
