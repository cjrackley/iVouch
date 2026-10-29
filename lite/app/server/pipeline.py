"""Upload and processing pipeline for Lite spec 2, objective 2.3.

Synchronous by design: every upload is processed inline in the request
handler and the response is the finished report. This is a deliberate
Lite simplification for small images and one user at a time -- there is
no job queue, no worker process, and no pending-state polling.

Pipeline order (spec 1, wired here exactly in this order): file sanity
(``lite/app/checks/files.py``), mock hash gate (same module),
provenance-lite, duplicates (rows adapted to
``[(report_id, sha256, phash)]``), CLIP incident/severity
(``lite/app/checks/clip_checks.py``), claim similarity, fusion
(``lite/app/checks/fusion.py``).

Check modules are called as module attributes (not ``from``-imported
names) so instrumented tests can patch them in place. Every CLIP entry
point accepts the optional ``encoder`` hook (default live, mirroring
the ``encoder=`` style of ``clip_checks``) so tests run stubbed and
fast; live-path coverage is left to objective 2.5.
"""

from __future__ import annotations

import hashlib
import imagehash
import json
from dataclasses import asdict
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image

from lite.app.checks import clip_checks
from lite.app.checks import duplicates
from lite.app.checks import files as file_checks
from lite.app.checks import fusion
from lite.app.checks import provenance as provenance_checks
from lite.app.checks.fusion import AllChecks
from lite.app.config import load_config
from lite.app.server.db import create_report, find_report

MOCK_REJECTION_DETAIL = "upload could not be accepted"
MOCK_DEMO_NOTICE = (
    "Demo screening only: this upload matched the mock fixture list "
    "(benign synthetic fixtures, not real safety screening)."
)
OVERSIZE_DETAIL = "upload_too_large"
UNSUPPORTED_DETAIL = "unsupported_file"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def load_mock_hashes() -> set[str]:
    """Load the mock-gate hash set from ``policy_mock_hashes_path``.

    Relative paths resolve against the repository root (same rule as
    the spec-1 tests). A missing file yields an empty set rather than
    an error -- the gate then simply never matches.
    """
    cfg = load_config()
    path = Path(cfg.policy_mock_hashes_path)
    if not path.is_absolute():
        path = _repo_root() / path
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return set()
    return {
        line.strip() for line in text.splitlines() if line.strip()
    }


def sha256_hex(raw: bytes) -> str:
    """SHA-256 hex digest of raw upload bytes."""
    return hashlib.sha256(raw).hexdigest()


def phash_hex(raw: bytes) -> str:
    """Perceptual-hash hex string of raw upload bytes (RGB)."""
    with Image.open(BytesIO(raw)) as img:
        img.load()
        return str(imagehash.phash(img.convert("RGB")))


def prior_report_rows(conn) -> list[tuple]:
    """Adapt stored reports to the duplicates-store shape.

    Returns ``[(report_id, sha256, phash), ...]`` in id order for every
    prior report row, as required by ``lite/app/checks/duplicates.py``.
    """
    rows = conn.execute(
        "SELECT id, sha256, phash FROM reports ORDER BY id"
    ).fetchall()
    return [(row["id"], row["sha256"], row["phash"]) for row in rows]


def upload_extension(raw: bytes) -> str:
    """File extension for stored bytes from the decoded image format."""
    with Image.open(BytesIO(raw)) as img:
        fmt = (img.format or "").strip().lower()
    if fmt == "jpg":
        fmt = "jpeg"
    return {"jpeg": "jpg", "png": "png"}.get(fmt, "bin")


