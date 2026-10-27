# Phase 2 — Core Image Models (Backbone + Heads + Export)

**Why this is its own phase:** The shared backbone and its heads decide incident type, severity and policy violations on both the phone and the server. The phase needs GPU time and produces versioned artifacts (PyTorch reference, ExecuTorch `.pte` for phones, ONNX for the server) plus test vectors that the Android, iOS and server phases test against. Nothing downstream can be verified until these exist.

| | |
|---|---|
| Depends on | Phases 0, 1 |
| Unblocks | Phases 3, 4 (real models), 5, 6, 7 |
| Parallel with | Phase 4 (using stubs) |
| Stack | PyTorch, DINOv3 (ViT-S/16 distilled), scikit-learn, ExecuTorch (XNNPACK backend), ONNX + ONNX Runtime |

## Human inputs (gate)

| Input | If missing |
|---|---|
| Accept the DINOv3 license and provide a download token (`HF_TOKEN` or Meta download URL) | Phase cannot start |
| GPU access (one modern GPU is enough for embeddings + linear heads) | Run on CPU over a subsample; log in `BLOCKED.md` |
| Phase 1 crash-severity labels and policy sets (violence/gore, adult nudity/sexual) | Train with what exists; mark gaps (see 2.3, 2.4) |

## Model I/O contract

Write `contracts/preprocessing.md` with:
1. Apply EXIF orientation.
2. Convert to RGB (drop alpha), decode HEIC via pillow-heif on the server.
3. Resize shorter side to 224 (bilinear, antialias), center-crop 224×224.
4. Normalize with the mean/std from the DINOv3 checkpoint's config (verify; do not assume).

Exported graph `iv_core`:

| Output | Shape | Notes |
|---|---|---|
| `embedding` | [1, D] | CLS token, L2-normalized (D = backbone width, 384 for ViT-S) |
| `patch_tokens` | [1, 196, D] | for the Phase 3 damage heatmap |
| `incident_probs` | [1, 6] | sigmoid, multi-label, order = `taxonomy.yaml` |
| `severity_probs` | [1, 3] | softmax, `minor/moderate/severe` |
| `policy_scores` | [1, 2] | sigmoid per category, order = `violence_gore`, `nudity_sexual` (from `config/policy.yaml`) |

## Objectives

### 2.1 Embedding extraction

**Functions**
```python
# ml/ivml/models/backbone.py
def load_backbone(name: str = "dinov3_vits16", device: str = "cuda") -> nn.Module: ...
def preprocess(img: Image.Image) -> torch.Tensor: ...  # implements contracts/preprocessing.md exactly
def embed_images(manifest: pd.DataFrame, backbone: nn.Module, batch_size: int = 128,
                 out_dir: Path, store_patch_tokens: bool = False) -> EmbeddingStore: ...
```

**Acceptance criteria**
- [ ] Embeddings cached with `embedding_version` = backbone name + checkpoint hash + preprocessing version.
- [ ] Re-running on cached data is a no-op.
- [ ] `preprocess` matches golden outputs for every Phase 0 fixture (max abs diff ≤ 1e-5).

### 2.2 Incident head (multi-label)

Logistic regression or a 1-hidden-layer MLP on frozen embeddings, one sigmoid per class, with per-class temperature scaling on the validation split.

**Functions**
```python
# ml/ivml/models/heads.py
def train_incident_head(emb: EmbeddingStore, manifest: pd.DataFrame, cfg: HeadConfig) -> IncidentHead: ...
def calibrate(head: nn.Module, val_logits: np.ndarray, val_labels: np.ndarray) -> Calibrator: ...
```

