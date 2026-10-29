"""Tests for Lite spec 1, objective 1.5: fusion-lite verdict rules.

Thresholds (``low_confidence_below``, ``claim_mismatch_below``) are read
from ``lite/config.yaml`` via :func:`lite.app.config.load_config` and are
never re-typed here. ``AllChecks`` values are built directly in-test from
plain dicts, datetimes and real ``Provenance`` objects; no fixtures needed.

Rule order under test (first match wins the LABEL, ALL matched reasons
are listed, ``needs_review`` is ``label != "likely-real"``, ``confidence``
is ``max(incident.values())``):

1. ``mock_match`` True -> needs-review ``upload_not_accepted``.
2. Non-empty ``duplicate_ids`` with differing present times -> ``previously_submitted``.
3. ``max(incident)`` below threshold -> ``low_confidence``; top severity
   ``severe`` -> ``high_severity``.
4. ``claim_sim`` below threshold -> ``claim_mismatch``.
5. Editor tag with implausible time -> likely-manipulated, edited-time reason.
6. Otherwise likely-real, no-inconsistencies reason.
"""

import re
from datetime import datetime, timedelta, timezone

from lite.app.checks.fusion import AllChecks, fuse
from lite.app.checks.provenance import Provenance
from lite.app.config import load_config

MANIPULATED_REASON = (
    "signals observed: edited file with inconsistent capture time"
)
REAL_REASON = "signals observed: no inconsistencies found (demo checks only)"
LABEL_TOKENS = ("likely-real", "needs-review", "likely-manipulated")
CERTAINTY_RE = re.compile(r"\b(proven|fake|real)\b", re.IGNORECASE)

CLAIMED_AT = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)
PRIOR_AT = CLAIMED_AT - timedelta(days=1)


def _below(threshold: float) -> float:
    """A value strictly below ``threshold`` that stays >= 0."""
    candidate = threshold - 0.1
    return candidate if candidate >= 0.0 else threshold / 2.0


def _above(threshold: float) -> float:
    """A value strictly above ``threshold`` that stays <= 1."""
    candidate = threshold + 0.3
    return candidate if candidate <= 1.0 else (threshold + 1.0) / 2.0


def _incident_probs(cfg, top_value: float) -> dict:
    labels = list(cfg.incident_prompts)
    return {label: (top_value if i == 0 else 0.0) for i, label in enumerate(labels)}


def _severity_probs(cfg, top_label: str) -> dict:
    assert top_label in cfg.severity_prompts
    return {
        label: (0.9 if label == top_label else 0.05)
        for label in cfg.severity_prompts
    }


def _non_severe_label(cfg) -> str:
    return next(label for label in cfg.severity_prompts if label != "severe")


def _provenance(editor_tag=None, time_plausible: bool = True) -> Provenance:
    return Provenance(
        exif_present=editor_tag is not None,
        time_plausible=time_plausible,
        gps_present=False,
        editor_tag=editor_tag,
    )


def _clean_checks(cfg, **overrides) -> AllChecks:
    """AllChecks that trigger no rule (expect likely-real)."""
    kwargs = {
        "file_ok": True,
        "file_reason": None,
        "mock_match": False,
        "provenance": _provenance(),
        "duplicate_ids": [],
        "claimed_time": None,
        "prior_time": None,
        "incident": _incident_probs(cfg, _above(cfg.low_confidence_below)),
        "severity": _severity_probs(cfg, _non_severe_label(cfg)),
        "claim_sim": None,
    }
    kwargs.update(overrides)
    return AllChecks(**kwargs)


def _reasons_contain(reasons: list, token: str) -> bool:
    return any(token in reason for reason in reasons)


def test_mock_match_is_defensive_needs_review():
    cfg = load_config()
    verdict = fuse(_clean_checks(cfg, mock_match=True), cfg)
    assert verdict.label == "needs-review"
    assert _reasons_contain(verdict.reasons, "upload_not_accepted")
    assert verdict.needs_review is True


