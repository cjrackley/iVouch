# Phase 2 — Core Image Models (Backbone + Heads + Export)

**Why separate:** the shared backbone and its heads decide incident
type, severity and policy violations on both the phone and the server.
The phase needs GPU time and produces versioned artifacts (PyTorch
reference, ExecuTorch `.pte` for Android, ONNX for the server) plus
test vectors the Android and server phases test against.

| | |
|---|---|
| Depends on | Phases 0, 1 |
| Unblocks | Phases 3, 4 (real models), 5, 6 |
| Execution | Sequential only — Block 1, phase 1 of 2 (Phase 3 follows automatically in the same block) |
| Stack | PyTorch, DINOv3 (ViT-S/16 distilled), scikit-learn, ExecuTorch (XNNPACK backend), ONNX + ONNX Runtime |

## Human inputs (gate)

| Input | If missing |
|---|---|
| DINOv3 license accepted + download token (checked via `python tasks.py env-check --names HF_TOKEN`, never by reading `.env`) | Objectives needing the backbone cannot start (NEEDS-USER-APPROVAL); 2.5 claim-text can proceed |
| GPU access (one modern GPU) | ENV-BLOCKED for full-corpus runs; a CPU subsample run may proceed only if the brief says so, logged in `BLOCKED.md` |
| Phase 1 crash-severity labels and policy sets | Train with what exists; mark gaps (see 2.3, 2.4). Untrained categories use the `unavailable` path, never a guessed threshold |

