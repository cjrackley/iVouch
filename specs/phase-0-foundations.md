# Phase 0 — Foundations and Contracts

**Why separate:** every later phase (Python ML, FastAPI server, Kotlin
Android app, web console) must agree on the same schemas, taxonomy,
thresholds, preprocessing and repo conventions. Freezing these first
lets later phases be built one at a time without renegotiating them.

| | |
|---|---|
| Depends on | nothing |
| Unblocks | all phases |
| Execution | Sequential only — Block 0, phase 1 of 2 (runs first; Phase 1 follows automatically in the same block) |
| Stack | Python 3.12, uv, ruff, mypy, pytest, Docker Compose (PostgreSQL 16 + PostGIS + pgvector, MinIO) |

## Human inputs (gate)

- None required to start.
- Docker Desktop running, needed for `python tasks.py up`. If missing,
  services criteria in 0.1 are **ENV-BLOCKED** (orchestrator §7);
  everything else proceeds.
- **Review later (non-blocking):** content policy, terms and
  removal-request drafts (0.4), minimum age (default 18). Drafts are
  marked `DRAFT`.

## Agent dispatch note

Phase 0 uses the **bootstrap exception** (orchestrator §5): briefs that
create `contracts/**`, `config/**`, CI files, `tasks.py`, `.env.example`,
`.gitattributes`, the 0.4 policy
documents, the 0.7 `docs/` files, or the 0.7 `logs/specN_log.md` files
list them in `allowed_paths` (logs via `new_files`, never overwriting a
log that has entries); they are not locked for those briefs. From
Phase 1 on they are locked normally. The orchestrator creates skeleton
`docs/HUMAN_INPUTS.md` and `docs/BLOCKED.md` at phase start
(orchestrator §1 step 0) so blockers can be recorded from the first
brief; objective 0.7 completes their contents.

## Objectives

### 0.1 Repository layout and tooling

Create the monorepo:

```text
iVouch/
  DEVELOPMENT_PLAN.md
  AGENTS.md               # roles + guardrails + Muse tool mapping (locked)
  agents/                 # orchestrator.md, builder.md, models.yaml (locked)
  logs/                   # specN_log.md, append-only, END-OF-LOG sentinel
  specs/                  # phase specs
  contracts/              # openapi.yaml, schemas/, examples/, preprocessing.md
  config/                 # taxonomy.yaml, thresholds.yaml, policy.yaml, label_maps/
  common/ivcommon/        # shared Python: config loaders, schemas, metrics
  ml/ivml/                # data, training, export, eval (Phases 1-3)
  server/ivserver/        # FastAPI app, worker, authenticity (Phases 4, 5, 7)
  android/                # Kotlin app (Phase 6)
  eval/                   # harness + reports/
  registry/               # datasets.yaml, models.yaml
  fixtures/               # small synthetic test images (safe to commit)
  infra/                  # docker-compose.yml, Dockerfiles
  .github/workflows/      # CI
  pyproject.toml + uv.lock  # Python workspace root covering common/ml/server/eval
  work/checkpoints/       # resumable long-job checkpoints (ignored by git)
  docs/                   # CONTENT_POLICY.md, TERMS.md, REMOVAL_REQUESTS.md,
                          # decisions/, HUMAN_INPUTS.md, BLOCKED.md
```

Data and model artifacts live outside git: datasets under `data/`,
artifacts under `ARTIFACT_ROOT` (default `data/artifacts/`). Both are
git-ignored; `registry/*.yaml` records their versions and sha256 so any
session can find and verify them.

Task runner: `tasks.py`, Python standard library only, targets:

- `python tasks.py setup`
- `python tasks.py check` — ruff + mypy + pytest across Python packages.
- `python tasks.py up` / `down` — Docker services.
- `python tasks.py fixtures`
- `python tasks.py env-check --names HF_TOKEN ...` — prints only
  `present`/`missing` per name. This is the **only** way agents may
  check credentials; nobody reads `.env` directly.
- `python tasks.py run` — local server + worker for end-to-end tests.
  Not a Phase 0 deliverable: the Phase 4 brief that first needs it
  adds the target via the orchestrator §5.2 unlock procedure, with the
  reason recorded. Until then `run` may print "not yet implemented".

