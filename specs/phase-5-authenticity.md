# Phase 5 — Authenticity and Escalation

**Why this is its own phase:** This is the highest-risk subsystem: calling a real victim's photo fake causes harm. It depends on several external services (Google Play Integrity, Apple App Attest, a reverse image search provider, an LLM host), its own evaluation data, and the strictest metric in the project (false-accusation rate). Isolating it keeps that risk testable and lets the user approve all external providers in one place.

| | |
|---|---|
| Depends on | Phases 0, 2, 4 |
| Unblocks | Phases 6, 7 (real attestation), 8, 9 |
| Parallel with | Phases 3, 6, 7 |
| Stack | Python (`ivserver.authenticity`), Pillow/piexif, `c2pa-python` (verify package name), imagehash, pgvector, httpx, Google Play Integrity API, Apple App Attest |

## Human inputs (gate)

| Input | If missing (agent uses) |
|---|---|
| Google Play Integrity: Cloud project, Play Console app, service-account credentials, package name, signing cert digest | `MockPlayIntegrity` |
| Apple App Attest: Team ID, bundle ID, (production vs. development environment) | `MockAppAttest` |
| Reverse image search provider choice + API key (e.g. Google Cloud Vision web detection, TinEye) | `MockReverseSearch` (fixture-driven) |
| Escalation model host + key for Llama 4 Scout (or a GPU to self-host) | `MockEscalator` |
| Forensic training data or budget/approval to generate AI images | Forensic v0 only (no trained score) |
| Held-out set of **real, consented phone photos** (ideally ≥ 300) for false-accusation eval | Use license-cleared Phase 1 test images; mark criterion provisional |

Every provider sits behind an interface with a mock so the phase can be built and tested without keys.

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
    reasons: list[str]                    # user-facing "signals observed", never "proven"
```

## Objectives

### 5.1 Provenance checks

**Functions**
```python
# server/ivserver/authenticity/provenance.py
def exif_signals(original: bytes, capture: CaptureMetadata, location: Location, received_at: datetime) -> ExifSignals: ...
```
Checks: capture time vs. device-reported time vs. receipt time; EXIF GPS vs. device location; editing-software tags; missing EXIF on `in_app_camera` captures (suspicious, since the app writes it).

**Acceptance criteria**
- [ ] Unit tests for each rule using Phase 0 fixtures (no EXIF, forged time, GPS far from device location, editor tag).

### 5.2 C2PA content credentials

**Functions**
```python
# server/ivserver/authenticity/c2pa_check.py
def c2pa_signals(original: bytes) -> C2paSignals: ...
```

**Acceptance criteria**
- [ ] Distinguishes valid / invalid / absent using the C2PA sample files published by the Content Authenticity Initiative.
- [ ] A manifest declaring a generative-AI tool produces a strong `likely-manipulated` reason.

### 5.3 Attestation (real verifiers)

**Functions**
```python
# server/ivserver/attestation/play_integrity.py
class PlayIntegrityVerifier(AttestationVerifier): ...  # nonce, package name, cert digest, device integrity verdict, request hash binding account_id
# server/ivserver/attestation/app_attest.py
class AppAttestVerifier(AttestationVerifier): ...      # attestation object on first use, assertions + counter afterwards
```

**Acceptance criteria**
- [ ] Replayed nonce, wrong package/bundle, decreasing App Attest counter, or a token bound to a different account → `invalid` (tests with recorded/mock tokens).
- [ ] Each account–device pairing is recorded; the number of accounts per device is available to fusion and abuse controls (value in `thresholds.yaml`).
- [ ] `DevAttestationVerifier` is impossible to enable when `ENV != dev` (test).

### 5.4 Internal duplicates

**Functions**
```python
# server/ivserver/authenticity/duplicates.py
def find_duplicates(report_id: str, phash: int, embedding: np.ndarray, k: int = 10) -> list[DuplicateMatch]: ...
```

**Acceptance criteria**
- [ ] Recall@10 ≥ 0.95 on a synthetic set (JPEG q50–95, resize 50–150%, crop ≤ 20%, borders/screenshot frame, slight color shift).
- [ ] False-match rate ≤ 1% on distinct images from the Phase 1 test split.
- [ ] A match to an earlier report from a different place/time adds a "previously submitted" reason.

### 5.5 Web reverse image search

**Functions**
```python
# server/ivserver/authenticity/reverse_search.py
class ReverseImageSearch(Protocol):
    async def search(self, image: bytes) -> list[WebMatch]: ...
