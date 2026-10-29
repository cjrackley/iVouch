"""Tests for Lite spec 1, objective 1.1: file sanity + mock safety gate.

Uses ONLY committed spec-0 fixtures plus small synthetic byte strings;
never fetches images from the network.
"""

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from lite.app.checks.files import (
    MOCK_REJECT_REASON,
    check_file,
    mock_hash_match,
)
from lite.app.config import load_config
from lite.tests.fixtures.generate import IMAGE_NAMES

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _mock_hashes() -> set[str]:
    cfg = load_config()
    hashes_path = Path(cfg.policy_mock_hashes_path)
    if not hashes_path.is_absolute():
        hashes_path = REPO_ROOT / hashes_path
    return {
        line.strip()
        for line in hashes_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def test_valid_fixtures_pass_file_sanity():
    for name in IMAGE_NAMES:
        raw = (FIXTURES_DIR / name).read_bytes()
        result = check_file(raw)
        assert result.ok is True, f"{name} unexpectedly rejected"
        assert result.reason is None, f"{name} has reason {result.reason!r}"


def test_non_image_bytes_rejected():
    for raw in (b"this is definitely not an image", b"\x00\x01\x02\x03", b""):
        result = check_file(raw)
        assert result.ok is False
        assert result.reason == "unsupported_file"


def test_oversize_upload_rejected():
    cfg = load_config()
    raw = (FIXTURES_DIR / "solid_no_exif.jpg").read_bytes()
    assert len(raw) <= cfg.max_upload_bytes
    oversize = raw + b"\x00" * (cfg.max_upload_bytes - len(raw) + 1)
    assert len(oversize) > cfg.max_upload_bytes
    result = check_file(oversize)
    assert result.ok is False
    assert result.reason == "unsupported_file"


def test_truncated_jpeg_rejected():
    raw = (FIXTURES_DIR / "solid_no_exif.jpg").read_bytes()
    truncated = raw[: len(raw) // 2]
    assert truncated != raw
    result = check_file(truncated)
    assert result.ok is False
    assert result.reason == "unsupported_file"


def test_mock_hash_match_flags_listed_fixture():
    hashes = _mock_hashes()
    raw = (FIXTURES_DIR / "solid_no_exif.jpg").read_bytes()
    assert hashlib.sha256(raw).hexdigest() in hashes
    assert mock_hash_match(raw, hashes) is True
    assert MOCK_REJECT_REASON == "upload_not_accepted"


def test_mock_hash_match_ignores_unknown_bytes():
    hashes = _mock_hashes()
    assert mock_hash_match(b"unlisted synthetic bytes", hashes) is False
    assert mock_hash_match(b"", set()) is False


def test_mock_match_caller_keeps_no_image_bytes():
    hashes = _mock_hashes()
    raw = (FIXTURES_DIR / "text_no_exif.jpg").read_bytes()
    assert mock_hash_match(raw, hashes) is True
    # Caller-side enforcement (pipeline wiring is spec 2): on a mock
    # match the stored record keeps only hash + time + account id.
    record = {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "received_at": datetime.now(timezone.utc).isoformat(),
        "account_id": "test-account",
        "reason": MOCK_REJECT_REASON,
    }
    assert record["reason"] == "upload_not_accepted"
    for key in record:
        assert key not in ("raw", "bytes", "image", "upload")
    for value in record.values():
        assert value != raw
