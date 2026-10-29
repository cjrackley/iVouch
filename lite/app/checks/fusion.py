"""Fusion-lite verdict (Lite spec 1, objective 1.5).

Pipeline position: final step of the spec-1 check pipeline. This module
combines the observation flags from the earlier checks into a single
verdict. Thresholds come only from the passed config object
(``low_confidence_below``, ``claim_mismatch_below``); no threshold
value is re-typed here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from lite.app.checks.provenance import Provenance


@dataclass(frozen=True)
class AllChecks:
    file_ok: bool
    file_reason: str | None
    mock_match: bool
    provenance: Provenance
    duplicate_ids: list[str]
    claimed_time: datetime | None
    prior_time: datetime | None
    incident: dict[str, float]
    severity: dict[str, float]
    claim_sim: float | None


@dataclass(frozen=True)
class Verdict:
    label: str  # "likely-real" | "needs-review" | "likely-manipulated"
    confidence: float
    reasons: list[str]
    needs_review: bool


def fuse(checks: AllChecks, cfg) -> Verdict:
    """Fuse per-check observations into a single verdict.

    ``cfg`` is the ``lite.app.config.load_config()`` shape (only
    ``low_confidence_below`` and ``claim_mismatch_below`` are read).
    The first matching rule wins the label; every matched reason is
    collected in rule order.
    """
    if checks.mock_match:
        return Verdict(
            label="needs-review",
            confidence=0.0,
            reasons=["upload_not_accepted"],
            needs_review=True,
        )

    reasons: list[str] = []
    label: str | None = None

    if (
        checks.duplicate_ids
        and checks.claimed_time is not None
        and checks.prior_time is not None
        and checks.claimed_time != checks.prior_time
    ):
        if label is None:
            label = "needs-review"
        reasons.append("previously_submitted")

    top = max(checks.incident.values())

    if top < cfg.low_confidence_below:
        if label is None:
            label = "needs-review"
        reasons.append("low_confidence")

    if checks.severity and max(checks.severity, key=checks.severity.get) == "severe":
        if label is None:
            label = "needs-review"
        reasons.append("high_severity")

    if checks.claim_sim is not None and checks.claim_sim < cfg.claim_mismatch_below:
        if label is None:
            label = "needs-review"
        reasons.append("claim_mismatch")

    if checks.provenance.editor_tag and not checks.provenance.time_plausible:
        if label is None:
            label = "likely-manipulated"
        reasons.append(
            "signals observed: edited file with inconsistent capture time"
        )

    if label is None:
        label = "likely-real"
        reasons.append(
            "signals observed: no inconsistencies found (demo checks only)"
        )

    return Verdict(
        label=label,
        confidence=top,
        reasons=reasons,
        needs_review=(label != "likely-real"),
    )