**Acceptance criteria** (initial targets; lowering any of them needs the user's approval)
- [ ] Macro-F1 ≥ 0.75 on the test split; per-class F1 reported.
- [ ] Expected calibration error ≤ 0.05 after calibration.
- [ ] `none` class precision ≥ 0.90 (so non-incidents are filtered cheaply).
- [ ] Per-class decision thresholds written to `thresholds.yaml`.

### 2.3 Severity head

Ordinal 3-class head on the embedding (+ incident probabilities as extra inputs). Trained on CrisisMMD severity and Phase 1 crash labels.

**Acceptance criteria**
- [ ] Quadratic-weighted kappa ≥ 0.5 overall on test; reported per incident type.
- [ ] If crash-severity labels are missing or < 200, `thresholds.yaml` marks `car_crash` severity as `low_confidence: true` so routing always sends crashes to review.

### 2.4 Content-policy head

Multi-label head on the embedding (one sigmoid per category: `violence_gore`, `nudity_sexual`), trained on the Phase 1 policy manifest.

**Acceptance criteria**
- [ ] Recall ≥ 0.95 per category on policy-violating test images at the chosen thresholds.
- [ ] Combined false-positive rate ≤ 5% on ordinary incident images, reported separately for car crashes and for people-in-ordinary-clothing hard negatives.
- [ ] Per-category thresholds written to `thresholds.yaml` (`policy.block_threshold.violence_gore`, `policy.block_threshold.nudity_sexual`).
- [ ] If a category had no training data, its threshold is set to `unavailable`, the phone does not block on it, and the server routes every upload to review for that category until it is trained (decision record).

### 2.5 Claim-text classifier

Small, portable model mapping optional claim text to incident ids: TF-IDF (word + char n-grams, capped vocabulary) + logistic regression, exported as JSON (vocabulary, idf, coefficients, intercepts) so Python, Kotlin and Swift implement the same math.

**Functions**
```python
# ml/ivml/text/claim.py
def train_claim_classifier(text_manifest: pd.DataFrame, cfg: TextConfig) -> ClaimModel: ...
def export_claim_model(model: ClaimModel, out: Path) -> Path: ...  # claim_model.json
def predict_claim(model_json: dict, text: str) -> dict[str, float]: ...  # reference implementation
```

**Acceptance criteria**
- [ ] `claim_model.json` ≤ 5 MB.
- [ ] Macro-F1 reported on the text test split.
- [ ] `text_test_vectors.json` (≥ 50 strings + expected probabilities) produced for Kotlin/Swift parity.

### 2.6 Export for phone and server

**Functions**
```python
# ml/ivml/export/core.py
def build_core_module(backbone, incident_head, severity_head, policy_head) -> nn.Module: ...
def export_executorch(module: nn.Module, out: Path, quantize: str = "int8") -> Path: ...   # iv_core.pte
def export_onnx(module: nn.Module, out: Path) -> Path: ...                                  # iv_core.onnx
def make_test_vectors(module: nn.Module, images: list[Path], out: Path) -> Path: ...        # inputs + expected outputs
```

**Acceptance criteria**
- [ ] `iv_core.pte` ≤ 30 MB.
- [ ] Quantized `.pte` vs. fp32 reference on the test split: incident top-1 agreement ≥ 99%, max abs prob diff ≤ 0.02 on ≥ 95% of images.
- [ ] ONNX (fp32) vs. reference: max abs diff ≤ 1e-3.
- [ ] `test_vectors/` contains ≥ 30 images (from fixtures or license-cleared data) with expected outputs for every output tensor.
- [ ] `MODEL_CARD.md` (data, metrics, limits, license) and registry entry written.

## Agent notes

- The same `preprocess` must be reimplemented in Kotlin and Swift. Keep it simple and documented, because mismatched resizing is the most common cause of phone/server disagreement.
- Freeze the backbone. Fine-tuning DINOv3 is out of scope for v1; linear heads on frozen features are the point.
- ExecuTorch export: use `torch.export` + XNNPACK partitioner; check current ExecuTorch docs for the exact API, which changes between releases.
- DINOv3 uses its own license (not Apache 2.0). Record it in the model registry.
- Policy-set images must never appear in eval reports, sample sheets or test vectors. Policy test vectors use synthetic fixtures and record only expected scores.

## Out of scope

Damage heatmap and segmentation (Phase 3), face/plate detection (Phase 3), forensic detection (Phase 5).

## Definition of done

Artifacts registered, test vectors published, eval reports in `eval/reports/`, thresholds written.
