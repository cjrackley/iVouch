# Phase 0 — Foundations and Contracts

**Why this is its own phase:** Every later phase (Python ML, FastAPI server, Kotlin app, Swift app, web console) must agree on the same schemas, taxonomy, thresholds, preprocessing and repo conventions. Freezing these first lets later phases run in parallel without agents negotiating with each other or waiting on the user.

| | |
|---|---|
| Depends on | nothing |
| Unblocks | all phases |
| Parallel with | — |
| Stack | Python 3.12, uv, ruff, mypy, pytest, Docker Compose (PostgreSQL 16 + PostGIS + pgvector, MinIO) |

## Human inputs (gate)

- None required to start.
- Docker Desktop running on the Windows machine, needed for `python tasks.py up`. If it's missing, the services criteria in 0.1 are blocked; everything else proceeds.
- **Review later (non-blocking):** the content policy, terms and removal-request notice drafts (objective 0.4), and the minimum age (default 18). Agents proceed with the drafts marked `DRAFT`.

## Objectives

### 0.1 Repository layout and tooling

Create the monorepo:

```text
iVouch/
  DEVELOPMENT_PLAN.md
  AGENTS.md               # agent entry point: roles + shared guardrails (locked for builders)
  agents/                 # orchestrator.md, builder.md, models.yaml (locked for builders)
  logs/                   # specN_log.md, append-only
  specs/                  # phase specs (this folder)
  contracts/              # openapi.yaml, schemas/, examples/, preprocessing.md
  config/                 # taxonomy.yaml, thresholds.yaml, policy.yaml, label_maps/
  common/ivcommon/        # shared Python: config loaders, schema models, metrics
  ml/ivml/                # data pipeline, training, export, eval (Phases 1–3)
  server/ivserver/        # FastAPI app, worker, authenticity (Phases 4–5, 8)
  android/                # Kotlin app (Phase 6)
  ios/                    # Swift app (Phase 7)
  eval/                   # harness + reports/
  registry/               # datasets.yaml, models.yaml
  fixtures/               # small synthetic test images (generated, safe to commit)
  infra/                  # docker-compose.yml, CI
  docs/                   # CONTENT_POLICY.md, TERMS.md, REMOVAL_REQUESTS.md, decisions/, HUMAN_INPUTS.md, BLOCKED.md
```

Task runner: `tasks.py` at the repo root, Python standard library only, with targets `python tasks.py setup`, `python tasks.py check` (ruff + mypy + pytest across Python packages), `python tasks.py up` / `down` (Docker services), `python tasks.py fixtures`. It must work in Windows PowerShell (the development machine) and on the Linux CI runner. No bash scripts or Makefiles.

**Acceptance criteria**
- [ ] `python tasks.py setup` then `python tasks.py check` passes on a clean clone, on Windows and in CI.
- [ ] `python tasks.py up` starts PostgreSQL (with `postgis` and `vector` extensions available) and MinIO; a healthcheck script exits 0.
- [ ] CI workflow (`infra/ci/` or `.github/workflows/`) runs `python tasks.py check` on push.
- [ ] `.gitignore` excludes `data/`, model weights, `.env`; `.env.example` lists every env var used.

### 0.2 API and data contracts

Write `contracts/openapi.yaml` for the v1 endpoints (see DEVELOPMENT_PLAN §7) and JSON Schemas in `contracts/schemas/`:

| Schema | Purpose |
|---|---|
| `account` | `account_id`, `email`, `email_verified`, `roles` (`user` \| `reviewer` \| `safety_officer` \| `admin`), `status` (`active` \| `suspended` \| `deleted`), `policy_version_accepted`, `age_confirmed_at`, `created_at` (no date of birth) |
| `auth_tokens` | `access_token` (JWT, short-lived), `refresh_token`, `expires_in` |
| `capture_metadata` | `captured_at`, `capture_source` (`in_app_camera` \| `gallery` \| `web_upload`), `device_model`, `os_version`, `app_version`, `install_id` (device identity for attestation; the account comes from the auth token) |
| `location` | `lat`, `lng`, `accuracy_m`, `source` (`exif-gps` \| `device-gps` \| `manual-pin` \| `claim-text` \| `none`), `consented` |
| `device_result` | on-device outputs + `model_version` (incident probs, severity probs, policy scores per category, boxes, mask area fraction, rationale) |
| `takedown_request` | requester name + email, electronic signature (typed full name + timestamp), content locator (report URL/id or description), good-faith statement (bool, required), status, `received_at`, `deadline_at` (= received + 48 h) |
| `authenticity_signals` / `authenticity_result` | see Phase 5 |
| `report` | full report as returned by `GET /v1/reports/{id}` |
| `incident_feature` | GeoJSON feature for `GET /v1/incidents` |

