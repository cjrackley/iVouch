# Phase 3 — Localization and Privacy Models

**Why this is its own phase:** These models output boxes and masks, not labels. They need different human-drawn labels (damage masks, plate boxes) and different metrics (IoU, detection recall) from Phase 2's classifiers. They don't block the core classifier or the backend skeleton, so they run alongside Phase 4.

Two model groups:
- **Damage localization (phone):** a heatmap from DINOv3 patch tokens → box prompts → EfficientSAM or MobileSAM mask.
- **Privacy blurring (server):** face and license-plate detectors. Blurring runs on the server because originals are uploaded for authenticity checks (DEVELOPMENT_PLAN §2, "Why originals are uploaded").

| | |
|---|---|
| Depends on | Phases 0, 1, 2 (`iv_core` patch tokens) |
| Unblocks | Phases 4 (blurring), 6, 7 (masks) |
| Parallel with | Phases 4, 5 |
| Stack | PyTorch, EfficientSAM / MobileSAM, MediaPipe Face Detector (Python), YOLOX-Nano, ExecuTorch, ONNX |

## Human inputs (gate)

| Input | If missing |
|---|---|
| ~200 incident images with damage-region polygons (eval set) | Report heatmap-only metrics; mark mask IoU criterion `blocked` in `BLOCKED.md` |
| Approved license-plate training/eval dataset | Use face blurring only; plate objective blocked |
| Approved face-detection eval images | Evaluate on Phase 0 fixtures only; log gap |

The agent prepares the images to label (`export_for_labeling` from Phase 1) so the user only has to draw.

## Objectives

### 3.1 Damage heatmap head

Patch-level linear classifier on frozen `patch_tokens` trained with image-level labels (class-activation style). Produces a 14×14 heatmap per incident class.

**Functions**
```python
# ml/ivml/localize/heatmap.py
def train_patch_head(patch_store: EmbeddingStore, manifest: pd.DataFrame, cfg: HeadConfig) -> PatchHead: ...
def damage_heatmap(patch_tokens: np.ndarray, incident_id: str, head: PatchHead) -> np.ndarray: ...  # [14, 14] in [0, 1]
def heatmap_to_boxes(heatmap: np.ndarray, image_size: tuple[int, int], threshold: float,
                     max_boxes: int = 3) -> list[Box]: ...
```

**Acceptance criteria**
- [ ] Pointing-game accuracy (heatmap peak inside a ground-truth polygon) ≥ 0.7 on the labeled eval set.
- [ ] Box threshold stored in `thresholds.yaml`.

### 3.2 On-device segmentation

Bake-off between EfficientSAM (Ti/S) and MobileSAM, prompted with the boxes from 3.1. Pick the smallest model meeting the criteria; record the decision.

**Functions**
```python
# ml/ivml/localize/segment.py
def load_segmenter(name: str) -> Segmenter: ...
def segment(img: Image.Image, boxes: list[Box], segmenter: Segmenter) -> list[np.ndarray]: ...  # binary masks
def mask_area_fraction(masks: list[np.ndarray]) -> float: ...
def export_segmenter(segmenter: Segmenter, out_dir: Path) -> dict[str, Path]: ...  # encoder.pte, decoder.pte, + .onnx
```

**Acceptance criteria**
- [ ] Mean IoU ≥ 0.5 vs. human masks (initial target).
- [ ] Segmenter `.pte` files ≤ 45 MB combined; `iv_core.pte` + segmenter ≤ 80 MB total.
- [ ] Parity test vectors (image + boxes → expected masks, IoU ≥ 0.95 vs. reference) published.

### 3.3 Templated rationale

Deterministic text built from model outputs, identical on phone and server.

**Functions**
```python
# common/ivcommon/rationale.py
def build_rationale(incident_probs: dict[str, float], severity: str, severity_conf: float,
                    mask_area_fraction: float | None, claim_probs: dict[str, float] | None) -> str: ...
# e.g. "Flood (91%). Water region covers ~46% of the image. Severity: severe (72%)."
```

**Acceptance criteria**
- [ ] `rationale_test_vectors.json` (≥ 30 cases) for Kotlin/Swift parity; exact string match.

### 3.4 Face detection (server)

MediaPipe Face Detector (Apache 2.0) via its Python package, using the full-range model for faces at a distance.

**Functions**
```python
# server/ivserver/privacy/faces.py
def detect_faces(img: Image.Image, min_confidence: float) -> list[Box]: ...
```

**Acceptance criteria**
- [ ] Recall ≥ 0.95 for faces ≥ 20 px on the approved eval set.

### 3.5 License-plate detection (server)

Fine-tune YOLOX-Nano (Apache 2.0) on the approved plate dataset. **Do not use Ultralytics YOLO packages** (AGPL-3.0) unless the user approves that license.

**Functions**
```python
# ml/ivml/privacy/plates.py
def train_plate_detector(dataset: Path, cfg: DetConfig) -> PlateDetector: ...
# server/ivserver/privacy/plates.py
def detect_plates(img: Image.Image, min_confidence: float) -> list[Box]: ...
```

**Acceptance criteria**
- [ ] Recall ≥ 0.90 on the plate eval set; ONNX export registered.

### 3.6 Irreversible blurring

**Functions**
```python
# server/ivserver/privacy/blur.py
def blur_regions(img: Image.Image, boxes: list[Box], pad_frac: float = 0.15) -> Image.Image: ...
def make_public_derivatives(img: Image.Image) -> PublicDerivatives: ...  # blurred full image + 256px thumbnail, EXIF stripped
```

**Acceptance criteria**
- [ ] Blur strength scales with box size (e.g. pixelate to ≤ 8 blocks across the box, then Gaussian), so faces/plates are unrecoverable by upscaling.
- [ ] Public derivatives contain no EXIF/GPS (test).

## Agent notes

- SAM 3 (~848M params) is too large for phones; do not use it here.
- EfficientSAM/MobileSAM image encoders use large inputs (often 1024 px). Measure on-device latency in Phases 6/7; if too slow, a smaller input size is an acceptable decision-record trade.
- Mask quality matters less than speed here. Masks are shown to reviewers and used for the rationale, not for automatic decisions.

## Out of scope

Server pipeline wiring (Phase 4), mobile integration (Phases 6–7).

## Definition of done

All artifacts exported, registered, with test vectors and eval reports; gaps recorded in `BLOCKED.md`.
