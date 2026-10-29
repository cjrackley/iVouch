"""File sanity and mock safety gate (Lite spec 1, objective 1.1).

Pipeline position: step 1 (file sanity) and step 2 (mock safety gate)
of the spec-1 check pipeline. Spec 2 wires these into the upload
pipeline; this module only exposes the per-bytes verdicts so the
caller can enforce them.

Mock-safety note: :func:`mock_hash_match` compares the SHA-256 of the
raw upload bytes against a fixture hash list loaded from
``policy_mock_hashes_path`` (benign synthetic fixtures only). A match
means the caller must reject with the generic reason
``upload_not_accepted``, store no image bytes, and keep only the
hash + time + account id. This mock is not real screening.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO

from PIL import Image

from lite.app.config import load_config

UNSUPPORTED_FILE = "unsupported_file"
MOCK_REJECT_REASON = "upload_not_accepted"


@dataclass(frozen=True)
class FileResult:
    """Outcome of :func:`check_file`."""

    ok: bool
    reason: str | None = None


def _normalise_format(name: str) -> str:
    lowered = name.strip().lower()
    if lowered == "jpg":
        return "jpeg"
    return lowered


def check_file(raw: bytes) -> FileResult:
    """Accept or reject raw upload bytes for type, size, and decodability.

    Limits come from ``lite/config.yaml`` via
    :func:`lite.app.config.load_config` (``max_upload_bytes`` and
    ``allowed_types``); no limit is re-typed here. Any failure --
    non-image bytes, oversize upload, disallowed type, or
    undecodable/truncated image -- returns
    ``FileResult(ok=False, reason="unsupported_file")``.
    """
    cfg = load_config()
    if not isinstance(raw, bytes) or not raw:
        return FileResult(ok=False, reason=UNSUPPORTED_FILE)
    if len(raw) > cfg.max_upload_bytes:
        return FileResult(ok=False, reason=UNSUPPORTED_FILE)
    allowed = {_normalise_format(item) for item in cfg.allowed_types}
    try:
        with Image.open(BytesIO(raw)) as img:
            fmt = _normalise_format(img.format or "")
            if fmt not in allowed:
                return FileResult(ok=False, reason=UNSUPPORTED_FILE)
            img.load()
    except Exception:
        return FileResult(ok=False, reason=UNSUPPORTED_FILE)
    return FileResult(ok=True, reason=None)


def mock_hash_match(raw: bytes, hashes: set[str]) -> bool:
    """Return True when the SHA-256 of ``raw`` is in ``hashes``.

    ``hashes`` is the set loaded from ``policy_mock_hashes_path``. A
    True result means the caller must reject with the generic reason
    ``upload_not_accepted`` (see ``MOCK_REJECT_REASON``), store no
    image bytes, and keep only hash + time + account id. This mock
    matches benign synthetic fixtures only and is not real screening.
    """
    return hashlib.sha256(raw).hexdigest() in hashes
