# Phase 1 — Data Pipeline and Labels

**Why this is its own phase:** Phases 2 and 3 must train and evaluate on fixed, versioned, license-tracked splits. Downloading and cleaning roughly a million image URLs is long-running, and dataset licenses need the user's sign-off once. Isolating this means one human gate, after which training runs unattended.

| | |
|---|---|
| Depends on | Phase 0 |
| Unblocks | Phases 2, 3 |
| Parallel with | Phase 4 |
| Stack | Python (`ivml.data`), pandas/pyarrow, Pillow + pillow-heif, imagehash, httpx |

## Human inputs (gate)

| Input | Needed for | If missing |
|---|---|---|
| License approval for each dataset and intended use (research vs. commercial) | 1.1–1.3 | Ingest anyway, tag `intended_use: research`, log in `BLOCKED.md` |
| Access/terms acceptance for Incidents1M and CrisisMMD; files placed in `data/raw/<name>/` | 1.1, 1.2 | Phase cannot start that objective |
| A licensed or approved violence/gore image set in `data/raw/policy/violence_gore/` | 1.6 | Build that category from CrisisMMD only; log gap |
| A licensed or approved **adult** nudity/sexual-content image set in `data/raw/policy/nudity_sexual/` (adults only, documented source and age verification by the provider) | 1.6 | Category untrained; Phase 2 marks it `unavailable`; log gap |
| Car-crash severity labels (a few hundred images, `minor` / `moderate` / `severe`) | 1.7 | Export the labeling batch and continue; severity head for crashes is marked low-confidence in Phase 2 |

## Seed datasets

| Dataset | What it is | Use in v1 |
|---|---|---|
| **Incidents1M** (MIT CSAIL) | ~1M web images labeled with incident types and places; distributed largely as URLs | Main source for incident classification; includes car accidents, floods, fires, storms, earthquakes |
| **CrisisMMD** (QCRI) | Tweets + images from 2017 disasters; image labels for informativeness, humanitarian category, **damage severity** | Severity labels; extra disaster images; claim-text training data; partial policy positives (injured/dead category) |
| **xBD** (xView2) | Pre/post-disaster **satellite** imagery with building damage levels | Registered only. Satellite viewpoint differs from phone photos; do not use for v1 training unless a decision record shows benefit |

Verify exact class/category names against each dataset's release files before writing label maps.

## Objectives

### 1.1 Ingest Incidents1M

**Functions**
```python
# ml/ivml/data/incidents1m.py
def download_incidents1m(index_path: Path, out_dir: Path, max_workers: int = 16,
                         rate_limit_per_host: float = 2.0) -> DownloadReport: ...
def parse_incidents1m_labels(index_path: Path) -> pd.DataFrame: ...
```

**Acceptance criteria**
- [ ] Downloader resumes after interruption without re-downloading completed files.
- [ ] `DownloadReport` records requested / downloaded / dead-link / non-image / too-small counts; written to `data/reports/incidents1m_download.json`.
- [ ] Every stored image decodes with Pillow and has sha256 + pHash recorded.

### 1.2 Ingest CrisisMMD

**Functions**
```python
# ml/ivml/data/crisismmd.py
def load_crisismmd(root: Path) -> pd.DataFrame: ...  # image path, tweet text, informativeness, humanitarian, damage_severity
```

**Acceptance criteria**
- [ ] All annotated images loaded; label distribution report written.

### 1.3 Register xBD (no ingestion)

**Acceptance criteria**
- [ ] `registry/datasets.yaml` has an xBD entry with license and `use: auxiliary-not-trained`.

### 1.4 Taxonomy label maps

Map source labels to `config/taxonomy.yaml` ids in `config/label_maps/incidents1m.yaml` and `config/label_maps/crisismmd.yaml`. Severity map for CrisisMMD: `little_or_no_damage → minor`, `mild_damage → moderate`, `severe_damage → severe`. CrisisMMD's vehicle-damage category may map to `car_crash`; verify by sampling.

**Functions**
```python
# ml/ivml/data/labels.py
def map_labels(source: str, record: dict) -> UnifiedLabel: ...  # incident_ids: list[str], severity: str | None, policy_category: "none" | "violence_gore" | "nudity_sexual" | None
```

