"""Exact and near-duplicate lookup (Lite spec 1, objective 1.3).

Pipeline position: step 4 of the spec-1 check pipeline. This module
is a pure function over a minimal sequence protocol -- each store row
is ``(report_id, sha256, phash)`` where ``phash`` is an
``imagehash`` hex string. Spec 2 adapts its rows to that shape before
calling; there is no SQLite here.

The ``max_distance`` argument comes from the caller (the
``phash_max_distance`` value read via
:func:`lite.app.config.load_config` at the call site in spec 2); no
threshold literal lives in this module.
"""

from __future__ import annotations

import imagehash


def exact_match(sha256: str, store) -> str | None:
    """Return the ``report_id`` whose SHA-256 equals ``sha256``, else None.

    The first row in store order wins.
    """
    for report_id, digest, _phash in store:
        if digest == sha256:
            return report_id
    return None


def near_matches(phash: str, store, max_distance: int) -> list[str]:
    """Return ``report_id``s whose perceptual hash is within range.

    A row matches when the Hamming distance between ``phash`` and the
    row's stored ``phash`` (both ``imagehash`` hex strings) is less
    than or equal to ``max_distance``. Results follow store order.
    Rows with unparseable hashes are skipped.
    """
    query = imagehash.hex_to_hash(phash)
    hits: list[str] = []
    for report_id, _digest, row_phash in store:
        try:
            distance = int(query - imagehash.hex_to_hash(row_phash))
        except Exception:
            continue
        if distance <= max_distance:
            hits.append(report_id)
    return hits
