# Phase 1 — Data Pipeline and Labels

**Why separate:** Phases 2 and 3 must train and evaluate on fixed,
versioned, license-tracked splits. Downloading and cleaning roughly a
million image URLs is long-running, and dataset licenses need the
user's sign-off once. Isolating this means one human gate, after which
training runs unattended.

| | |
|---|---|
| Depends on | Phase 0 |
| Unblocks | Phases 2, 3 |
| Execution | Sequential only — Block 0, phase 2 of 2 (starts automatically after Phase 0; manual stop after this phase) |
| Stack | Python (`ivml.data`), pandas/pyarrow, Pillow + pillow-heif, imagehash, httpx |

## Human inputs (gate)

One rule (orchestrator §1): use the fallback below to keep working and
log it in `BLOCKED.md`. A fallback never satisfies a criterion that
requires the real input: the affected objective is BUILD-ACCEPTED
with the criterion listed as open where a fallback exists, or stays
open (NEEDS-USER-APPROVAL or ENV-BLOCKED) where none does, until the
input arrives and the criterion actually passes.

| Input | Needed for | If missing |
|---|---|---|
| License approval per dataset and intended use | 1.1–1.3 | Ingest anyway in research-only mode, tag `intended_use: research`, log in `BLOCKED.md`; the objective is not ACCEPTED until the user approves the license and intended use |
| Access/terms acceptance for Incidents1M and CrisisMMD; files in `data/raw/<name>/` | 1.1, 1.2 | Objective cannot start (NEEDS-USER-APPROVAL) |
| Licensed violence/gore set in `data/raw/policy/violence_gore/` | 1.6 | Build category from CrisisMMD only; log gap |
| Licensed **adult** nudity/sexual-content set in `data/raw/policy/nudity_sexual/` (adults only, documented source) | 1.6 | Category untrained; Phase 2 marks it `unavailable`; log gap |
| Car-crash severity labels (a few hundred) | 1.7 | Export the labeling batch and continue; crash severity marked low-confidence in Phase 2 |

## Long-job rule (applies to 1.1 and 1.5)

Downloads and manifest builds run far beyond one builder session. Every
such job is **resumable** and updates its brief checkpoint
(`work/checkpoints/phase-1-<objective>.md`) at least every 15 minutes
of work: parameters, counts so far, completed shards, and the exact
resume command. A new session resumes from the checkpoint; restarting
from zero because a session ended is a brief failure, not bad luck.

## Seed datasets

| Dataset | Use in v1 |
|---|---|
| **Incidents1M** (MIT CSAIL) | Main incident classification source (~1M web images, largely URLs) |
| **CrisisMMD** (QCRI) | Severity labels, extra disaster images, claim text, partial policy positives (injured/dead category) |
| **xBD** (xView2) | Registered only. Satellite viewpoint; not used for v1 training unless a decision record shows benefit |

Verify exact class/category names against each dataset's release files
before writing label maps.

## Objectives

### 1.1 Ingest Incidents1M

```python
# ml/ivml/data/incidents1m.py
def download_incidents1m(index_path: Path, out_dir: Path, max_workers: int = 16,
                         rate_limit_per_host: float = 2.0) -> DownloadReport: ...
def parse_incidents1m_labels(index_path: Path) -> pd.DataFrame: ...
```

Downloader defaults (record any change as a decision): per-request
timeout 30 s, at most 3 attempts per URL then counted as dead-link,
`User-Agent: iVouch-data-ingest/1.0 (research)`, shards of 10k URLs
with per-shard checkpoints.

**Acceptance criteria**

- [ ] Downloader resumes after interruption without re-downloading
  completed files (checkpointed per shard; test with a mock HTTP
  server, not the live web).
- [ ] `DownloadReport` records requested / downloaded / dead-link /
  non-image / too-small counts; written to
  `data/reports/incidents1m_download.json`.
- [ ] Every stored image decodes with Pillow and has sha256 + pHash
  recorded. Files listed via SAFETY-STOP (agent notes) have their
  bytes discarded immediately, are skipped and counted separately,
  never retried automatically.

### 1.2 Ingest CrisisMMD

```python
# ml/ivml/data/crisismmd.py
def load_crisismmd(root: Path) -> pd.DataFrame: ...
```

**Acceptance criteria**

- [ ] All annotated images loaded; label distribution report written.

### 1.3 Register xBD (no ingestion)

- [ ] `registry/datasets.yaml` has an xBD entry with license and
  `use: auxiliary-not-trained`.

### 1.4 Taxonomy label maps

Map source labels to `config/taxonomy.yaml` ids in
`config/label_maps/incidents1m.yaml` and
`config/label_maps/crisismmd.yaml`. Severity map for CrisisMMD:
`little_or_no_damage → minor`, `mild_damage → moderate`,
`severe_damage → severe`. CrisisMMD's vehicle-damage category may map
to `car_crash`; verify by sampling.

```python
# ml/ivml/data/labels.py
def map_labels(source: str, record: dict) -> UnifiedLabel: ...
# incident_ids: list[str], severity: str | None,
# policy_category: "none" | "violence_gore" | "nudity_sexual" | None
```

**Acceptance criteria**

- [ ] Every source class appears in the map as a taxonomy id or
  explicitly `exclude`.
- [ ] A sample sheet of 20 images per mapped class is written to
  `data/reports/label_map_samples/` for spot checks — **excluding any
  policy-category images** (violence/gore, nudity/sexual, injured/dead).
  Policy classes are verified by counts and label metadata only, never
  by sample sheets. `data/` is git-ignored: the orchestrator verifies
  by directory listing (orchestrator §6), not by diff.