Every schema has a `schema_version` field. Mirror the schemas as Pydantic v2 models in `ivcommon.schemas`.

**Functions**
```python
# common/ivcommon/schemas.py
class Account(BaseModel): ...
class AuthTokens(BaseModel): ...
class TakedownRequest(BaseModel): ...
class CaptureMetadata(BaseModel): ...
class Location(BaseModel): ...
class DeviceResult(BaseModel): ...
class AuthenticityResult(BaseModel): ...
class Report(BaseModel): ...
def validate_against_schema(payload: dict, schema_name: str) -> None: ...  # raises on failure
```

**Acceptance criteria**
- [ ] `openapi.yaml` passes `openapi-spec-validator`.
- [ ] Each schema has ≥ 1 valid and ≥ 1 invalid example in `contracts/examples/`; a pytest test validates all of them.
- [ ] Pydantic models round-trip every valid example with no field loss.

### 0.3 Shared configuration

- `config/taxonomy.yaml`: incident ids `car_crash`, `fire`, `flood`, `storm_damage`, `earthquake_damage`, `none`; display names; severity levels `minor`, `moderate`, `severe`.
- `config/thresholds.yaml`: every numeric threshold in the system, each with a comment naming the phase that calibrates it (`# CALIBRATE: Phase 2`).
- `config/policy.yaml`: policy version, terms version, `min_age` (default 18; must be ≥ 13), categories (`violence_gore`, `nudity_sexual`), user-facing message per category, repeat-violation suspension count.

**Functions**
```python
# common/ivcommon/config.py
def load_taxonomy(path: Path | None = None) -> Taxonomy: ...
def load_thresholds(path: Path | None = None) -> Thresholds: ...
def load_policy(path: Path | None = None) -> Policy: ...
```

**Acceptance criteria**
- [ ] Loaders validate files and fail with a clear message on unknown keys or missing values.
- [ ] Unit tests cover each loader.

### 0.4 Content policy, terms and removal-request notice (user-facing)

Write three plain-language documents, each marked `DRAFT` until the user approves it:

`docs/CONTENT_POLICY.md`
- **Not allowed:** anything showing real violence (fights, assaults, shootings, weapons being used against people or animals); gore (blood, wounds, injured or dead people or animals); nudity or sexual content of any kind.
- **Illegal content:** content that sexually exploits children is illegal and is reported to the National Center for Missing & Exploited Children (NCMEC).
- **Guidance:** photograph the scene, vehicles, buildings, water, fire or debris, not injured people. "Not for emergencies: call your local emergency number first."
- What happens on violation: the app blocks the upload and explains why; the server re-checks and discards violating images; repeated violations suspend the account.

`docs/TERMS.md`
- Accounts required; minimum age (`min_age`); one person per account; account deletion and what is kept under legal obligations.

`docs/REMOVAL_REQUESTS.md` (TAKE IT DOWN Act notice)
- How anyone (no account needed) can request removal of an intimate image shared without consent: what to include (name, contact, signature, where the content is, good-faith statement), the 48-hour removal commitment, and that identical copies are removed too.

Serve all three via `GET /v1/policy` (Phase 4) and bundle copies in each app as an offline fallback.

**Acceptance criteria**
- [ ] Each document and `config/policy.yaml` share the same version strings; a test checks they match.
- [ ] `REMOVAL_REQUESTS.md` lists every field required by the `takedown_request` schema.

### 0.5 Evaluation harness