**Acceptance criteria**
- [ ] Every source class appears in the map as a taxonomy id or explicitly `exclude`.
- [ ] A sample sheet of 20 images per mapped class is written to `data/reports/label_map_samples/` for spot checks.

### 1.5 Unified manifest and splits

Manifest: `data/manifests/<version>/manifest.parquet` with columns `image_id, path, sha256, phash, source, source_labels, incident_ids, severity, policy_category, license, intended_use, split, width, height, dup_group`.

**Functions**
```python
# ml/ivml/data/manifest.py
def build_manifest(sources: list[pd.DataFrame]) -> pd.DataFrame: ...
def assign_dup_groups(df: pd.DataFrame, phash_max_distance: int) -> pd.DataFrame: ...
def build_splits(df: pd.DataFrame, seed: int, ratios: tuple[float, float, float] = (0.8, 0.1, 0.1)) -> pd.DataFrame: ...
def write_manifest(df: pd.DataFrame, version: str) -> Path: ...
```

**Acceptance criteria**
- [ ] Exact duplicates (sha256) removed; near-duplicates share a `dup_group` and **no group crosses splits** (test).
- [ ] Splits are stratified by incident id and source.
- [ ] Same inputs + seed produce a byte-identical manifest (test).
- [ ] Class-count report written; any class with < 500 training images is flagged in a decision record.
- [ ] Manifest registered with license per row (no empty licenses).

### 1.6 Content-policy dataset

Two categories, labeled in `policy_category`:
- `violence_gore` positives: user-provided set in `data/raw/policy/violence_gore/` plus CrisisMMD's injured/dead-people category (verify category name).
- `nudity_sexual` positives: **only** the user-provided adult set in `data/raw/policy/nudity_sexual/`. No other source.
- Negatives (`none`): incident images without violence, injuries or nudity, deliberately including car crashes without visible people and scenes with people in ordinary clothing (beach floods, swimwear, etc.) as hard negatives.

Store as a separate manifest `policy_manifest.parquet` with the same split rules.

**Acceptance criteria**
- [ ] Policy test split contains ≥ 200 non-violent car-crash images and ≥ 200 people-in-ordinary-clothing images (hard negatives) if available; counts reported either way.
- [ ] Images in the policy set are stored in an access-restricted directory and never copied into `fixtures/`, eval report thumbnails or logs.
- [ ] Before ingest, every policy image is hash-checked against the CSAM hash list via `ivcommon.hashmatch.HashMatcher` (Phase 0 interface; mock until access exists); any match stops ingestion of that file and is recorded in `BLOCKED.md` without copying it.

### 1.7 Crash-severity labeling round-trip

**Functions**
```python
# ml/ivml/data/labeling.py
def export_for_labeling(df: pd.DataFrame, query: str, n: int, out_csv: Path, seed: int) -> Path: ...
def import_labels(csv_path: Path, field: str) -> pd.DataFrame: ...
```

**Acceptance criteria**
- [ ] Export produces a CSV + image folder the user can label in a spreadsheet.
- [ ] Import validates allowed values and merges into a new manifest version.

### 1.8 Claim-text dataset

From CrisisMMD tweet text, build `text_manifest.parquet` (`text, incident_ids, split`) for the Phase 2 claim-text classifier.

**Acceptance criteria**
- [ ] Text splits follow the image splits for the same tweet (no leakage).

## Agent notes

- Many Incidents1M URLs are dead (link rot); expect a large dead-link fraction and report it rather than retrying forever.
- Respect each host's terms and rate limits. Set a descriptive User-Agent.
- Apply EXIF orientation before computing pHash and dimensions.
- Licenses for these datasets are typically research-oriented. Never mark rows `commercial-approved` without a user decision.
- **Never search for, scrape or download nudity/sexual content.** The only allowed source is the user-provided adult set. If any image in any dataset looks like it could involve a minor in a sexual context, stop, don't copy or open it further, and record only its path in `BLOCKED.md` for the user.

## Out of scope

Training, augmentation (done at train time in Phase 2), face/plate or mask labels (Phase 3).

## Definition of done

Manifests registered, reports written, all acceptance boxes checked or logged in `BLOCKED.md` with the mock/fallback used.