def write_upload_file(
    uploads_dir, account_id: int, report_id: int, raw: bytes
) -> Path:
    """Store bytes at ``<uploads_dir>/<account_id>/<report_id>.<ext>``."""
    dest = (
        Path(uploads_dir) / str(account_id) / f"{report_id}.{upload_extension(raw)}"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return dest


def record_mock_rejection(conn, account_id: int, digest: str) -> None:
    """Write one ``mock_rejection`` audit event (hash + time + account).

    Never stores image bytes or claim text.
    """
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO audit_events (kind, actor_account_id, report_id,"
        " detail, created_at) VALUES (?, ?, ?, ?, ?)",
        (
            "mock_rejection",
            account_id,
            None,
            f"mock_rejection sha256={digest} account_id={account_id}"
            f" at {now}",
            now,
        ),
    )
    conn.commit()


def _normalise_claim(claim_text: str | None) -> str | None:
    if claim_text is None:
        return None
    stripped = claim_text.strip()
    return stripped or None


def analyze_bytes(
    raw: bytes,
    claim_text: str | None,
    store,
    encoder=None,
) -> dict:
    """Run the spec-1 check pipeline over raw bytes, in fixed order.

    ``store`` is the duplicates-store sequence from
    :func:`prior_report_rows`. ``encoder`` is the optional CLIP test
    hook (default live). Returns the observations plus the fused
    verdict; persistence is the caller's job.
    """
    cfg = load_config()
    claim = _normalise_claim(claim_text)
    received_at = datetime.now(timezone.utc)
    provenance = provenance_checks.provenance_signals(raw, received_at)
    digest = sha256_hex(raw)
    phash = phash_hex(raw)
    duplicate_ids: list = []
    exact = duplicates.exact_match(digest, store)
    if exact is not None:
        duplicate_ids.append(exact)
    for near_id in duplicates.near_matches(
        phash, store, cfg.phash_max_distance
    ):
        if near_id not in duplicate_ids:
            duplicate_ids.append(near_id)
    incident = clip_checks.incident_probs(raw, encoder=encoder)
    severity = clip_checks.severity_probs(raw, encoder=encoder)
    claim_sim = clip_checks.claim_similarity(raw, claim, encoder=encoder)
    fused = fusion.fuse(
        AllChecks(
            file_ok=True,
            file_reason=None,
            mock_match=False,
            provenance=provenance,
            duplicate_ids=list(duplicate_ids),
            claimed_time=None,
            prior_time=None,
            incident=dict(incident),
            severity=dict(severity),
            claim_sim=claim_sim,
        ),
        cfg,
    )
    return {
        "sha256": digest,
        "phash": phash,
        "provenance": provenance,
        "duplicate_ids": duplicate_ids,
        "incident_probs": dict(incident),
        "severity_probs": dict(severity),
        "claim_sim": claim_sim,
        "verdict": fused,
    }


def build_response(
    report_id: int,
    incident_probs: dict,
    severity_probs: dict,
    label: str,
    reasons: list,
) -> dict:
    """Build the exact 200 response body for a finished report.

    Confidence is the top incident probability and ``needs_review``
    tracks the label (both unchanged from spec 1 via ``fuse``).
    """
    incident = dict(incident_probs)
    severity = dict(severity_probs)
    return {
        "report_id": report_id,
        "incident_probs": incident,
        "severity_probs": severity,
        "top_severity": max(severity, key=severity.get),
        "verdict": label,
        "reasons": list(reasons),
        "confidence": max(incident.values()),
        "needs_review": label != "likely-real",
    }


def stored_response(conn, report_row) -> dict:
    """Rebuild the 200 body for an existing report (idempotent replay)."""
    check = conn.execute(
        "SELECT * FROM check_results WHERE report_id = ?",
        (report_row["id"],),
    ).fetchone()
    if check is None:
        raise RuntimeError(
            f"missing check_results for report {report_row['id']}"
        )
    return build_response(
        report_row["id"],
        json.loads(check["incident_probs"]),
        json.loads(check["severity_probs"]),
        check["verdict"],
        json.loads(check["reasons"]),
    )


def persist_accepted_upload(
    conn,
    *,
    report_id: int,
    incident_probs: dict,
    severity_probs: dict,
    provenance,
    label: str,
    reasons: list,
) -> None:
    """Write the ``check_results`` row for an accepted upload."""
    conn.execute(
        "INSERT INTO check_results (report_id, incident_probs,"
        " severity_probs, provenance, verdict, reasons)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            report_id,
            json.dumps(dict(incident_probs)),
            json.dumps(dict(severity_probs)),
            json.dumps(asdict(provenance)),
            label,
            json.dumps(list(reasons)),
        ),
    )
    conn.commit()


def process_upload(
    *,
    conn,
    account_id: int,
    raw: bytes,
    claim_text: str | None,
    client_report_id: str,
    location_lat: float,
    location_lng: float,
    location_source: str,
    uploads_dir,
    encoder=None,
) -> tuple[int, dict]:
    """Process one verified upload; returns ``(http_status, body)``.

    Order: idempotent replay (same account + ``client_report_id``
    returns the existing report with no new rows or files), file
    sanity (413 oversize / 415 unsupported), mock hash gate (generic
    rejection body plus one audit event, no file or report row), then
    provenance -> duplicates -> CLIP -> claim -> fusion with report,
    ``check_results``, and file persistence.
    """
    cfg = load_config()
    existing = find_report(conn, account_id, client_report_id)
    if existing is not None:
        return 200, stored_response(conn, existing)
    if len(raw) > cfg.max_upload_bytes:
        return 413, {"detail": OVERSIZE_DETAIL}
    if not file_checks.check_file(raw).ok:
        return 415, {"detail": UNSUPPORTED_DETAIL}
    digest = sha256_hex(raw)
    if file_checks.mock_hash_match(raw, load_mock_hashes()):
        record_mock_rejection(conn, account_id, digest)
        return 200, {
            "detail": MOCK_REJECTION_DETAIL,
            "demo_notice": MOCK_DEMO_NOTICE,
        }
    analysis = analyze_bytes(
        raw, claim_text, prior_report_rows(conn), encoder=encoder
    )
    report_id, created = create_report(
        conn,
        account_id=account_id,
        client_report_id=client_report_id,
        sha256=analysis["sha256"],
        phash=analysis["phash"],
        location_lat=location_lat,
        location_lng=location_lng,
        location_consented=1,
        location_source=location_source,
    )
    if not created:
        # Lost a race with a concurrent first insert: first wins.
        return 200, stored_response(
            conn, find_report(conn, account_id, client_report_id)
        )
    verdict = analysis["verdict"]
    persist_accepted_upload(
        conn,
        report_id=report_id,
        incident_probs=analysis["incident_probs"],
        severity_probs=analysis["severity_probs"],
        provenance=analysis["provenance"],
        label=verdict.label,
        reasons=verdict.reasons,
    )
    write_upload_file(uploads_dir, account_id, report_id, raw)
    return 200, build_response(
        report_id,
        analysis["incident_probs"],
        analysis["severity_probs"],
        verdict.label,
        verdict.reasons,
    )
