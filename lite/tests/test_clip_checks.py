"""Tests for Lite spec 1, objective 1.4: CLIP incident/severity/claim checks.

Uses ONLY committed spec-0 fixtures; never fetches images from the
network. Prompt text is never re-typed here: labels come from
``incident_prompts`` / ``severity_prompts`` in ``lite/config.yaml``
via :func:`lite.app.config.load_config`. Unit tests run against a
stubbed encoder (allowed by the spec); one real-model test marked
``slow`` runs unskipped in the normal suite and verifies the real
path on fixtures.
"""

import math
from pathlib import Path

import pytest
from PIL import Image

from lite.app.checks import clip_model
from lite.app.checks.clip_checks import (
    claim_similarity,
    incident_probs,
    severity_probs,
)
from lite.app.config import load_config
from lite.tests.fixtures.generate import IMAGE_NAMES

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

MATCH_CLAIM = "a street scene with geometric shapes"
MISMATCH_CLAIM = "an unrelated claim about something else entirely"


class FanStub:
    """Deterministic stub encoder: text vectors fan out by position so
    the resulting distribution is non-uniform but valid."""

    def image_embed(self, image):
        assert isinstance(image, Image.Image)
        return [1.0, 1.0]

    def text_embeds(self, texts):
        return [[1.0, 0.1 * (i + 1)] for i, _ in enumerate(texts)]


class ClaimStub:
    """Claim-aware stub: only the designated matching text aligns
    with the image embedding."""

    def __init__(self, match_text):
        self._match = match_text

    def image_embed(self, image):
        return [1.0, 0.0]

    def text_embeds(self, texts):
        return [
            [1.0, 0.0] if text == self._match else [0.0, 1.0]
            for text in texts
        ]


def _raw(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


def _assert_distribution(probs: dict, labels) -> None:
    assert set(probs) == set(labels)
    for value in probs.values():
        assert math.isfinite(value)
        assert value >= 0.0
    assert abs(sum(probs.values()) - 1.0) <= 1e-3


def test_incident_probs_stubbed_shape_all_fixtures():
    cfg = load_config()
    assert len(cfg.incident_prompts) == 6
    for name in IMAGE_NAMES:
        probs = incident_probs(FIXTURES_DIR / name, encoder=FanStub())
        _assert_distribution(probs, cfg.incident_prompts)


def test_severity_probs_stubbed_shape_all_fixtures():
    cfg = load_config()
    assert len(cfg.severity_prompts) == 3
    for name in IMAGE_NAMES:
        probs = severity_probs(FIXTURES_DIR / name, encoder=FanStub())
        _assert_distribution(probs, cfg.severity_prompts)


def test_probs_accept_path_bytes_and_pil():
    incident_labels = set(load_config().incident_prompts)
    name = "shapes_basic.png"
    from_path = incident_probs(FIXTURES_DIR / name, encoder=FanStub())
    from_bytes = incident_probs(_raw(name), encoder=FanStub())
    with Image.open(FIXTURES_DIR / name) as img:
        img.load()
        from_pil = incident_probs(img, encoder=FanStub())
    assert from_path == from_bytes == from_pil
    assert set(from_path) == incident_labels


def test_empty_claim_returns_none():
    stub = ClaimStub(MATCH_CLAIM)
    name = "shapes_basic.png"
    for img in (FIXTURES_DIR / name, _raw(name)):
        assert claim_similarity(img, None, encoder=stub) is None
        assert claim_similarity(img, "", encoder=stub) is None
        assert claim_similarity(img, "   ", encoder=stub) is None


def test_empty_claim_returns_none_without_encoder():
    # Blank claims short-circuit before any model touch.
    assert claim_similarity(FIXTURES_DIR / "shapes_basic.png", None) is None
    assert claim_similarity(FIXTURES_DIR / "shapes_basic.png", "  ") is None


def test_matching_claim_scores_higher_than_mismatched_stubbed():
    stub = ClaimStub(MATCH_CLAIM)
    img = FIXTURES_DIR / "shapes_basic.png"
    match = claim_similarity(img, MATCH_CLAIM, encoder=stub)
    mismatch = claim_similarity(img, MISMATCH_CLAIM, encoder=stub)
    assert match is not None and mismatch is not None
    assert -1.0 <= mismatch <= 1.0
    assert -1.0 <= match <= 1.0
    assert match > mismatch


@pytest.mark.slow
def test_real_model_probs_and_claim_on_fixtures():
    cfg = load_config()
    for name in IMAGE_NAMES:
        path = FIXTURES_DIR / name
        incident = incident_probs(path)
        severity = severity_probs(path)
        _assert_distribution(incident, cfg.incident_prompts)
        _assert_distribution(severity, cfg.severity_prompts)
        sim = claim_similarity(path, MATCH_CLAIM)
        assert sim is not None
        assert -1.0 <= sim <= 1.0
        top_incident = max(incident, key=incident.get)
        top_severity = max(severity, key=severity.get)
        print(
            f"obs {name}: incident={top_incident} "
            f"p={incident[top_incident]:.3f} severity={top_severity} "
            f"p={severity[top_severity]:.3f} claim_sim={sim:.3f}"
        )


@pytest.mark.slow
def test_real_model_incident_matches_smoke_classifier():
    # Same model, same config prompts: the top incident label must
    # agree with clip_model.classify_image on every fixture.
    for name in IMAGE_NAMES:
        path = FIXTURES_DIR / name
        expected_label, _ = clip_model.classify_image(path)
        top = max(
            incident_probs(path), key=incident_probs(path).get
        )
        assert top == expected_label, f"{name}: {top} != {expected_label}"