All targets work in Windows PowerShell and on the Linux CI runner. No
bash scripts or Makefiles. The runner creates `work/checkpoints/` and
prints `ARTIFACT_ROOT` on `setup`. `setup` installs pinned dev
dependencies (uv or pip from the committed lock/requirements) so `check`
passes on a clean clone.

**Acceptance criteria**

- [ ] `python tasks.py setup` then `python tasks.py check` passes on a
  clean clone on Windows. (CI confirms the same on Linux whenever the
  user pushes; CI is recorded, not gating — orchestrator §6.)
- [ ] `python tasks.py up` starts PostgreSQL (with `postgis` and
  `vector` extensions) and MinIO; the healthcheck
  `infra/healthcheck.py` (created by the 0.1 brief, stdlib + psycopg
  or httpx as pinned) exits 0 when both answer. If Docker is absent
  this box is ENV-BLOCKED, not failed. No stock image ships both
  extensions; the brief may add `infra/Dockerfile.postgres` (pin the
  base, e.g. `postgres:16`, plus PostGIS/pgvector versions, license
  recorded) or a chosen third-party image with a decision record.
  Container-registry hosts go in the brief's `network_allowed`.
- [ ] CI workflow (`.github/workflows/check.yml`, `ubuntu-latest`,
  Python 3.12, uv, `python tasks.py check` on push; no Docker services
  in CI for Phase 0 — services are tested locally) runs the check.
  Later phases add jobs (e.g. Android in Phase 6) via the §5.2 unlock
  procedure.
- [ ] `.gitignore` excludes `data/`, `work/`, model weights, `.env`;
  `.env.example` lists every env var used, including `ARTIFACT_ROOT`,
  `ENV`, `ORIGINALS_KEY`, `QUARANTINE_KEY`.
- [ ] `.gitattributes` pins LF (`* text=auto eol=lf`, `*.md text
  eol=lf`) so the log sentinel stays an exact match on Windows;
  `.gitignore` itself is user-owned and verified, never edited by a
  brief — a gap in it is reported to the user, not fixed.
- [ ] `env-check` prints no secret values (test greps its output).

### 0.2 API and data contracts

Write `contracts/openapi.yaml` for the v1 endpoints
(DEVELOPMENT_PLAN §7) and JSON Schemas in `contracts/schemas/`:

| Schema | Purpose |
|---|---|
| `account` | `account_id`, `email`, `email_verified`, `roles` (`user` \| `reviewer` \| `safety_officer` \| `admin`), `status`, `policy_version_accepted`, `age_confirmed_at`, `created_at` (no date of birth) |
| `auth_tokens` | `access_token` (JWT), `refresh_token`, `expires_in` |
| `capture_metadata` | `captured_at`, `capture_source` (`in_app_camera` \| `gallery` \| `web_upload`), `device_model`, `os_version`, `app_version`, `install_id` (the account comes from the auth token) |
| `location` | `lat`, `lng`, `accuracy_m`, `source` (`exif-gps` \| `device-gps` \| `manual-pin` \| `claim-text` \| `none`), `consented` |
| `device_result` | on-device outputs + `model_version` (incident/severity/policy scores, boxes, mask fraction, rationale) |
| `takedown_request` | requester name + email, electronic signature, content locator, good-faith statement (required), status, `received_at`, `deadline_at` (= received + 48 h) |
| `authenticity_signals` / `authenticity_result` | shapes defined here; values and fusion rules are Phase 5 |
| `report` | full report as returned by `GET /v1/reports/{id}` |
| `incident_feature` | GeoJSON feature for `GET /v1/incidents` |