**Functions**
```python
# common/ivcommon/metrics.py
def macro_f1(y_true, y_pred, labels) -> float: ...
def per_class_f1(y_true, y_pred, labels) -> dict[str, float]: ...
def quadratic_weighted_kappa(y_true, y_pred) -> float: ...
def expected_calibration_error(probs, y_true, n_bins: int = 15) -> float: ...
def mask_iou(pred: np.ndarray, gt: np.ndarray) -> float: ...
def recall_at_k(ranked_ids: list[list[str]], relevant: list[set[str]], k: int) -> float: ...
def roc_auc(scores, y_true) -> float: ...
def false_accusation_rate(labels_pred: list[str], truly_real: list[bool]) -> float: ...
def latency_percentiles(samples_ms: list[float]) -> dict[str, float]: ...  # p50, p95, p99

# eval/run.py
def run_eval(task: str, model_version: str, dataset_version: str) -> EvalReport: ...
# writes eval/reports/<task>/<model_version>__<dataset_version>.{json,md}
```

**Acceptance criteria**
- [ ] Each metric has a unit test with a hand-computed expected value.
- [ ] `python -m eval.run --task dummy` writes both report files.

### 0.6 Dataset and model registries

`registry/datasets.yaml` and `registry/models.yaml`: name, version, source URL, **license**, intended use (`research` / `commercial-approved`), sha256 of artifacts, storage path, created_at, parent versions. Weights and data live outside git (local path or MinIO bucket).

**Functions**
```python
# common/ivcommon/registry.py
def register_dataset(name: str, version: str, path: Path, license: str, source: str, parents: list[str] = []) -> None: ...
def register_model(name: str, version: str, artifacts: dict[str, Path], dataset_version: str, embedding_version: str | None, license: str) -> None: ...
def resolve(name: str, version: str = "latest") -> RegistryEntry: ...
```

**Acceptance criteria**
- [ ] Registering refuses entries with an empty `license`.
- [ ] Checksums are verified on `resolve`.

### 0.7 Agent working conventions

Create:
- `docs/decisions/0000-template.md`: lightweight decision record (context, options, decision, reversibility). Agents record reversible decisions here instead of stopping to ask, except the user-only decisions in `agents/orchestrator.md` §9 (e.g. lowering any target).
- `docs/HUMAN_INPUTS.md`: checklist of every external input from DEVELOPMENT_PLAN §8.2 with status (`pending` / `provided` / `waived`).
- `docs/BLOCKED.md`: where an agent records anything it could not finish because a human input is missing, plus the mock it used instead.

**Acceptance criteria**
- [ ] All three files exist and `HUMAN_INPUTS.md` lists every gate from every phase spec.

### 0.8 Synthetic fixtures

`python tasks.py fixtures` generates small synthetic images with Pillow (solid scenes, text, simple shapes) and variants: no EXIF, EXIF with GPS, rotated EXIF orientation, re-encoded JPEG at quality 50, HEIC copy, PNG. These are for unit tests only (not model quality).

**Acceptance criteria**
- [ ] Fixtures are deterministic (same bytes for the same seed).
- [ ] Fixtures are safe to commit (< 5 MB total).

### 0.9 CSAM hash-matching interface

Shared by Phase 1 (screening policy data before ingest) and Phase 4 (screening every upload). Real providers are implemented in Phase 4.

**Functions**
```python
# common/ivcommon/hashmatch.py
class HashMatchResult(BaseModel):
    matched: bool
    provider: str
    match_id: str | None      # provider reference, never the hash list itself
class HashMatcher(Protocol):
    def check(self, image_bytes: bytes) -> HashMatchResult: ...
class MockHashMatcher:        # "matches" only images whose sha256 is listed in a test config of benign fixtures
    ...
def get_hash_matcher() -> HashMatcher: ...  # from env; MockHashMatcher allowed only when ENV in {dev, test}
```

**Acceptance criteria**
- [ ] `get_hash_matcher()` raises at startup if `ENV` is not `dev`/`test` and no real provider is configured (test).
- [ ] Mock match list contains only Phase 0 synthetic fixtures.

## Agent notes

- Contracts are the source of truth. A later phase that needs a contract change must update the schema, bump `schema_version`, update examples, and record a decision.
- Never commit secrets. All secrets come from env vars listed in `.env.example`.
- Keep `thresholds.yaml` as the only place numbers live. No magic numbers in code.
- Never collect, download, generate or open material that could be CSAM, in this or any phase (DEVELOPMENT_PLAN §8.3).

## Out of scope

Any model training, endpoints beyond stubs, mobile code.

## Definition of done

All acceptance boxes checked, `python tasks.py check` green on Windows and in CI, `docs/HUMAN_INPUTS.md` complete.