class MockReverseSearch: ...
```

**Acceptance criteria**
- [ ] Sends the **blurred public derivative**, never the original (test).
- [ ] Results cached by sha256; daily call budget in `thresholds.yaml` enforced.
- [ ] A web match first seen before the claimed capture time adds a "published earlier online" reason (miscontextualization).

### 5.6 Corroboration

**Functions**
```python
# server/ivserver/authenticity/corroboration.py
def corroboration_count(report: Report, radius_m: int, window_h: int) -> int: ...
```
Counts reports from **distinct verified accounts on distinct devices**, same incident type, within radius and time window, excluding duplicates of the same image and suspended accounts.

**Acceptance criteria**
- [ ] Tests for: same account submitting twice (counts once), several accounts on the same device (counts once), duplicate image from another account (not counted), different type (not counted), suspended account (not counted).

### 5.7 Forensic score

- **v0:** no learned score (`forensic_score = None`); fusion relies on other signals.
- **v1 (if data available):** classifier on DINOv3 embeddings (+ optional frequency features) trained on real vs. AI-generated/manipulated images from several generators.

**Functions**
```python
# server/ivserver/authenticity/forensics.py
class ForensicDetector(Protocol):
    def score(self, img: Image.Image) -> float | None: ...
```

**Acceptance criteria (v1)**
- [ ] ROC-AUC reported per generator family, including at least one generator **held out** of training.
- [ ] Threshold chosen so this signal alone yields ≤ 1% false-accusation on the real-photo set.

### 5.8 Escalation and context check

Called only when routing says so (low confidence, high severity, device/server disagreement, or reviewer `escalate`). Uses Llama 4 Scout through an OpenAI-compatible chat interface so the host can change.

**Functions**
```python
# server/ivserver/escalation/escalator.py
class Escalator(Protocol):
    async def run(self, blurred_image: bytes, report: Report) -> EscalationResult: ...  # caption, rationale, context_check
# server/ivserver/escalation/weather.py
async def weather_at(lat: float, lng: float, when: datetime) -> WeatherObs | None: ...  # Open-Meteo historical API
```

**Acceptance criteria**
- [ ] Prompt and expected JSON output schema stored in `server/ivserver/escalation/prompts/` with version; invalid model output is retried once, then recorded as `context_check: None`.
- [ ] Daily escalation budget enforced; when exhausted, cases go to human review without escalation.
- [ ] Context check flags claim/scene mismatches (e.g. claim "flood", scene dry and sunny with weather data agreeing) on a fixture set.

### 5.9 Fusion

Rule-based, ordered, all thresholds in `thresholds.yaml`. Rules produce reasons; the label is the most severe rule outcome.

**Functions**
```python
# server/ivserver/authenticity/fusion.py
def fuse(signals: AuthenticitySignals, incident_severity: str, thresholds: Thresholds) -> AuthenticityResult: ...
```

**Acceptance criteria**
- [ ] Each rule has a unit test.
- [ ] **False-accusation rate** (real photos labeled `likely-manipulated`) ≤ 1% on the held-out real set.
- [ ] High-severity reports are never auto-labeled `likely-real` without review.
- [ ] Reasons use "signals observed" wording; a test fails if any reason contains "proven", "fake" or "real" as a verdict.

## Agent notes

- Gallery and web uploads are not suspicious by themselves; they just lack the in-app capture and attestation signals. Don't penalize them as manipulated.
- Weather: Open-Meteo is free for non-commercial use; commercial use needs a paid plan. Keep it behind `weather_at`.
- Detectors for AI-generated images degrade on new generators. That is why the forensic score is one input, never a verdict.

- CSAM hash matching is not an authenticity signal. It runs earlier in the Phase 4 pipeline; quarantined items never reach this service.

## Out of scope

Reviewer UI (Phase 8), red-teaming (Phase 9), CSAM hash matching and takedowns (Phase 4).

## Definition of done

Real `AuthenticityService` wired into the Phase 4 pipeline, all mocks in place for missing inputs, eval reports for duplicates, fusion and (if trained) forensics.
