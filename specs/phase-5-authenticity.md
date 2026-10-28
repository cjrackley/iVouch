# Phase 5 — Authenticity and Escalation

**Why separate:** this is the highest-risk subsystem — calling a real
victim's photo fake causes harm. It depends on external services
(Google Play Integrity, a reverse image search provider, an LLM host),
its own evaluation data, and the strictest metric in the project
(false-accusation rate). Isolating it keeps that risk testable and lets
the user approve all external providers in one place.

(Android is the only v1 client, so attestation here is Play Integrity
only. A future client would add its verifier behind the same
`AttestationVerifier` protocol without changing fusion.)

| | |
|---|---|
| Depends on | Phases 0, 2, 4 |
| Unblocks | Phases 6 (real attestation), 7, 8 |
| Execution | Sequential only — Block 2, phase 2 of 2 (starts automatically after Phase 4; manual stop after this phase) |
| Stack | Python (`ivserver.authenticity`), Pillow/piexif, `c2pa-python` (verify package name), imagehash, pgvector, httpx, Google Play Integrity API |

## Human inputs (gate)

| Input | If missing (agent uses) |
|---|---|
| Google Play Integrity: Cloud project, Play Console app, service-account credentials, package name, signing cert digest | `MockPlayIntegrity` |
| Reverse image search provider + API key (e.g. Google Cloud Vision web detection, TinEye) | `MockReverseSearch` (fixture-driven) |
| Escalation model host + key for Llama 4 Scout (or GPU to self-host) | `MockEscalator` |
| Forensic training data or budget/approval to generate AI images | Forensic v0 only (no trained score) |
| Held-out **real, consented phone photos** (ideally ≥ 300) for false-accusation eval | Use license-cleared Phase 1 test images for development and report the result as provisional evidence only; the 5.9 criterion stays open (NEEDS-USER-APPROVAL) until the consented set exists — never pass it on the substitute set |

Every provider sits behind an interface with a mock, so the phase can
be built and tested without keys. Credentials are checked with
`python tasks.py env-check --names ...` only. Provider hosts used by a
brief must appear in its `network_allowed`; that list is reviewed by
the orchestrator, not enforced by the sandbox — a provider call to an
unlisted host found in the diff/logs is a gate failure.

## Signals and output

```python
class AuthenticitySignals(BaseModel):
    capture_source: Literal["in_app_camera", "gallery", "web_upload"]
    attestation: Literal["valid", "invalid", "absent", "not_applicable"]
    c2pa: Literal["valid", "invalid", "absent"]; c2pa_claims: dict | None
    exif: Literal["consistent", "inconsistent", "missing"]; exif_notes: list[str]
    time_plausible: bool | None; gps_plausible: bool | None
    internal_duplicates: list[DuplicateMatch]
    web_matches: list[WebMatch]           # url, first_seen (if provider gives it)
    corroboration_count: int
    forensic_score: float | None          # P(manipulated/AI-generated), None in v0
    context_check: ContextCheck | None    # escalation only

class AuthenticityResult(BaseModel):
    label: Literal["likely-real", "needs-review", "likely-manipulated"]
    confidence: float
    reasons: list[str]                    # "signals observed", never "proven"
```

## Objectives

### 5.1 Provenance checks

```python
# server/ivserver/authenticity/provenance.py
def exif_signals(original: bytes, capture: CaptureMetadata, location: Location, received_at: datetime) -> ExifSignals: ...
```

Checks: capture time vs. device-reported time vs. receipt time; EXIF
GPS vs. device location; editing-software tags; missing EXIF on
`in_app_camera` captures (suspicious, since the app writes it).

**Acceptance criteria**

- [ ] Unit tests for each rule using Phase 0 fixtures (no EXIF, forged
  time, GPS far from device location, editor tag).

### 5.2 C2PA content credentials

```python
# server/ivserver/authenticity/c2pa_check.py
def c2pa_signals(original: bytes) -> C2paSignals: ...
```

**Acceptance criteria**

- [ ] Distinguishes valid / invalid / absent using the C2PA sample
  files published by the Content Authenticity Initiative. (Fetching
  those samples requires prior user approval in `HUMAN_INPUTS.md` plus
  the host in the brief's `network_allowed`; if either is missing, use
  locally signed fixtures via the pinned `c2pa` package — verify the
  exact PyPI package name first and record it — or synthetic
  `C2paSignals` unit fixtures, and mark the sample-source gap in
  `BLOCKED.md`.)
