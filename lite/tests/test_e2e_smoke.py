"""End-to-end smoke test (Lite spec 2, objective 2.5, Part A).

Full journey on TestClient with tmp SQLite + tmp mail/uploads dirs
only -- never the real ``lite/data/`` directory -- and the stubbed
CLIP encoder via the ``create_app(clip_encoder=...)`` seam (fast;
the live-model run is Part B, recorded in the log entry only).

Journey: register -> verify (console mail file) -> upload a novel
noise JPEG (NOT a committed fixture -- all fixtures are mock-listed)
with required location + consent -> read the report back via
``GET /reports/{id}`` and assert incident probs / severity / verdict /
reasons / confidence / needs_review are present and consistent with
the stub (spec-1 values pass through unchanged).
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
from lite.app.checks import provenance as provenance_mod
from lite.app.checks.fusion import AllChecks, fuse
from lite.app.config import load_config
from lite.app.server import pipeline as upload_pipeline
from lite.app.server.api import create_app

TEST_SECRET = "test-jwt-secret-for-e2e-smoke-tests-0123456789"
PASSWORD = "correct-horse-9"
ADULT_DOB = (date.today() - timedelta(days=365 * 30)).isoformat()
EMAIL = "e2e@example.com"
CLAIM_TEXT = "a photo of a street with geometric shapes"
LAT = 51.5
LNG = -0.12


class FanStub:
    """Deterministic stub encoder (same shape as the 2.3 suite's)."""

    def image_embed(self, image):
        assert isinstance(image, Image.Image)
        return [1.0, 1.0]

    def text_embeds(self, texts):
        return [[1.0, 0.1 * (i + 1)] for i, _ in enumerate(texts)]


def _fresh_jpeg_bytes(seed=7, size=(64, 64)) -> bytes:
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


def test_e2e_smoke_register_verify_upload_readback(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("LITE_JWT_SECRET", TEST_SECRET)
    dirs = {
        "db": tmp_path / "test.db",
        "mail": tmp_path / "mail",
        "uploads": tmp_path / "uploads",
    }
    from fastapi.testclient import TestClient

    stub = FanStub()
    app = create_app(
        db_path=dirs["db"],
        mail_dir=dirs["mail"],
        uploads_dir=dirs["uploads"],
        clip_encoder=stub,
    )
    http = TestClient(app)

    # 1. Register.
    resp = http.post(
        "/auth/register",
        json={
            "email": EMAIL,
            "password": PASSWORD,
            "date_of_birth": ADULT_DOB,
        },
    )
    assert resp.status_code == 200, resp.text

    # 2. Verify via the console mail file (token line).
    paths = sorted(Path(dirs["mail"]).glob("*.txt"))
    assert paths, "no verification mail written"
    tokens = []
    for path in paths:
        match = re.search(
            r"^token:\s*(\S+)\s*$",
            path.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        assert match, f"mail file {path.name} has no token line"
        tokens.append(match.group(1))
    verify = http.post("/auth/verify-email", json={"token": tokens[-1]})
    assert verify.status_code == 200, verify.text

    # 3. Log in.
    login = http.post(
        "/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
    )
    assert login.status_code == 200, login.text
    assert login.json()["email_verified"] is True
    headers = {
        "Authorization": f"Bearer {login.json()['access_token']}"
    }

    # 4. Upload a novel noise JPEG with location + consent.
    raw = _fresh_jpeg_bytes()
    assert (
        hashlib.sha256(raw).hexdigest()
        not in upload_pipeline.load_mock_hashes()
    )
    upload = http.post(
        "/analyze",
        data={
            "client_report_id": "e2e-smoke-1",
            "location_lat": str(LAT),
            "location_lng": str(LNG),
            "location_consented": "true",
            "location_source": "browser",
            "claim_text": CLAIM_TEXT,
        },
        files={"photo": ("photo.jpg", raw, "image/jpeg")},
        headers=headers,
    )
    assert upload.status_code == 200, upload.text
    body = upload.json()
    for key in (
        "report_id",
        "incident_probs",
        "severity_probs",
        "verdict",
        "reasons",
        "confidence",
        "needs_review",
    ):
        assert key in body, f"upload response missing {key}: {body!r}"[
            :500
        ]
    report_id = body["report_id"]

    # 5. Expected spec-1 values from direct stub calls.
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

    # Upload body is consistent with the stub.
    assert body["incident_probs"] == expected_incident
    assert body["severity_probs"] == expected_severity
    assert body["verdict"] == expected_verdict.label
    assert body["reasons"] == list(expected_verdict.reasons)
    assert body["confidence"] == expected_verdict.confidence
    assert body["confidence"] == max(expected_incident.values())
    assert body["needs_review"] == expected_verdict.needs_review

    # 6. Read the report back via GET /reports/{id}.
    detail = http.get(f"/reports/{report_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    readback = detail.json()
    for key in (
        "incident_probs",
        "severity_probs",
        "verdict",
        "reasons",
        "confidence",
        "needs_review",
    ):
        assert key in readback, (
            f"GET /reports/{{id}} missing {key}: {readback!r}"
        )[:500]
    # Read-back matches the finished upload output unchanged.
    for key in (
        "incident_probs",
        "severity_probs",
        "top_severity",
        "verdict",
        "reasons",
        "confidence",
        "needs_review",
    ):
        assert readback[key] == body[key], key
    assert readback["report_id"] == report_id
    assert readback["claim_text"] == CLAIM_TEXT
