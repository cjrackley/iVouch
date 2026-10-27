# Phase 7 — iOS App (Swift)

**Why this is its own phase:** iOS apps can only be built with Xcode on macOS, so this phase needs different infrastructure (a Mac or macOS CI runner) and an Apple Developer account for App Attest. It mirrors a finished Android reference (Phase 6), so behavior is already settled and parity can be tested against known outputs instead of being designed twice.

| | |
|---|---|
| Depends on | Phases 0, 2, 3, 4, 6 (reference behavior) |
| Unblocks | Phase 9 |
| Parallel with | Phases 5, 8 |
| Stack | Swift, SwiftUI, AVFoundation, PhotosUI, CoreLocation, SwiftData (or Core Data), URLSession background transfers, BackgroundTasks, ExecuTorch iOS, MapLibre Native iOS (Swift Package), DeviceCheck (App Attest), Keychain |

## Human inputs (gate)

| Input | If missing |
|---|---|
| **macOS with Xcode** (a Mac, or a macOS CI runner such as GitHub Actions `macos-*`) | Phase cannot start; agents can only write code without building |
| Apple Developer account, Team ID, bundle ID | Simulator-only builds; App Attest in dev mode |
| A physical iPhone (or a device cloud) for App Attest and performance | Simulator numbers; mark 7.6/7.10 provisional |

## Objectives

Each objective mirrors the Android objective with the same number; the Android spec's acceptance criteria apply unless overridden below.

### 7.1 Project skeleton (mirrors 6.1)

**Acceptance criteria**
- [ ] `xcodebuild test` passes in CI; SwiftLint/SwiftFormat clean.
- [ ] DTOs validated against `contracts/examples/`.

### 7.2 Accounts (mirrors 6.2)

```swift
protocol AuthRepository {
    func register(email: String, password: String, dateOfBirth: Date, termsVersion: String) async throws -> RegisterResult
    func login(email: String, password: String) async throws -> LoginResult
    func refreshIfNeeded() async throws -> Bool
    func logout() async
    func requestPasswordReset(email: String) async throws
    func deleteAccount() async throws -> DeletionResult
    var session: AsyncStream<Session?> { get }
}
```

**Acceptance criteria**
- [ ] Tokens stored in Keychain (`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`); cleared on logout and deletion.
- [ ] In-app account deletion meets App Store Review Guideline 5.1.1(v): easy to find in Settings, deletes the account (not just deactivates it), and explains anything kept for legal reasons.
- [ ] Email + password only in v1. Adding any third-party sign-in later also requires Sign in with Apple (record a decision before doing so).

### 7.3 Content policy gate (mirrors 6.3)

```swift
protocol PolicyRepository {
    func current() async throws -> Policy
    var acceptedVersion: String? { get }
    func accept(version: String) async throws
}
```

### 7.4 Capture (mirrors 6.4)

- AVFoundation in-app capture (`in_app_camera`); PhotosUI picker (`gallery`).

**Acceptance criteria**
- [ ] HEIC originals uploaded unmodified (sha256 test).
- [ ] Picker imports read location metadata only with the needed photo-library permission; otherwise `source: none`.

### 7.5 On-device analysis (mirrors 6.5)

```swift
protocol IncidentAnalyzer {
    func analyze(image: CGImage, orientation: CGImagePropertyOrientation, claimText: String?) async throws -> DeviceResult
}
enum Preprocess { static func tensor(from image: CGImage, orientation: CGImagePropertyOrientation) -> [Float] }
enum Heatmap { static func boxes(_ heatmap: [Float], width: Int, height: Int, threshold: Float, maxBoxes: Int) -> [Box] }
enum ClaimClassifier { static func predict(model: ClaimModel, text: String) -> [String: Float] }
enum Rationale { static func build(/* same inputs as Python/Kotlin */) -> String }
```

**Acceptance criteria**
- [ ] Parity tests pass on the same Phase 2–3 test vectors used by Android.
- [ ] Cross-platform check: for every test vector, iOS and Android outputs agree within tolerance and rationale strings match exactly.

### 7.6 Offline queue and upload (mirrors 6.6)

```swift
protocol ReportQueue { func enqueue(_ report: PendingReport) async throws -> UUID }
protocol Attestor { func token(nonce: String, requestHash: Data) async throws -> String? }  // DCAppAttestService
```

**Acceptance criteria**
- [ ] Uses background `URLSession` so uploads continue after the app is suspended.
- [ ] App Attest key generated once per install and stored in Keychain; assertions per upload bind the account id and photo sha256.

### 7.7 Report card (mirrors 6.7)

### 7.8 Map (mirrors 6.8)

**Acceptance criteria**
- [ ] VoiceOver labels on dots and bottom sheet; Dynamic Type supported in the bottom sheet.

### 7.9 Reviewer mode (mirrors 6.9)

### 7.10 Performance and size budgets (mirrors 6.10)

**Acceptance criteria** (a recent mid-range iPhone, e.g. iPhone SE 3rd gen class)
- [ ] Bundled models ≤ 80 MB; analysis p50 ≤ 1.5 s, p95 ≤ 3 s.

## Agent notes

- **App Attest does not work in the Simulator.** Use dev attestation mode there and check `DCAppAttestService.shared.isSupported`.
- iPhone photos are HEIC by default; keep them as-is for upload.
- Large app downloads over cellular may prompt the user; another reason to keep models small.
- App Store uploads must be built with a current Xcode/iOS SDK (Xcode 26 or later since April 2026); use a CI runner image that provides it.
- Check ExecuTorch's iOS docs for current Swift Package/framework integration steps.

## Out of scope

Android changes (raise a decision record if parity reveals an Android bug), safety-officer tools (Phase 8), server-delivered model updates (v2).

## Definition of done

All mirrored criteria checked, cross-platform parity report in `eval/reports/parity/`, signed development build installable on a test device (if account available).
