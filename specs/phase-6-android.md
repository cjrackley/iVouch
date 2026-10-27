# Phase 6 — Android App (Kotlin)

**Why this is its own phase:** Android is the first client. It implements accounts, the on-device pipeline, offline queue, attestation and map against the real contracts, and its behavior becomes the reference that iOS mirrors in Phase 7. It can be built and tested on Windows/Linux with the Android emulator, so agents can work on it without special hardware.

| | |
|---|---|
| Depends on | Phases 0, 2, 3 (model artifacts + test vectors), 4 (API) |
| Unblocks | Phase 7 |
| Parallel with | Phases 5, 8 |
| Stack | Kotlin, Jetpack Compose, CameraX, Photo Picker, WorkManager, Room, OkHttp + Retrofit + kotlinx.serialization, ExecuTorch Android, MapLibre Native Android, Play Integrity API, Fused Location Provider, Android Keystore |

## Human inputs (gate)

| Input | If missing |
|---|---|
| Application ID (package name) | Use `org.ivouch.app` placeholder; record decision |
| Play Console app + Play Integrity setup (from Phase 5) | Dev attestation mode against a dev server |
| A physical mid-range Android phone (or Firebase Test Lab access) for performance criteria | Report emulator numbers; mark 6.10 provisional |

## Module layout

`app`, `core-model` (ExecuTorch wrappers, preprocessing), `core-data` (Room, API client, auth, upload worker), `feature-account`, `feature-policy`, `feature-capture`, `feature-report`, `feature-map`, `feature-review`, `feature-settings`.

## Objectives

### 6.1 Project skeleton

**Acceptance criteria**
- [ ] `./gradlew check` (unit tests + ktlint + detekt or Android lint) passes in CI.
- [ ] API base URL, tile style URL, removal-request page URL and environment come from build config, not code.
- [ ] Generated or hand-written DTOs validated against `contracts/examples/` in unit tests.

### 6.2 Accounts

Sign up (email, password, date of birth for the age gate, terms acceptance), email verification, login, logout, password reset, and **in-app account deletion**.

**Functions**
```kotlin
interface AuthRepository {
    suspend fun register(email: String, password: String, dateOfBirth: LocalDate, termsVersion: String): RegisterResult
    suspend fun login(email: String, password: String): LoginResult
    suspend fun refreshIfNeeded(): Boolean
    suspend fun logout()
    suspend fun requestPasswordReset(email: String)
    suspend fun deleteAccount(): DeletionResult
    fun session(): StateFlow<Session?>      // account id, roles, emailVerified, policyVersionAccepted
}
class AuthInterceptor : Interceptor        // adds access token; refreshes once on 401, then logs out
```

**Acceptance criteria**
- [ ] Date of birth is sent only in the register request and never stored on the device (test).
- [ ] Tokens stored with Android Keystore-backed encryption; cleared on logout and account deletion.
- [ ] Unverified accounts see a "verify your email" screen with resend; capture is disabled until verified.
- [ ] Account deletion is reachable from Settings in ≤ 3 taps, confirms once, calls `DELETE /v1/account`, clears all local data (queue, cache, tokens) and returns to the login screen (UI test).
- [ ] Once logged in, capture and on-device analysis work offline; an expired session with no network keeps reports queued until the user logs in again.

### 6.3 Content policy gate

**Functions**
```kotlin
interface PolicyRepository {
    suspend fun current(): Policy          // GET /v1/policy, falls back to bundled copy offline
    fun acceptedVersion(): String?          // from the account session
    suspend fun accept(version: String)     // POST /v1/policy/accept
}
```

**Acceptance criteria**
- [ ] Capture is impossible until the current policy version is accepted by the logged-in account (UI test).
- [ ] A new policy version re-prompts on next launch.
- [ ] Policy, terms and the removal-request page are reachable from Settings and the capture screen.

### 6.4 Capture

- In-app camera via CameraX → `capture_source = in_app_camera`; app writes capture time and (if consented) GPS into EXIF.
- Gallery import via Photo Picker → `capture_source = gallery`.
- Location consent toggle; manual pin fallback; `location.source` set correctly.

**Acceptance criteria**
- [ ] Original bytes are uploaded unmodified (sha256 of uploaded bytes == file on disk) (test).
- [ ] Gallery imports read location EXIF only with `ACCESS_MEDIA_LOCATION` granted; otherwise `source: none` (test).
- [ ] No location is sent when consent is off.

### 6.5 On-device analysis

**Functions**
```kotlin
interface IncidentAnalyzer {
    suspend fun analyze(image: Bitmap, exifOrientation: Int, claimText: String?): DeviceResult
}
object Preprocess { fun toTensor(image: Bitmap, exifOrientation: Int): FloatArray }  // matches contracts/preprocessing.md
object Heatmap { fun toBoxes(heatmap: FloatArray, width: Int, height: Int, threshold: Float, maxBoxes: Int): List<Box> }
object ClaimClassifier { fun predict(modelJson: ClaimModel, text: String): Map<String, Float> }
object Rationale { fun build(/* same inputs as ivcommon.rationale.build_rationale */): String }
```