Embedding extraction and training are long jobs: resumable, with
checkpoints under `work/checkpoints/` (see Phase 1's long-job rule).

## Model I/O contract

Write `contracts/preprocessing.md` (the brief lists it in `new_files`) with:

1. Apply EXIF orientation.
2. Convert to RGB (drop alpha), decode HEIC via pillow-heif on the server.
3. Resize shorter side to 224 (bilinear, antialias), center-crop 224x224.
4. Normalize with the mean/std from the DINOv3 checkpoint's config
   (verify; do not assume).

Exported graph `iv_core`:

| Output | Shape | Notes |
|---|---|---|
| `embedding` | [1, D] | CLS token, L2-normalized (D = 384 for ViT-S; verify against the checkpoint config — on mismatch record a decision and correct this contract via the unlock procedure) |
| `patch_tokens` | [1, 196, D] | for the Phase 3 damage heatmap |
| `incident_probs` | [1, 6] | sigmoid, multi-label, order = `taxonomy.yaml` |
| `severity_probs` | [1, 3] | softmax, `minor/moderate/severe` |
| `policy_scores` | [1, 2] | sigmoid per category, order = `violence_gore`, `nudity_sexual` |

## Objectives

### 2.1 Embedding extraction

```python
# ml/ivml/models/backbone.py
def load_backbone(name: str = "dinov3_vits16", device: str = "cuda") -> nn.Module: ...
def preprocess(img: Image.Image) -> torch.Tensor: ...  # contracts/preprocessing.md exactly
def embed_images(manifest: pd.DataFrame, backbone: nn.Module, out_dir: Path,
                 batch_size: int = 128, store_patch_tokens: bool = False) -> EmbeddingStore: ...
```

**Acceptance criteria**

- [ ] Embeddings cached under `ARTIFACT_ROOT` with `embedding_version`
  = backbone name + checkpoint hash + preprocessing version.
- [ ] Re-running on cached data is a no-op (resume from checkpoint).
- [ ] `preprocess` matches golden outputs for every Phase 0 fixture
  (max abs diff ≤ 1e-5).

### 2.2 Incident head (multi-label)

Logistic regression or a 1-hidden-layer MLP on frozen embeddings, one
sigmoid per class, per-class temperature scaling on validation.

```python
# ml/ivml/models/heads.py
def train_incident_head(emb: EmbeddingStore, manifest: pd.DataFrame, cfg: HeadConfig) -> IncidentHead: ...
def calibrate(head: nn.Module, val_logits: np.ndarray, val_labels: np.ndarray) -> Calibrator: ...
```

**Acceptance criteria** (targets; lowering any needs user approval —
but see the evidence-pack rule in Agent notes)

- [ ] Macro-F1 ≥ 0.75 on the test split; per-class F1 reported.
- [ ] Expected calibration error ≤ 0.05 after calibration.
- [ ] `none` class precision ≥ 0.90.
- [ ] Per-class decision thresholds written to `thresholds.yaml` under
  `# CALIBRATE: Phase 2` keys named in the brief.

### 2.3 Severity head

Ordinal 3-class head on the embedding (+ incident probabilities).
Trained on CrisisMMD severity and Phase 1 crash labels.

**Acceptance criteria**

- [ ] Quadratic-weighted kappa ≥ 0.5 overall on test; reported per
  incident type.
- [ ] If crash-severity labels are missing or < 200, `thresholds.yaml`
  marks `car_crash` severity `low_confidence: true` so routing always
  sends crashes to review.

### 2.4 Content-policy head

Multi-label head on the embedding, trained on the Phase 1 policy
manifest.

**Acceptance criteria**

- [ ] Recall ≥ 0.95 per category on policy-violating test images at
  the chosen thresholds.
- [ ] Combined false-positive rate ≤ 5% on ordinary incident images,
  reported separately for car crashes and people-in-ordinary-clothing
  hard negatives.
- [ ] Per-category thresholds written to `thresholds.yaml`
  (`policy.block_threshold.violence_gore`,
  `policy.block_threshold.nudity_sexual`).
- [ ] If a category had no training data, its threshold is set to
  `unavailable`: the phone does not block on it and the server routes
  every upload to review for that category until trained (decision
  record). Never substitute a default number for `unavailable`.

### 2.5 Claim-text classifier

TF-IDF (word + char n-grams, capped vocabulary) + logistic regression,
exported as JSON (vocabulary, idf, coefficients, intercepts) so Python
and Kotlin implement the same math. (Android is the only v1 client;
the JSON format stays platform-neutral.)

```python
# ml/ivml/text/claim.py
def train_claim_classifier(text_manifest: pd.DataFrame, cfg: TextConfig) -> ClaimModel: ...
def export_claim_model(model: ClaimModel, out: Path) -> Path: ...  # claim_model.json
def predict_claim(model_json: dict, text: str) -> dict[str, float]: ...
```

**Acceptance criteria**

- [ ] `claim_model.json` ≤ 5 MB, stored under `ARTIFACT_ROOT` and
  registered.
- [ ] Macro-F1 reported on the text test split.
- [ ] `text_test_vectors.json` (≥ 50 strings + expected probabilities)
  produced for Kotlin parity.

### 2.6 Export for phone and server

```python
# ml/ivml/export/core.py
def build_core_module(backbone, incident_head, severity_head, policy_head) -> nn.Module: ...
def export_executorch(module: nn.Module, out: Path, quantize: str = "int8") -> Path: ...   # iv_core.pte
def export_onnx(module: nn.Module, out: Path) -> Path: ...                                  # iv_core.onnx
def make_test_vectors(module: nn.Module, images: list[Path], out: Path) -> Path: ...
```

**Acceptance criteria**

- [ ] `iv_core.pte` ≤ 30 MB under `ARTIFACT_ROOT`; registry entry with
  sha256 written. Artifacts are never committed (orchestrator's 5 MB
  diff gate).
- [ ] Quantized `.pte` vs. fp32 reference: incident top-1 agreement
  ≥ 99%, max abs prob diff ≤ 0.02 on ≥ 95% of test images.
- [ ] ONNX (fp32) vs. reference: max abs diff ≤ 1e-3.
- [ ] `test_vectors/` contains ≥ 30 images (fixtures or license-cleared
  data) with expected outputs for every output tensor. Test vectors
  are small and committed (prefer Phase 0 fixtures as the images so the
  diff stays small); the model files they exercise are resolved
  through the registry.
- [ ] `MODEL_CARD.md` (data, metrics, limits, license) and registry
  entry written.

## Agent notes

- The same `preprocess` is reimplemented in Kotlin (Phase 6). Keep it
  simple and documented; mismatched resizing is the most common cause
  of phone/server disagreement.
- Freeze the backbone. Fine-tuning DINOv3 is out of scope for v1.
- ExecuTorch export: use `torch.export` + XNNPACK partitioner; check
  current ExecuTorch docs for the exact API, which changes between
  releases. If export needs a network fetch (docs/packages), the brief
  must list those hosts in `network_allowed`.
- DINOv3 uses its own license (not Apache 2.0). Record it in the
  registry.
- Policy-set images must never appear in eval reports, sample sheets
  or test vectors. Policy test vectors use synthetic fixtures and
  record only expected scores.
- **Metric evidence packs:** if a 2.2–2.4 target fails and Phase 1's
  class-count report shows the data cannot support it (e.g. < 500
  training images in a class, missing category set), the builder's
  entry must attach the eval report + counts. The orchestrator then
  uses the §3 data-unreachable exit (one attempt, user evidence pack)
  instead of a second code attempt. Targets are never lowered by agents.

## Out of scope

Damage heatmap/segmentation (Phase 3), face/plate detection (Phase 3),
forensic detection (Phase 5).

## Definition of done

Artifacts registered under `ARTIFACT_ROOT`, test vectors published,
eval reports in `eval/reports/`, thresholds written, and every
acceptance criterion recorded as passing in `logs/spec2_log.md` (the
boxes above are spec source text and are never ticked; see
`logs/README.md`). Gaps are recorded in `BLOCKED.md` and keep their
objective — and the phase — open under orchestrator §7. A category
marked `unavailable` or `low_confidence` is a routing state, not a
passed criterion. There is no partial completion.
