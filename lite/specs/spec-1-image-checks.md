# Lite Spec 1 — Image Checks (local only)

**Why separate:** this is the heart of Lite. Every check is a pure
function over image bytes plus config, testable without HTTP. Spec 2
only wires these into an upload pipeline.

| | |
|---|---|
| Depends on | spec-0 |
| Unblocks | spec-2 |
| Execution | Sequential only — spec 2 of 6 |
| Stack | Pillow, piexif, imagehash, transformers CLIP (local) |

## Human inputs

None. All checks run locally. Thresholds are uncalibrated demo values
in `lite/config.yaml`; the log must say so. No accuracy target in this
spec may be presented as met by construction — report observed
numbers only.

## Check pipeline (fixed order)

Every upload passes through these in order. Order is tested.

1. **File sanity.** Type in `allowed_types`, size within
   `max_upload_bytes`, decodes with Pillow. Failure: reject with
   reason `unsupported_file`.
2. **Mock safety gate.** SHA-256 of raw bytes against the fixture
   hash list at `policy_mock_hashes_path`. Match: reject with the
   generic reason `upload_not_accepted`, store no image bytes, keep
   only hash + time + account id. This mock is not real screening.
3. **Provenance-lite.** From EXIF: present/missing, capture time
   sanity (not in the future, not implausibly old), GPS present/
   absent, editing-software tag if any. Output flags only; missing
   EXIF never lowers the label by itself.
4. **Duplicates.** Exact SHA-256 match, then perceptual hash within
   `phash_max_distance` of a prior Lite upload. Output prior report
   ids. Runs here as a function; spec 2 supplies the store.
5. **Incident type.** CLIP zero-shot over `incident_prompts` for
   `car_crash`, `fire`, `flood`, `storm_damage`, `earthquake_damage`,
   `none`. Output all six probabilities.
6. **Severity.** CLIP zero-shot over `severity_prompts`
   (minor/moderate/severe). Output probabilities plus top label.
7. **Claim check.** Cosine similarity between image embedding and
   claim-text embedding (empty claim: `None`). Below
   `claim_mismatch_below` adds reason `claim_mismatch`.
8. **Fusion-lite.** Ordered rules in 1.8. Output label, confidence,
   and reasons using "signals observed" wording only.

## Objectives

### 1.1 File sanity and mock safety gate

```python
# lite/app/checks/files.py
def check_file(raw: bytes) -> FileResult: ...        # ok or reason
def mock_hash_match(raw: bytes, hashes: set[str]) -> bool: ...
```

**Acceptance criteria**

- [ ] Non-image bytes, oversize upload, and truncated JPEG each
  rejected with the right reason (tests on spec-0 fixtures).
- [ ] A fixture whose hash is in the mock list is rejected with
  `upload_not_accepted` and no bytes retained (test inspects store).

### 1.2 Provenance-lite

```python
# lite/app/checks/provenance.py
def provenance_signals(raw: bytes, received_at: datetime) -> Provenance: ...
# fields: exif_present, time_plausible, gps_present, editor_tag
```

**Acceptance criteria**

- [ ] Each spec-0 EXIF variant yields the expected flags (tests).
- [ ] A future capture time sets `time_plausible = False` (test).

### 1.3 Duplicates

```python
# lite/app/checks/duplicates.py
# The store is a minimal sequence protocol, not SQLite: spec 2 adapts
# its rows to [(report_id, sha256, phash), ...] before calling.
def exact_match(sha256: str, store) -> str | None: ...
def near_matches(phash: str, store, max_distance: int) -> list[str]: ...
```

**Acceptance criteria**

- [ ] JPEG re-encode at quality 50 and a 90% resize still near-match
  the original at the configured `phash_max_distance` (test); an
  unrelated fixture does not (test). If the fixture pair does not
  match at the default distance, the builder raises the configured
  distance with a decision note instead of weakening the test.

### 1.4 Incident and severity (CLIP zero-shot)

```python
# lite/app/checks/clip_checks.py
def incident_probs(img) -> dict[str, float]: ...   # six labels, sums ~1
def severity_probs(img) -> dict[str, float]: ...   # three labels
def claim_similarity(img, claim: str | None) -> float | None: ...
```

Prompt text lives in `lite/config.yaml`, not in code. Model loads once
(spec-0 smoke check proves the path); device is GPU with CPU fallback.
`claim_similarity` is cosine similarity in [-1, 1]; the
`claim_mismatch_below` threshold is compared on that scale.

**Acceptance criteria**

- [ ] Probabilities are finite, non-negative, and sum to ~1 (tests
  with a stubbed encoder; one real-model test marked slow is allowed).
- [ ] Empty claim returns `None`; a scene-matching claim scores
  higher than a mismatched one on fixtures (stubbed-encoder test).
- [ ] Observed top-labels on the fixture set are reported in the log
  as demo observations, with no accuracy claim.

### 1.5 Fusion-lite

Rules, in order. First matching rule wins for the label; all matched
reasons are listed. Thresholds come from `lite/config.yaml`.

1. Mock safety match never reaches fusion (rejected in 1.1).
2. Duplicate of an earlier upload with different claimed time ->
   `needs-review`, reason `previously_submitted`.
3. Top incident probability below `low_confidence_below`, or top
   severity is `severe` -> `needs-review`, reason
   `low_confidence` / `high_severity`.
4. `claim_mismatch` present -> `needs-review` with that reason.
5. Editor tag present AND EXIF time implausible ->
   `likely-manipulated`, reason `signals observed: edited file with
   inconsistent capture time`.
6. Otherwise `likely-real`, reason `signals observed: no
   inconsistencies found (demo checks only)`.

```python
# lite/app/checks/fusion.py
def fuse(checks: AllChecks, cfg) -> Verdict: ...
# Verdict: label, confidence, reasons, needs_review (bool)
# confidence is the top incident probability (0-1 float). It is a
# reported number, never an accuracy claim. Spec 2 returns it
# unchanged.
```

**Acceptance criteria**

- [ ] One unit test per rule, including rule-order precedence.
- [ ] No reason string claims certainty: strip the exact label
  tokens (`likely-real`, `needs-review`, `likely-manipulated`)
  from each reason, then assert no case-insensitive whole-word
  match for `proven`, `fake`, or `real` remains (regex test).
- [ ] `severe` and low-confidence cases always set
  `needs_review = True` (tests).

## Agent notes

- Never fetch images from the web for tests. Spec-0 fixtures only.
- CLIP zero-shot is demo-grade. Do not tune prompts against any
  external dataset in this spec; prompt changes are config edits
  recorded in the log.
- Policy categories (violence/gore, nudity) are out of Lite's checks.
  The only safety gate is the mock hash list in 1.1.

## Out of scope

HTTP, storage schema, accounts, UI, real safety providers, forensic
AI-detection, reverse search, attestation.

## Definition of done

Every criterion recorded as passing in `lite/logs/spec1_log.md`,
full Lite suite green, observed fixture results logged without any
accuracy or launch claim.