def test_duplicate_with_differing_times_needs_review():
    cfg = load_config()
    checks = _clean_checks(
        cfg,
        duplicate_ids=["abc123"],
        claimed_time=CLAIMED_AT,
        prior_time=PRIOR_AT,
    )
    verdict = fuse(checks, cfg)
    assert verdict.label == "needs-review"
    assert _reasons_contain(verdict.reasons, "previously_submitted")
    assert verdict.needs_review is True
    # Same time, a missing time, or no ids: rule 2 does not fire.
    assert (
        fuse(
            _clean_checks(
                cfg,
                duplicate_ids=["abc123"],
                claimed_time=CLAIMED_AT,
                prior_time=CLAIMED_AT,
            ),
            cfg,
        ).label
        == "likely-real"
    )
    assert (
        fuse(
            _clean_checks(
                cfg,
                duplicate_ids=["abc123"],
                claimed_time=CLAIMED_AT,
                prior_time=None,
            ),
            cfg,
        ).label
        == "likely-real"
    )
    assert (
        fuse(
            _clean_checks(
                cfg,
                duplicate_ids=[],
                claimed_time=CLAIMED_AT,
                prior_time=PRIOR_AT,
            ),
            cfg,
        ).label
        == "likely-real"
    )


def test_low_confidence_needs_review():
    cfg = load_config()
    low = _below(cfg.low_confidence_below)
    checks = _clean_checks(cfg, incident=_incident_probs(cfg, low))
    verdict = fuse(checks, cfg)
    assert max(checks.incident.values()) < cfg.low_confidence_below
    assert verdict.label == "needs-review"
    assert _reasons_contain(verdict.reasons, "low_confidence")
    assert verdict.needs_review is True
    assert verdict.confidence == max(checks.incident.values()) == low


def test_high_severity_needs_review():
    cfg = load_config()
    assert "severe" in cfg.severity_prompts
    severity = _severity_probs(cfg, "severe")
    assert max(severity, key=severity.get) == "severe"
    verdict = fuse(_clean_checks(cfg, severity=severity), cfg)
    assert verdict.label == "needs-review"
    assert _reasons_contain(verdict.reasons, "high_severity")
    assert verdict.needs_review is True


def test_severe_and_low_confidence_together_still_need_review():
    cfg = load_config()
    checks = _clean_checks(
        cfg,
        incident=_incident_probs(cfg, _below(cfg.low_confidence_below)),
        severity=_severity_probs(cfg, "severe"),
    )
    verdict = fuse(checks, cfg)
    assert verdict.label == "needs-review"
    assert _reasons_contain(verdict.reasons, "low_confidence")
    assert _reasons_contain(verdict.reasons, "high_severity")
    assert verdict.needs_review is True


def test_claim_mismatch_needs_review():
    cfg = load_config()
    low_sim = _below(cfg.claim_mismatch_below)
    checks = _clean_checks(cfg, claim_sim=low_sim)
    verdict = fuse(checks, cfg)
    assert verdict.label == "needs-review"
    assert _reasons_contain(verdict.reasons, "claim_mismatch")
    assert verdict.needs_review is True
    # A missing claim short-circuits the rule; a high claim passes it.
    assert fuse(_clean_checks(cfg, claim_sim=None), cfg).label == "likely-real"
    assert (
        fuse(
            _clean_checks(cfg, claim_sim=_above(cfg.claim_mismatch_below)), cfg
        ).label
        == "likely-real"
    )


def test_edited_with_implausible_time_is_likely_manipulated():
    cfg = load_config()
    checks = _clean_checks(
        cfg, provenance=_provenance(editor_tag="demo-editor", time_plausible=False)
    )
    verdict = fuse(checks, cfg)
    assert verdict.label == "likely-manipulated"
    assert MANIPULATED_REASON in verdict.reasons
    assert verdict.needs_review is True
    assert verdict.confidence == max(checks.incident.values())
    # Either half of rule 5 alone is not enough.
    assert (
        fuse(
            _clean_checks(
                cfg,
                provenance=_provenance(editor_tag="demo-editor", time_plausible=True),
            ),
            cfg,
        ).label
        == "likely-real"
    )
    assert (
        fuse(
            _clean_checks(
                cfg, provenance=_provenance(editor_tag=None, time_plausible=False)
            ),
            cfg,
        ).label
        == "likely-real"
    )