- [ ] A manifest declaring a generative-AI tool produces a strong
  `likely-manipulated` reason.

### 5.3 Attestation (Play Integrity verifier)

```python
# server/ivserver/attestation/play_integrity.py
class PlayIntegrityVerifier(AttestationVerifier): ...
# nonce, package name, cert digest, device integrity verdict,
# request hash binding account_id
```

**Acceptance criteria**

- [ ] Replayed nonce, wrong package, wrong cert digest, or a token
  bound to a different account → `invalid`. Tests use the mock token
  format defined and documented by the builder (mock only; no real
  Play tokens are recorded here).
- [ ] Each account–device pairing is recorded; accounts-per-device is
  available to fusion and abuse controls (threshold in
  `thresholds.yaml`).
- [ ] `DevAttestationVerifier` is impossible to enable when
  `ENV != dev` (test).

### 5.4 Internal duplicates

```python
# server/ivserver/authenticity/duplicates.py
def find_duplicates(report_id: str, phash: int, embedding: np.ndarray, k: int = 10) -> list[DuplicateMatch]: ...
```

Match rule: pHash Hamming distance ≤ `duplicates.phash_max_distance`
AND embedding cosine similarity ≥ `duplicates.cosine_min` (both in
`thresholds.yaml` under `# CALIBRATE: Phase 5` keys named in the
brief; defaults 8 / 0.92 unless the brief states otherwise).

**Acceptance criteria**

- [ ] Recall@10 ≥ 0.95 on a synthetic set (JPEG q50–95, resize
  50–150%, crop ≤ 20%, borders/screenshot frame, slight color shift).
- [ ] False-match rate ≤ 1% on distinct images from the Phase 1 test
  split.
- [ ] A match to an earlier report from a different place/time adds a
  "previously submitted" reason.

### 5.5 Web reverse image search

```python
# server/ivserver/authenticity/reverse_search.py
class ReverseImageSearch(Protocol):
    async def search(self, image: bytes) -> list[WebMatch]: ...
class MockReverseSearch: ...
```

**Acceptance criteria**

- [ ] Sends the **blurred public derivative**, never the original (test).
- [ ] Results cached by sha256; daily call budget in
  `thresholds.yaml` enforced.
- [ ] A web match first seen before the claimed capture time adds a
  "published earlier online" reason (miscontextualization).

### 5.6 Corroboration

```python
# server/ivserver/authenticity/corroboration.py
def corroboration_count(report: Report, radius_m: int, window_h: int) -> int: ...
```

Counts reports from **distinct verified accounts on distinct
devices**, same incident type, within radius and time window,
excluding duplicates of the same image and suspended accounts.

**Acceptance criteria**

- [ ] Tests for: same account twice (counts once), several accounts on
  one device (counts once), duplicate image from another account (not
  counted), different type (not counted), suspended account (not
  counted).

### 5.7 Forensic score

- **v0:** no learned score (`forensic_score = None`); fusion relies on
  other signals.
- **v1 (if data available):** classifier on DINOv3 embeddings (+
  optional frequency features) trained on real vs.
  AI-generated/manipulated images from several generators. Minimum
  for v1: ≥ 2 generator families with ≥ 500 images each, plus one
  held-out family for eval; if only one family exists, the held-out
  criterion stays open.

```python
# server/ivserver/authenticity/forensics.py
class ForensicDetector(Protocol):
    def score(self, img: Image.Image) -> float | None: ...
```

**Acceptance criteria (v1)**

- [ ] ROC-AUC reported per generator family, including at least one
  generator **held out** of training.
- [ ] Threshold chosen so this signal alone yields ≤ 1%
  false-accusation on the real-photo set. If the held-out real set is
  the provisional one (Human inputs), this criterion stays open
  (NEEDS-USER-APPROVAL) until the consented set exists.

### 5.8 Escalation and context check

Called only when routing says so (low confidence, high severity,
device/server disagreement, or reviewer `escalate`). Llama 4 Scout
through an OpenAI-compatible chat interface so the host can change.

