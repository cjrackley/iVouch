"""Local CLIP model loader and single-image zero-shot classify.

Lite spec 0, objective 0.4. The model id, requested device, and prompt
text are read via :func:`lite.app.config.load_config` -- never re-typed
here. Weights live ONLY under ``lite/data/artifacts/`` (git-ignored):
downloaded from HuggingFace on first use, reused from disk afterwards.
The loader caches the model in-process (load-once); when CUDA is absent
or unusable the loader falls back to CPU and says so.
"""

from __future__ import annotations

import logging
import os
import queue
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import torch
from huggingface_hub import HfApi, snapshot_download
from PIL import Image
from transformers import CLIPModel, CLIPProcessor

from lite.app.config import load_config

logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path(__file__).resolve().parents[2] / "data" / "artifacts"

# Bounds so a stalled network can never hang the run forever: each
# download attempt gets DOWNLOAD_TIMEOUT_S, the revision lookup gets
# REVISION_TIMEOUT_S, and first inference gets INFERENCE_TIMEOUT_S.
# Bounds favour many fast retries: the sandbox proxy is a coin flip
# per request, so short attempts that fail fast and resume flip the
# most coins per minute. SLOW_REQUEST_S is kept only for the etag
# (HEAD) calls, which otherwise burn whole attempts on metadata.
DOWNLOAD_TIMEOUT_S = 240.0
DOWNLOAD_ATTEMPTS = 3
REVISION_TIMEOUT_S = 60.0
INFERENCE_TIMEOUT_S = 300.0
SLOW_REQUEST_S = 60.0
DOWNLOAD_WORKERS = 8

_cached: dict = {}


@dataclass(frozen=True)
class ClipInfo:
    """How the cached CLIP model was loaded."""

    model_id: str
    revision: str
    device: str
    cpu_fallback: bool
    load_seconds: float


def _model_dir(model_id: str) -> Path:
    return ARTIFACTS_DIR / model_id.replace("/", "__")


def _call_with_timeout(label: str, timeout_s: float, func, *args, **kwargs):
    """Run ``func`` in a daemon worker; raise ``TimeoutError`` past the bound.

    The worker is a daemon thread (not a pooled executor) on purpose: a
    hung network call must never block the retry loop or process exit,
    which a pool shutdown would. An orphaned download keeps writing
    partial files that the next attempt resumes.
    """

    box: queue.Queue = queue.Queue(maxsize=1)

    def _run() -> None:
        try:
            box.put((True, func(*args, **kwargs)))
        except BaseException as exc:  # deliver failures to the waiter
            box.put((False, exc))

    worker = threading.Thread(target=_run, name=f"clip-{label}", daemon=True)
    worker.start()
    try:
        ok, value = box.get(timeout=timeout_s)
    except queue.Empty as exc:
        logger.warning("%s timed out after %.0fs", label, timeout_s)
        raise TimeoutError(f"{label} timed out after {timeout_s:.0f}s") from exc
    if not ok:
        raise value
    return value


def _resolve_revision(model_id: str) -> str:
    try:
        info = _call_with_timeout(
            f"revision lookup for {model_id}",
            REVISION_TIMEOUT_S,
            HfApi().model_info,
            model_id,
        )
        return info.sha or "unresolved"
    except Exception as exc:  # network or API trouble: still loadable
        logger.warning("could not resolve revision for %s: %s", model_id, exc)
        return "unresolved"


def _download_model(model_id: str, local_dir: Path) -> None:
    """Fetch ``model_id`` into ``local_dir`` with bounded retries.

    Partial downloads resume on retry (huggingface_hub keeps the
    incomplete files), so a transient proxy failure does not restart
    from zero. Raises the last error after ``DOWNLOAD_ATTEMPTS`` tries.
    """
    os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", str(SLOW_REQUEST_S))
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", str(SLOW_REQUEST_S))
    last_exc: Exception | None = None
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        logger.info(
            "downloading %s -> %s (attempt %d/%d, timeout %.0fs)",
            model_id,
            local_dir,
            attempt,
            DOWNLOAD_ATTEMPTS,
            DOWNLOAD_TIMEOUT_S,
        )
        try:
            _call_with_timeout(
                f"download of {model_id} (attempt {attempt})",
                DOWNLOAD_TIMEOUT_S,
                snapshot_download,
                repo_id=model_id,
                local_dir=str(local_dir),
                max_workers=DOWNLOAD_WORKERS,
                etag_timeout=SLOW_REQUEST_S,
            )
            logger.info("download of %s finished", model_id)
            return
        except Exception as exc:  # transient proxy/network trouble: retry
            last_exc = exc
            logger.warning(
                "download attempt %d/%d for %s failed: %s",
                attempt,
                DOWNLOAD_ATTEMPTS,
                model_id,
                exc,
            )
    raise RuntimeError(
        f"download of {model_id} failed after {DOWNLOAD_ATTEMPTS} attempts: {last_exc}"
    ) from last_exc