Every schema has a `schema_version` field. Mirror the schemas as
Pydantic v2 models in `ivcommon.schemas`. Contracts stay
platform-neutral (nothing Android-specific) so a future client needs no
contract break.

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
def validate_against_schema(payload: dict, schema_name: str) -> None: ...
```

**Acceptance criteria**

- [ ] `openapi.yaml` passes `openapi-spec-validator`.
- [ ] Each schema has ≥ 1 valid and ≥ 1 invalid example in
  `contracts/examples/`; a pytest test validates all of them.
- [ ] Pydantic models round-trip every valid example with no field loss.

### 0.3 Shared configuration

- `config/taxonomy.yaml`: incident ids `car_crash`, `fire`, `flood`,
  `storm_damage`, `earthquake_damage`, `none`; severity levels
  `minor`, `moderate`, `severe`.
- `config/thresholds.yaml`: every **calibrated** numeric threshold,
  each with a comment naming the phase that calibrates it
  (`# CALIBRATE: Phase 2`). Only briefs naming those keys may set them.
- `config/policy.yaml`: policy/terms versions, `min_age` (default 18,
  ≥ 13), categories (`violence_gore`, `nudity_sexual`), user-facing
  message per category, repeat-violation suspension count, and fixed
  protocol constants (token lifetimes, upload size limit, takedown
  deadline hours, account-deletion window days) so code references
  constants instead of re-typing numbers.

**Functions**

```python
# common/ivcommon/config.py
def load_taxonomy(path: Path | None = None) -> Taxonomy: ...
def load_thresholds(path: Path | None = None) -> Thresholds: ...
def load_policy(path: Path | None = None) -> Policy: ...
```

**Acceptance criteria**

- [ ] Loaders validate files and fail with a clear message on unknown
  keys or missing values.
- [ ] Unit tests cover each loader.

### 0.4 Content policy, terms and removal-request notice

Write three plain-language documents, each marked `DRAFT` until the
user approves:

- `docs/CONTENT_POLICY.md` — not allowed: real violence, gore, nudity
  or sexual content of any kind; illegal content (sexual exploitation
  of children) is reported to NCMEC; guidance to photograph scenes not
  injured people; "Not for emergencies: call your local emergency
  number first."; what happens on violation.
- `docs/TERMS.md` — accounts required, minimum age, one person per
  account, account deletion and legal-hold exceptions.
- `docs/REMOVAL_REQUESTS.md` — how anyone (no account) can request
  removal of an intimate image shared without consent, the 48-hour
  commitment, and that identical copies are removed too.

Phase 4 serves all three via `GET /v1/policy` and the Android app
bundles copies as an offline fallback; Phase 0 only writes the
documents and checks version/field consistency here.

**Acceptance criteria**

- [ ] Each document and `config/policy.yaml` share the same version
  strings; a test checks they match.
- [ ] `REMOVAL_REQUESTS.md` lists every field required by the
  `takedown_request` schema.

### 0.5 Evaluation harness

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
def latency_percentiles(samples_ms: list[float]) -> dict[str, float]: ...