def test_clean_inputs_are_likely_real():
    cfg = load_config()
    checks = _clean_checks(cfg)
    verdict = fuse(checks, cfg)
    assert verdict.label == "likely-real"
    assert REAL_REASON in verdict.reasons
    assert verdict.needs_review is False
    assert verdict.confidence == max(checks.incident.values())


def test_first_match_wins_label_but_all_reasons_listed():
    cfg = load_config()
    checks = _clean_checks(
        cfg,
        incident=_incident_probs(cfg, _below(cfg.low_confidence_below)),
        provenance=_provenance(editor_tag="demo-editor", time_plausible=False),
    )
    verdict = fuse(checks, cfg)
    # Rule 3 fires before rule 5, so the label stays needs-review ...
    assert verdict.label == "needs-review"
    # ... but every matched reason is still reported.
    assert _reasons_contain(verdict.reasons, "low_confidence")
    assert MANIPULATED_REASON in verdict.reasons
    assert verdict.needs_review is True


def test_confidence_is_max_incident_prob_across_labels():
    cfg = load_config()
    cases = [
        _clean_checks(cfg),
        _clean_checks(
            cfg, incident=_incident_probs(cfg, _below(cfg.low_confidence_below))
        ),
        _clean_checks(
            cfg, provenance=_provenance(editor_tag="demo-editor", time_plausible=False)
        ),
    ]
    for checks in cases:
        assert fuse(checks, cfg).confidence == max(checks.incident.values())


def test_needs_review_tracks_label():
    cfg = load_config()
    verdicts = [
        fuse(_clean_checks(cfg), cfg),
        fuse(_clean_checks(cfg, mock_match=True), cfg),
        fuse(
            _clean_checks(
                cfg,
                duplicate_ids=["abc123"],
                claimed_time=CLAIMED_AT,
                prior_time=PRIOR_AT,
            ),
            cfg,
        ),
        fuse(
            _clean_checks(
                cfg,
                provenance=_provenance(editor_tag="demo-editor", time_plausible=False),
            ),
            cfg,
        ),
    ]
    assert {verdict.label for verdict in verdicts} == {
        "likely-real",
        "needs-review",
        "likely-manipulated",
    }
    for verdict in verdicts:
        assert verdict.needs_review == (verdict.label != "likely-real")


def test_reasons_use_no_certainty_language():
    cfg = load_config()
    verdicts = [
        fuse(_clean_checks(cfg), cfg),
        fuse(_clean_checks(cfg, mock_match=True), cfg),
        fuse(
            _clean_checks(
                cfg,
                duplicate_ids=["abc123"],
                claimed_time=CLAIMED_AT,
                prior_time=PRIOR_AT,
            ),
            cfg,
        ),
        fuse(
            _clean_checks(
                cfg, incident=_incident_probs(cfg, _below(cfg.low_confidence_below))
            ),
            cfg,
        ),
        fuse(_clean_checks(cfg, severity=_severity_probs(cfg, "severe")), cfg),
        fuse(
            _clean_checks(cfg, claim_sim=_below(cfg.claim_mismatch_below)), cfg
        ),
        fuse(
            _clean_checks(
                cfg,
                provenance=_provenance(editor_tag="demo-editor", time_plausible=False),
            ),
            cfg,
        ),
    ]
    assert verdicts, "expected at least one verdict to scrub"
    for verdict in verdicts:
        assert verdict.reasons, "expected every verdict to carry reasons"
        for reason in verdict.reasons:
            scrubbed = reason
            for token in LABEL_TOKENS:
                scrubbed = scrubbed.replace(token, "")
            assert not CERTAINTY_RE.search(scrubbed), (
                f"certainty language in reason: {reason!r}"
            )
