"""Smoke test for the local CLIP model (Lite spec 0, objective 0.4).

Loads the pinned model from ``lite/data/artifacts/`` (downloading from
HuggingFace on first use), classifies one synthetic fixture, and logs
the device used plus the load time. Passes on GPU, or on CPU with the
fallback flagged in :class:`ClipInfo`.
"""

import logging
from pathlib import Path

from lite.app.checks import clip_model
from lite.app.config import load_config

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
ARTIFACTS_DIR = Path(__file__).resolve().parents[1] / "data" / "artifacts"

logger = logging.getLogger(__name__)


def test_clip_model_smoke(caplog):
    cfg = load_config()
    with caplog.at_level(logging.INFO):
        model, _processor, info = clip_model.load_clip()
    assert model is not None
    assert info.model_id == cfg.clip_model_id
    assert ARTIFACTS_DIR.is_dir(), "weights must live under lite/data/artifacts/"
    weights = list(ARTIFACTS_DIR.rglob("*"))
    assert any(p.is_file() for p in weights), "no weight files downloaded"
    if info.device == "cuda":
        assert not info.cpu_fallback
    else:
        assert info.device == "cpu"
        assert info.cpu_fallback == (cfg.clip_device != "cpu")
    label, confidence = clip_model.classify_image(
        FIXTURES_DIR / "shapes_basic.png"
    )
    assert label in cfg.incident_prompts
    assert 0.0 <= confidence <= 1.0
    assert info.load_seconds >= 0.0
    model_dir = ARTIFACTS_DIR / cfg.clip_model_id.replace("/", "__")
    total_bytes, file_count, licence = clip_model.artifacts_summary(model_dir)
    assert total_bytes > 0, "snapshot has no bytes on disk"
    print(
        f"clip smoke: model={info.model_id} rev={info.revision} "
        f"device={info.device} fallback={info.cpu_fallback} "
        f"load_s={info.load_seconds:.1f} label={label} "
        f"confidence={confidence:.3f} files={file_count} "
        f"bytes={total_bytes} licence={licence}"
    )
    logger.info(
        "clip smoke: device=%s load_s=%.1f label=%s confidence=%.3f",
        info.device,
        info.load_seconds,
        label,
        confidence,
    )