# eval/run.py
def run_eval(task: str, model_version: str, dataset_version: str) -> EvalReport: ...
# writes eval/reports/<task>/<model_version>__<dataset_version>.{json,md}
```

**Acceptance criteria**

- [ ] Each metric has a unit test with a hand-computed expected value.
- [ ] `python -m eval.run --task dummy` writes both report files.

### 0.6 Dataset and model registries

`registry/datasets.yaml` and `registry/models.yaml`: name, version,
source URL, **license**, intended use (`research` /
`commercial-approved`), sha256, storage path (under `data/` or
`ARTIFACT_ROOT`), created_at, parent versions.

```python
# common/ivcommon/registry.py
def register_dataset(name: str, version: str, path: Path, license: str, source: str, parents: list[str] | None = None) -> None: ...
def register_model(name: str, version: str, artifacts: dict[str, Path], dataset_version: str, embedding_version: str | None, license: str) -> None: ...
def resolve(name: str, version: str = "latest") -> RegistryEntry: ...  # verifies sha256, errors clearly if artifact missing
```

**Acceptance criteria**

- [ ] Registering refuses entries with an empty `license`.
- [ ] Checksums verified on `resolve`; a missing artifact produces an
  ENV-BLOCKED-style error naming the expected path, not a stack trace.

### 0.7 Agent working conventions

Create:

- `docs/decisions/0000-template.md` — decision record template.
  Agents record reversible decisions here instead of stopping, except
  orchestrator §9 user-only decisions.
- `docs/HUMAN_INPUTS.md` — every external input from
  DEVELOPMENT_PLAN §8.1 with status (`pending`/`provided`/`waived`).
- `docs/BLOCKED.md` — anything unfinished for a missing human input,
  the mock used, and any SAFETY-STOP file paths (path only).
- Each `logs/specN_log.md` (N = 0–8) created empty except its title and
  a final `<!-- END-OF-LOG -->` sentinel line (orchestrator §6.2). The
  orchestrator creates `spec0_log.md` itself at phase start, before any
  brief runs (orchestrator §1 step 0); this objective creates the rest
  and must not overwrite a log that already has entries — an existing
  file with only its sentinel is left as is. The brief lists the missing
  logs in `new_files`.

**Acceptance criteria**

- [ ] All files exist (the orchestrator's phase-start skeletons for
  `HUMAN_INPUTS.md`/`BLOCKED.md` completed, not overwritten);
  `HUMAN_INPUTS.md` lists every gate from every
  phase spec; every spec log ends with the sentinel.

### 0.8 Synthetic fixtures

`python tasks.py fixtures` generates small synthetic images with Pillow
(solid scenes, text, simple shapes) and variants: no EXIF, EXIF with
GPS, rotated EXIF orientation, re-encoded JPEG quality 50, HEIC copy,
PNG. Unit tests only.

**Acceptance criteria**

- [ ] Fixtures deterministic (same bytes for same seed), < 5 MB total,
  safe to commit.

### 0.9 CSAM hash-matching interface

Shared by Phase 1 (screening policy data) and Phase 4 (screening every
upload). Real providers are implemented in Phase 4.

```python
# common/ivcommon/hashmatch.py
class HashMatcherUnavailable(Exception): ...  # provider outage (Phase 8: uploads stay queued)
class HashMatchResult(BaseModel):
    matched: bool
    provider: str
    match_id: str | None
class HashMatcher(Protocol):
    def check(self, image_bytes: bytes) -> HashMatchResult: ...  # raises HashMatcherUnavailable on outage, never returns matched=False for one
class MockHashMatcher: ...  # matches only sha256s in config/test_hashmatch.yaml (benign fixtures); raises HashMatcherUnavailable when configured to simulate outage
def get_hash_matcher() -> HashMatcher: ...  # Mock allowed only when ENV in {dev, test}
```

The mock list lives at `config/test_hashmatch.yaml` (created by the
0.9 brief). `ENV` comes from the environment (see `.env.example`).

**Acceptance criteria**

- [ ] `get_hash_matcher()` raises at startup if `ENV` is not
  `dev`/`test` and no real provider is configured (test).
- [ ] Mock match list contains only Phase 0 synthetic fixtures.
- [ ] `check` outage raises `HashMatcherUnavailable` (test with the
  mock in outage mode); callers treat it as retry-later, never as a
  non-match.

## Agent notes

- Contracts are the source of truth. A later phase needing a contract
  change updates the schema, bumps `schema_version`, updates examples,
  and records a decision. Breaking changes need the user (orchestrator
  §9).
- Never commit secrets. Secrets come from env vars in `.env.example`,
  checked only via `tasks.py env-check`.
- Calibrated numbers live in `thresholds.yaml`; protocol constants in
  `policy.yaml`/contracts. No other magic numbers in code.
- Never collect, download, generate or open material that could be
  CSAM (DEVELOPMENT_PLAN §8.2).

## Out of scope

Any model training, endpoints beyond stubs, Android code.

## Definition of done

Every acceptance criterion recorded as passing in `logs/spec0_log.md`
(the boxes above are spec source text and are never ticked; see
`logs/README.md`), `python tasks.py check` green on Windows,
`docs/HUMAN_INPUTS.md` complete. A criterion that cannot run — Docker
absent for the services box, for example — keeps its objective
BUILD-ACCEPTED with the criterion listed as open (orchestrator §7),
logged in `BLOCKED.md`: the phase may be build-complete and sequence
to Phase 1, but the criterion still has not passed and no launch
claim may rest on it. An objective with no provisional path stays
open and blocks sequencing.