### 1.5 Unified manifest and splits

Manifest: `data/manifests/<version>/manifest.parquet` with columns
`image_id, path, sha256, phash, source, source_labels, incident_ids,
severity, policy_category, license, intended_use, split, width,
height, dup_group`.

```python
# ml/ivml/data/manifest.py
def build_manifest(sources: list[pd.DataFrame]) -> pd.DataFrame: ...
def assign_dup_groups(df: pd.DataFrame, phash_max_distance: int = 8) -> pd.DataFrame: ...
def build_splits(df: pd.DataFrame, seed: int, ratios: tuple[float, float, float] = (0.8, 0.1, 0.1)) -> pd.DataFrame: ...
def write_manifest(df: pd.DataFrame, version: str) -> Path: ...
```

`phash_max_distance` defaults to 8; the brief may set another value
with a decision record.

**Acceptance criteria**

- [ ] Exact duplicates (sha256) removed; near-duplicates share a
  `dup_group` and **no group crosses splits** (test).
- [ ] Splits stratified by incident id and source.
- [ ] Same inputs + seed produce a logically identical manifest (same
  rows, columns and values ignoring Parquet file metadata/timestamps;
  test compares DataFrames, not bytes).
- [ ] Class-count report written; any class with < 500 training images
  is flagged in a decision record (this flag is what later justifies a
  metric evidence pack under orchestrator §3 — it is data, not failure).
- [ ] Manifest registered with license per row (no empty licenses).

### 1.6 Content-policy dataset

- `violence_gore` positives: user-provided set in
  `data/raw/policy/violence_gore/` plus CrisisMMD's injured/dead-people
  category (verify category name).
- `nudity_sexual` positives: **only** the user-provided adult set in
  `data/raw/policy/nudity_sexual/`. No other source, ever.
- Negatives (`none`): incident images without violence, injuries or
  nudity, deliberately including car crashes without visible people and
  people in ordinary clothing (beach floods, swimwear) as hard negatives.

Store as a separate manifest `policy_manifest.parquet` with the same
split rules.

**Acceptance criteria**

- [ ] Policy test split contains all available hard negatives (target
  ≥ 200 non-violent car-crash images and ≥ 200
  people-in-ordinary-clothing images); actual counts reported either
  way. The criterion passes only at the target counts; below target,
  with every available hard negative included and counted, the
  objective is BUILD-ACCEPTED with this criterion listed as open
  (orchestrator §7) — agents never lower the target themselves.
- [ ] Policy images are stored in an access-restricted directory and
  never copied into `fixtures/`, sample sheets, eval report thumbnails
  or logs.
- [ ] Before ingest, every policy image is hash-checked via
  `ivcommon.hashmatch.HashMatcher` (Phase 0 interface; mock until real
  access exists — note in the report that a mock check is a placeholder,
  not screening). Any match stops ingestion of **that file only**, is
  recorded by path in `BLOCKED.md`, and ingestion continues past it.

### 1.7 Crash-severity labeling round-trip

```python
# ml/ivml/data/labeling.py
def export_for_labeling(df: pd.DataFrame, query: str, n: int, out_csv: Path, seed: int) -> Path: ...
def import_labels(csv_path: Path, field: str) -> pd.DataFrame: ...
```

**Acceptance criteria**

- [ ] Export produces a CSV + image folder the user can label in a
  spreadsheet.
- [ ] Import validates allowed values and merges into a new manifest
  version.

### 1.8 Claim-text dataset

From CrisisMMD tweet text, build `text_manifest.parquet`
(`text, incident_ids, split`) for the Phase 2 claim-text classifier.

**Acceptance criteria**

- [ ] Text splits follow the image splits for the same tweet (no
  leakage).

## Agent notes

- Many Incidents1M URLs are dead; expect a large dead-link fraction and
  report it rather than retrying forever. Per-host rate limits and a
  descriptive User-Agent are mandatory.
- Download hosts come from the dataset's official index file, held
  locally: extract the host list from the index into the brief's
  checkpoint before any download, and fetch only those hosts,
  download-only (the scoped exception in `AGENTS.md` §4.10). Hosts not
  in the index are out of scope, not a reason to browse.
- Apply EXIF orientation before computing pHash and dimensions.
- Licenses are typically research-oriented. Never mark rows
  `commercial-approved` without a user decision.
- **Never search for, scrape or download nudity/sexual content.** The
  only allowed source is the user-provided adult set.
- **Suspect-file rule:** if any image might involve a minor in a sexual
  context, stop on that file only — do not open, copy or view it
  further — record only its path in `BLOCKED.md`, list it in the job
  checkpoint, and continue with the next file. Only the user clears a
  listed path; agents never re-examine one.

## Out of scope

Training, augmentation (Phase 2), face/plate or mask labels (Phase 3).

## Definition of done

Manifests registered, reports written, every acceptance criterion
recorded as passing in `logs/spec1_log.md` (the boxes above are spec
source text and are never ticked; see `logs/README.md`), with
checkpoints for every long job. An objective blocked on a missing
input with a working fallback is BUILD-ACCEPTED with its criteria
listed as open (logged in `BLOCKED.md`); an objective with no fallback
stays open (ENV-BLOCKED / NEEDS-USER-APPROVAL) and blocks sequencing
under orchestrator §7. Checkpoint resumptions continue the same
attempt and never consume a new one while the checkpoint shows
progress (orchestrator §3).
