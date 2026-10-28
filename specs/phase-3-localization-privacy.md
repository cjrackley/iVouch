# Phase 3 — Localization and Privacy Models

**Why separate:** these models output boxes and masks, not labels. They
need different human-drawn labels (damage masks, plate boxes) and
different metrics (IoU, detection recall) from Phase 2, and they don't
block the core classifier or the backend skeleton.

Two model groups:

- **Damage localization (phone):** heatmap from DINOv3 patch tokens →
  box prompts → EfficientSAM or MobileSAM mask.
- **Privacy blurring (server):** face and license-plate detectors.
  Blurring runs on the server because originals are uploaded for
  authenticity checks (DEVELOPMENT_PLAN §2).

| | |
|---|---|
| Depends on | Phases 0, 1, 2 (`iv_core` patch tokens) |
| Unblocks | Phases 4 (blurring), 6 (masks) |
| Execution | Sequential only — Block 1, phase 2 of 2 (starts automatically after Phase 2; manual stop after this phase) |
| Stack | PyTorch, EfficientSAM / MobileSAM, MediaPipe Face Detector (Python), YOLOX-Nano, ExecuTorch, ONNX |

## Human inputs (gate)

| Input | If missing |
|---|---|
| ~200 incident images with damage-region polygons (eval set) | Report heatmap-only metrics; the mask IoU criterion is un-run, logged in `BLOCKED.md`, and its objective stays open (NEEDS-USER-APPROVAL) — it is not accepted |
| Approved license-plate training/eval dataset | Plate objective (3.5) stays open (NEEDS-USER-APPROVAL); face blurring proceeds |
| Approved face-detection eval images | Evaluate on Phase 0 fixtures only for development; the 3.4 criterion is not accepted until the approved eval set exists, and the gap is logged |

The agent prepares the images to label (`export_for_labeling` from
Phase 1) so the user only has to draw. Un-run criteria above follow
orchestrator §7 — they are not failures and must not consume retry
attempts, but they are not passes either: they keep their objective,
and therefore the phase, incomplete.

## Objectives

### 3.1 Damage heatmap head

Patch-level linear classifier on frozen `patch_tokens` trained with
image-level labels (class-activation style). Produces a 14x14 heatmap
per incident class.

```python
# ml/ivml/localize/heatmap.py
def train_patch_head(patch_store: EmbeddingStore, manifest: pd.DataFrame, cfg: HeadConfig) -> PatchHead: ...
def damage_heatmap(patch_tokens: np.ndarray, incident_id: str, head: PatchHead) -> np.ndarray: ...  # [14, 14] in [0, 1]
def heatmap_to_boxes(heatmap: np.ndarray, image_size: tuple[int, int], threshold: float,
                     max_boxes: int = 3) -> list[Box]: ...
```

**Acceptance criteria**

- [ ] Pointing-game accuracy (heatmap peak inside a ground-truth
  polygon) ≥ 0.7 on the labeled eval set.
- [ ] Box threshold stored in `thresholds.yaml` (`# CALIBRATE: Phase 3`).

### 3.2 On-device segmentation

Bake-off between EfficientSAM (Ti/S) and MobileSAM, prompted with the
boxes from 3.1. Pick the smallest model meeting the criteria; record
the decision.

```python
# ml/ivml/localize/segment.py
def load_segmenter(name: str) -> Segmenter: ...
def segment(img: Image.Image, boxes: list[Box], segmenter: Segmenter) -> list[np.ndarray]: ...
def mask_area_fraction(masks: list[np.ndarray]) -> float: ...
def export_segmenter(segmenter: Segmenter, out_dir: Path) -> dict[str, Path]: ...  # encoder.pte, decoder.pte, + .onnx
```

**Acceptance criteria**

- [ ] Mean IoU ≥ 0.5 vs. human masks (initial target; data-unreachable
  failures follow the Phase 2 evidence-pack rule).
- [ ] Segmenter `.pte` files ≤ 45 MB combined; `iv_core.pte` +
  segmenter ≤ 80 MB total, all under `ARTIFACT_ROOT` and registered.
- [ ] Parity test vectors (image + boxes → expected masks, IoU ≥ 0.95
  vs. reference) published for Kotlin.

### 3.3 Templated rationale

Deterministic text built from model outputs, identical on phone
(Kotlin) and server (Python).

```python
# common/ivcommon/rationale.py
def build_rationale(incident_probs: dict[str, float], severity: str, severity_conf: float,
                    mask_area_fraction: float | None, claim_probs: dict[str, float] | None) -> str: ...
# e.g. "Flood (91%). Water region covers ~46% of the image. Severity: severe (72%)."
```

**Acceptance criteria**

- [ ] `rationale_test_vectors.json` (≥ 30 cases) for Kotlin parity;
  exact string match.

### 3.4 Face detection (server)

MediaPipe Face Detector (Apache 2.0) via its Python package, full-range
model for faces at a distance.

```python
# server/ivserver/privacy/faces.py
def detect_faces(img: Image.Image, min_confidence: float) -> list[Box]: ...
```

**Acceptance criteria**

- [ ] Recall ≥ 0.95 for faces ≥ 20 px on the approved eval set (or
  fixture-only evaluation with the gap logged, per Human inputs).

### 3.5 License-plate detection (server)

Fine-tune YOLOX-Nano (Apache 2.0) on the approved plate dataset. **Do
not use Ultralytics YOLO packages** (AGPL-3.0) unless the user approves
that license (orchestrator §9).

```python
# ml/ivml/privacy/plates.py
def train_plate_detector(dataset: Path, cfg: DetConfig) -> PlateDetector: ...
# server/ivserver/privacy/plates.py
def detect_plates(img: Image.Image, min_confidence: float) -> list[Box]: ...
```

**Acceptance criteria**

- [ ] Recall ≥ 0.90 on the plate eval set; ONNX export registered
  under `ARTIFACT_ROOT`. Training is a checkpointed long job.

### 3.6 Irreversible blurring

```python
# server/ivserver/privacy/blur.py
def blur_regions(img: Image.Image, boxes: list[Box], pad_frac: float = 0.15) -> Image.Image: ...
def make_public_derivatives(img: Image.Image) -> PublicDerivatives: ...  # blurred full image + 256px thumbnail, EXIF stripped
```

**Acceptance criteria**

- [ ] Blur strength scales with box size (pixelate to ≤ 8 blocks across
  the box, then Gaussian), so faces/plates are unrecoverable by
  upscaling.
- [ ] Public derivatives contain no EXIF/GPS (test).

## Agent notes

- SAM 3 (~848M params) is too large for phones; do not use it here.
- EfficientSAM/MobileSAM encoders often use large inputs (1024 px).
  Measure Android latency in Phase 6; if too slow, a smaller input
  size is an acceptable decision-record trade.
- Mask quality matters less than speed. Masks are shown to reviewers
  and used for the rationale, not for automatic decisions.
- All artifacts resolve through `registry/models.yaml` +
  `ARTIFACT_ROOT`; a missing artifact is ENV-BLOCKED with the expected
  path, never a reason to retrain inside an unrelated brief.

## Out of scope

Server pipeline wiring (Phase 4), Android integration (Phase 6).

## Definition of done

All artifacts exported and registered, test vectors and eval reports
published, and every acceptance criterion recorded as passing in
`logs/spec3_log.md` (the boxes above are spec source text and are never
ticked; see `logs/README.md`). Gaps recorded in `BLOCKED.md` keep their
objective — and the phase — open under orchestrator §7. There is no
partial completion.