def artifacts_summary(local_dir: Path) -> tuple[int, int, str]:
    """Return ``(total_bytes, file_count, licence)`` for a model snapshot dir.

    The licence is read from the snapshot's own ``README.md`` frontmatter
    (``license: ...``) when present; otherwise ``"unknown"``.
    """
    files = [p for p in local_dir.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    licence = "unknown"
    readme = local_dir / "README.md"
    if readme.is_file():
        match = re.search(
            r"^license:\s*(\S+)",
            readme.read_text(encoding="utf-8", errors="replace"),
            re.MULTILINE,
        )
        if match:
            licence = match.group(1).strip().strip("\"'")
    return total, len(files), licence


def load_clip() -> tuple[CLIPModel, CLIPProcessor, ClipInfo]:
    """Load the pinned CLIP model once; return ``(model, processor, info)``.

    Later calls return the cached triple without re-reading disk.
    """
    if _cached:
        return _cached["model"], _cached["processor"], _cached["info"]
    cfg = load_config()
    started = time.perf_counter()
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    local_dir = _model_dir(cfg.clip_model_id)
    _download_model(cfg.clip_model_id, local_dir)
    total_bytes, file_count, licence = artifacts_summary(local_dir)
    logger.info(
        "snapshot %s: %d files, %.1f MB, licence=%s",
        cfg.clip_model_id,
        file_count,
        total_bytes / 1e6,
        licence,
    )
    if cfg.clip_device == "cuda" and torch.cuda.is_available():
        device = "cuda"
        cpu_fallback = False
    else:
        device = "cpu"
        cpu_fallback = cfg.clip_device != "cpu"
    if cpu_fallback:
        logger.warning(
            "requested device %r unavailable; falling back to CPU",
            cfg.clip_device,
        )
    model = CLIPModel.from_pretrained(str(local_dir)).to(device).eval()
    processor = CLIPProcessor.from_pretrained(str(local_dir))
    info = ClipInfo(
        model_id=cfg.clip_model_id,
        revision=_resolve_revision(cfg.clip_model_id),
        device=device,
        cpu_fallback=cpu_fallback,
        load_seconds=time.perf_counter() - started,
    )
    logger.info(
        "loaded %s (rev %s) on %s in %.1fs",
        info.model_id,
        info.revision,
        info.device,
        info.load_seconds,
    )
    _cached.update(model=model, processor=processor, info=info)
    return model, processor, info


def classify_image(image_path: str | Path) -> tuple[str, float]:
    """Zero-shot classify one image; return ``(label, confidence)``.

    Candidate labels and prompt text come from ``incident_prompts`` in
    ``lite/config.yaml``. Confidence is the softmax probability of the
    winning prompt, in ``[0, 1]``.
    """
    cfg = load_config()
    model, processor, info = load_clip()
    labels = list(cfg.incident_prompts)
    prompts = [cfg.incident_prompts[label] for label in labels]
    with Image.open(image_path) as img:
        img.load()
        rgb = img.convert("RGB")
    inputs = processor(
        text=prompts, images=rgb, return_tensors="pt", padding=True
    )
    inputs = {k: v.to(info.device) for k, v in inputs.items()}
    with torch.no_grad():
        logits = _call_with_timeout(
            "first CLIP inference",
            INFERENCE_TIMEOUT_S,
            lambda: model(**inputs).logits_per_image,
        )
        probs = logits.softmax(dim=1)[0]
    best = int(probs.argmax())
    return labels[best], float(probs[best])