Flow: preprocess → `iv_core.pte` → if any `policy_scores[category] ≥ policy.block_threshold[category]` → **block** and show the matching policy section → otherwise heatmap boxes → segmenter → rationale → `DeviceResult`. Categories marked `unavailable` in `thresholds.yaml` don't block on the phone.

**Acceptance criteria**
- [ ] Instrumented parity tests pass on all Phase 2–3 test vectors (core outputs, masks, claim text, rationale strings) within the stated tolerances.
- [ ] Policy-blocked images are never written to the upload queue or app cache; the capture file is deleted on block (test).
- [ ] Analysis runs fully offline (airplane-mode UI test).

### 6.6 Offline queue and upload

**Functions**
```kotlin
interface ReportQueue {
    suspend fun enqueue(report: PendingReport): String   // returns clientReportId (UUID); tied to the current account
    fun observe(): Flow<List<PendingReportState>>
}
class UploadWorker : CoroutineWorker   // network constraint, exponential backoff, auth + attestation per upload
interface Attestor { suspend fun token(nonce: String, requestHash: String): String? }  // Play Integrity standard request
```

**Acceptance criteria**
- [ ] Reports captured offline upload automatically when connectivity returns, exactly once (idempotent `client_report_id`) (test with mock server).
- [ ] Upload survives app kill and device reboot.
- [ ] Each upload fetches a fresh nonce from `/v1/attestation/challenge`; the request hash binds the account id and photo sha256.
- [ ] Queued reports belong to one account; logging out asks the user to upload or discard them first.
- [ ] A generic server rejection ("upload could not be accepted") is shown as-is, with a link to the content policy.

### 6.7 Report card

**Acceptance criteria**
- [ ] Shows the device result immediately, then replaces it with the server result when available, with a "verified by server" or "under review" state.
- [ ] Authenticity banner uses only `likely-real` / `needs-review` / `likely-manipulated` wording with reasons; never "fake" or "proven".
- [ ] Shows "Not for emergencies: call your local emergency number" on every report.

### 6.8 Map

MapLibre Native with OpenFreeMap (or self-hosted) vector tiles, style URL in config; GeoJSON source with built-in clustering.

**Acceptance criteria**
- [ ] Fetches `GET /v1/incidents` for the viewport, debounced 300 ms after pan/zoom.
- [ ] Red-dot markers, ≥ 24 dp hit area; cluster badges show counts; tap zooms in.
- [ ] Tap a dot → bottom sheet: thumbnail, `incident_type — severity`, authenticity banner, time, confidence, `View details`, and a "Request removal" link to the removal-request page.
- [ ] Filters (type, severity, 24h/7d/30d; `likely-manipulated` hidden) map to query params.
- [ ] Reports without location appear in a list with `Add location (manual pin)`, never as dots.
- [ ] TalkBack: each dot has a content description (e.g. "car crash, moderate"); severity always shown as text too.

### 6.9 Reviewer mode

Same login as everyone; reviewer screens appear when the session has the `reviewer` role. Review queue, confirm/correct/escalate/**flag suspected CSAM** from the bottom sheet and report detail.

**Acceptance criteria**
- [ ] Reviewer-only UI hidden for accounts without the role (test).
- [ ] "Flag suspected CSAM" confirms once, calls the review endpoint with `flag_csam`, and immediately removes the item from the screen and image cache.
- [ ] No safety-officer features in the mobile app (web only, Phase 8).

### 6.10 Performance and size budgets

**Acceptance criteria** (mid-range device, e.g. Pixel 6a class)
- [ ] Bundled models ≤ 80 MB; AAB download size reported.
- [ ] Full on-device analysis p50 ≤ 1.5 s, p95 ≤ 3 s (Macrobenchmark or instrumented timing).
- [ ] Initial map dots ≤ 2 s on simulated 4G.
- [ ] No ANRs in a 20-minute monkey test.

## Agent notes

- Play Integrity fails on most emulators; use the dev attestation mode there.
- Apply EXIF orientation before preprocessing, since phone photos are often stored sideways.
- Google Play limits base download size (around 200 MB); stay well under it, but if models grow, plan for Play Asset Delivery.
- Google Play requires apps with account creation to offer account deletion in the app **and** a web link for deletion requests (the Phase 8 page); list both in the Play Console data-safety form.
- Check ExecuTorch's Android docs for the current AAR/Maven coordinates and minimum SDK.

## Out of scope

iOS (Phase 7), web (Phase 8), safety-officer tools (Phase 8), server-delivered model updates (v2).

## Definition of done

All criteria checked (or provisional with reason in `BLOCKED.md`), debug APK builds in CI, end-to-end test against a local server passes: register → verify (via console email) → accept policy → capture → upload → report → delete account.
