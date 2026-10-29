"""Incident / severity zero-shot checks over local CLIP (Lite spec 1, objective 1.4).

Pipeline positions: steps 5-7 of the spec-1 check pipeline.

Prompt text lives ONLY in ``lite/config.yaml`` and is read here via
:func:`lite.app.config.load_config` -- no prompt literal appears in
this module. The model itself loads once through
:func:`lite.app.checks.clip_model.load_clip` (GPU with CPU fallback);
this module never reimplements downloading or loading.

Each function accepts an optional ``encoder`` hook for testability: an
object with ``image_embed(image)`` and ``text_embeds(texts)`` methods
returning embedding vectors as float sequences. When ``encoder`` is
``None`` (the default) the real CLIP path is used. Unit tests pass a
stub encoder (allowed by the spec); one test marked ``slow``
exercises the real path on a committed fixture.
"""

from __future__ import annotations

import math
from io import BytesIO
from typing import Protocol, Sequence

import torch
from PIL import Image

from lite.app.checks import clip_model
from lite.app.config import load_config

_TOL_SUM = 1e-3


class ClipEncoder(Protocol):
    """Test hook: embedding provider for the zero-shot checks."""

    def image_embed(self, image: Image.Image) -> Sequence[float]:
        """Return the image embedding vector for a PIL RGB image."""
        ...

    def text_embeds(self, texts: list[str]) -> list[Sequence[float]]:
        """Return one embedding vector per prompt text, in order."""
        ...


def _to_pil(img) -> Image.Image:
    """Normalise ``img`` (PIL image, raw bytes, or path) to a PIL RGB image."""
    if isinstance(img, Image.Image):
        return img.convert("RGB")
    if isinstance(img, bytes):
        with Image.open(BytesIO(img)) as opened:
            opened.load()
            return opened.convert("RGB")
    with Image.open(img) as opened:
        opened.load()
        return opened.convert("RGB")


def _norm(vec: Sequence[float]) -> list[float]:
    length = math.sqrt(sum(float(v) * float(v) for v in vec))
    if length == 0.0:
        return [0.0 for _ in vec]
    return [float(v) / length for v in vec]


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise ValueError(
            f"embedding length mismatch: {len(a)} != {len(b)}"
        )
    denom = math.sqrt(sum(x * x for x in a)) * math.sqrt(
        sum(x * x for x in b)
    )
    if denom == 0.0:
        return 0.0
    value = sum(x * y for x, y in zip(a, b)) / denom
    return max(-1.0, min(1.0, value))


def _softmax(logits: Sequence[float]) -> list[float]:
    peak = max(logits)
    exps = [math.exp(float(v) - peak) for v in logits]
    total = sum(exps)
    return [v / total for v in exps]


class _LiveClipEncoder:
    """Real CLIP embedding path; built on :func:`clip_model.load_clip`."""

    def __init__(self) -> None:
        model, processor, info = clip_model.load_clip()
        self._model = model
        self._processor = processor
        self._device = info.device
        with torch.no_grad():
            self._scale = float(model.logit_scale.exp().item())

    @property
    def scale(self) -> float:
        """CLIP logit scale (``exp(logit_scale)``); zero-shot softmax temperature."""
        return self._scale

    @torch.no_grad()
    def image_embed(self, image: Image.Image) -> list[float]:
        inputs = self._processor(
            images=image.convert("RGB"), return_tensors="pt"
        )
        pixel_values = inputs["pixel_values"].to(self._device)
        feats = self._model.get_image_features(pixel_values=pixel_values)
        if not isinstance(feats, torch.Tensor):
            feats = feats.pooler_output
        return feats[0].detach().float().cpu().tolist()

    @torch.no_grad()
    def text_embeds(self, texts: list[str]) -> list[list[float]]:
        inputs = self._processor(
            text=list(texts), return_tensors="pt", padding=True
        )
        inputs = {k: v.to(self._device) for k, v in inputs.items()}
        feats = self._model.get_text_features(**inputs)
        if not isinstance(feats, torch.Tensor):
            feats = feats.pooler_output
        return feats.detach().float().cpu().tolist()


_live: _LiveClipEncoder | None = None


def _real_encoder() -> _LiveClipEncoder:
    global _live
    if _live is None:
        _live = _LiveClipEncoder()
    return _live


def _probs_over_prompts(
    img, prompts: dict, encoder: ClipEncoder | None
) -> dict[str, float]:
    """Softmax distribution over an ordered ``{label: prompt}`` mapping."""
    pil = _to_pil(img)
    labels = list(prompts)
    texts = [prompts[label] for label in labels]
    live = _real_encoder() if encoder is None else None
    backend = live if live is not None else encoder
    assert backend is not None
    image_vec = backend.image_embed(pil)
    text_vecs = backend.text_embeds(texts)
    if len(text_vecs) != len(labels):
        raise ValueError(
            f"encoder returned {len(text_vecs)} text embeddings "
            f"for {len(labels)} prompts"
        )
    scale = live.scale if live is not None else 1.0
    logits = [scale * _cosine(image_vec, vec) for vec in text_vecs]
    probs = _softmax(logits)
    return {label: prob for label, prob in zip(labels, probs)}


def incident_probs(img, encoder: ClipEncoder | None = None) -> dict[str, float]:
    """Zero-shot distribution over the six incident labels in config.

    Keys are the ``incident_prompts`` labels from ``lite/config.yaml``;
    values are finite, non-negative, and sum to ~1.
    """
    cfg = load_config()
    return _probs_over_prompts(img, cfg.incident_prompts, encoder)


def severity_probs(img, encoder: ClipEncoder | None = None) -> dict[str, float]:
    """Zero-shot distribution over the three severity labels in config.

    Keys are the ``severity_prompts`` labels from ``lite/config.yaml``;
    values are finite, non-negative, and sum to ~1.
    """
    cfg = load_config()
    return _probs_over_prompts(img, cfg.severity_prompts, encoder)


def claim_similarity(
    img, claim: str | None, encoder: ClipEncoder | None = None
) -> float | None:
    """Cosine similarity between the image and claim-text embeddings.

    Returns a float in ``[-1, 1]``, or ``None`` when the claim is
    ``None`` or blank (whitespace-only).
    """
    if claim is None or not claim.strip():
        return None
    pil = _to_pil(img)
    backend = _real_encoder() if encoder is None else encoder
    assert backend is not None
    image_vec = backend.image_embed(pil)
    (text_vec,) = backend.text_embeds([claim])
    return _cosine(image_vec, text_vec)