```python
# server/ivserver/escalation/escalator.py
class Escalator(Protocol):
    async def run(self, blurred_image: bytes, report: Report) -> EscalationResult: ...  # caption, rationale, context_check
# server/ivserver/escalation/weather.py
async def weather_at(lat: float, lng: float, when: datetime) -> WeatherObs | None: ...  # Open-Meteo historical API
```

**Acceptance criteria**

- [ ] Prompt and expected JSON schema stored in
  `server/ivserver/escalation/prompts/` with version. Schema fields:
  `caption: str`, `rationale: str`, `context_check:
  {mismatch: bool, explanation: str} | None`. Invalid model output is
  retried once, then recorded as `context_check: None`. The builder
  drafts the prompt text and records it; no browsing for prompts.
- [ ] Daily escalation budget enforced; when exhausted, cases go to
  human review without escalation.
- [ ] Context check flags claim/scene mismatches (e.g. claim "flood",
  scene dry and sunny with weather data agreeing) on a fixture set.

### 5.9 Fusion

Rule-based, ordered, all thresholds in `thresholds.yaml` under
`# CALIBRATE: Phase 5` keys named in the brief. Rules produce reasons;
the label is the most severe rule outcome. Implement exactly these
rules in order (extra rules need a decision record):

1. C2PA manifest declares a generative-AI tool →
   `likely-manipulated` ("signals observed: AI-tool manifest").
2. Web match first seen before claimed capture →
   `likely-manipulated` ("published earlier online").
3. Internal duplicate from a different place/time →
   `needs-review` ("previously submitted").
4. `in_app_camera` + attestation `invalid` → `needs-review`.
5. `forensic_score` (if not None) above `fusion.forensic_high` →
   `needs-review`.
6. `corroboration_count` ≥ `fusion.corrob_min` with no rule 1–5 hit
   and severity ≠ `severe` (taxonomy value, `config/taxonomy.yaml`)
   → `likely-real`; `severe` → always `needs-review`.
7. Default: `needs-review`.

```python
# server/ivserver/authenticity/fusion.py
def fuse(signals: AuthenticitySignals, incident_severity: str, thresholds: Thresholds) -> AuthenticityResult: ...
```

**Acceptance criteria**

- [ ] Each rule has a unit test.
- [ ] **False-accusation rate** (real photos labeled
  `likely-manipulated`) ≤ 1% on the held-out real set. On the
  provisional set (if the consented set is missing) this criterion is
  reported with its sample size as provisional evidence only and stays
  open (NEEDS-USER-APPROVAL) — passing it on a small substitute set
  must never be logged as passing it outright.
- [ ] High-severity reports are never auto-labeled `likely-real`
  without review.
- [ ] Reasons use "signals observed" wording. Test checks the reasons
  list only (not the label): it fails on case-insensitive standalone
  words "proven", "fake" or "real" (regex `\b(proven|fake|real)\b`),
  excluding the quoted label strings `likely-real` / `needs-review` /
  `likely-manipulated` themselves.

## Agent notes

- Gallery and web uploads are not suspicious by themselves; they just
  lack in-app capture and attestation signals. Don't penalize them as
  manipulated.
- Weather: Open-Meteo is free for non-commercial use; commercial use
  needs a paid plan. Dev/test may use the free tier for non-commercial
  development only; production needs the paid plan (launch-checklist
  item in Phase 8). Keep it behind `weather_at`.
- Documentation and sample-file hosts (C2PA samples, provider docs)
  must be user-approved in `docs/HUMAN_INPUTS.md` before any brief
  lists them in `network_allowed`.
- AI-generation detectors degrade on new generators. The forensic score
  is one input, never a verdict.
- CSAM hash matching is not an authenticity signal. It runs earlier in
  the Phase 4 pipeline; quarantined items never reach this service.

## Out of scope

Reviewer UI (Phase 7), red-teaming (Phase 8), CSAM hash matching and
takedowns (Phase 4).

## Definition of done

Real `AuthenticityService` wired into the Phase 4 pipeline, mocks in
place for missing inputs, eval reports for duplicates, fusion and (if
trained) forensics, and every acceptance criterion recorded as passing
in `logs/spec5_log.md` (the boxes above are spec source text and are
never ticked; see `logs/README.md`). Provisional evidence is reported
as provisional: its criterion stays open under the objective's
BUILD-ACCEPTED verdict (orchestrator §7), the phase may be
build-complete, and no authenticity claim may rest on it.
