# iVouch — Development Plan

Incident photo analyzer: users photograph incidents (natural disasters, car crashes). The software answers:
1. Is this photo likely real vs. manipulated / AI-generated / miscontextualized?
2. What incident(s) does it show, and how severe?

> Authenticity output is probabilistic and requires human review. Never present it as certain.

**Architecture: phone-first.** Small image models run on the phone for an instant result that also works offline. A thin server verifies every result, runs the authenticity checks, stores, de-duplicates, corroborates, maps and queues reports for human review. Large models are called only for rare escalations.

**Build approach:** coding agents implement the system in phases. Each phase has its own spec in [`specs/`](specs/) (see §8).

## 1. Product Scope

### In scope (v1)
- **Accounts required for everyone.** No anonymous submissions. Email + password signup with email verification, a minimum-age gate at signup (default 18+, see §11), and account deletion from inside the apps and on the web.
- One RGB photo per report from native **Android (Kotlin)** and **iOS (Swift)** apps, plus a web upload page. In-app camera capture is preferred; gallery and web uploads are allowed but carry fewer authenticity signals.
- Optional short claim text with each photo, handled by a small text classifier.
- **On-device analysis (works offline):** incident type(s), severity, damage-region mask, content-policy check. The server re-checks every result.
- Incident classification (multi-label): car crash, fire, flood, storm damage, earthquake damage, none-of-these
- Severity estimate: minor / moderate / severe + short templated rationale (e.g. "Flood (91%). Water region covers ~46% of the image.")
- Authenticity signals: likely-real / needs-review / likely-manipulated + reasons
- **Content policy:** no real violence or gore, and no nudity or sexual content. A written policy is shown to users before their first upload; an on-device classifier blocks violating photos and the server re-checks.
- **Legal compliance (U.S.):** server-side hash matching against known child sexual abuse material (CSAM) with a restricted quarantine, one-year preservation and NCMEC reporting workflow; a public removal-request process for nonconsensual intimate images (TAKE IT DOWN Act). See §5.
- Human review queue for low-confidence and high-severity cases
- Mobile incident map: red dots on a real basemap for geolocated reports; tap dot → photo + summary bottom sheet
- English UI and reports

### Out of scope (v1, consider for v2)
- Automatic emergency dispatch or insurance claim decisions
- Reports without a photo
- Real-time video
- Audio notes, thermal / drone depth, multi-photo fusion
- Server-delivered model updates (v1 ships models inside app releases)
- Legal proof of authenticity

## 2. Architecture

```text
[Phone app: Android / iOS]
  sign up / log in (email verified, age gate) → content policy accepted
  in-app capture (or gallery import) + time, GPS if consented, device
        |
        v
[On-device pipeline]  ExecuTorch, offline-capable
  preprocess → DINOv3 ViT-S backbone → heads: incident (multi-label), severity, policy
  policy violation → block upload + show policy
  patch heatmap → box prompts → EfficientSAM / MobileSAM → damage mask
  claim text → small text classifier
  → instant report card + templated rationale
        |
        v   offline queue; uploads when connected
[Upload]  account token + ORIGINAL photo + capture metadata + device results + attestation token
        |
        v
[Server ingest: FastAPI + worker]
  verify account + attestation
  → CSAM hash match (match → restricted quarantine, preserve 1 year, NCMEC report; stop)
  → policy re-check (violation → discard image)
  → re-run image models on CPU (ONNX Runtime) → compare with device result
  → face + plate detection → blurred copy + thumbnail for all public use
  → original encrypted, reviewer-only, auto-deleted after retention period
        |
        +---> [Authenticity service]
        |       EXIF / time / GPS checks, C2PA content credentials,
        |       capture source (in-app vs. gallery vs. web), device attestation,
        |       internal duplicates (pHash + embeddings in pgvector),
        |       web reverse image search, corroboration (same place / time / type),
        |       forensic score → fusion → likely-real / needs-review / likely-manipulated
        |
        +---> [Escalation, rare]  Llama 4 Scout (vision) via provider interface
        |       context check + written rationale for low-confidence / high-severity / disputed cases
        v
[Report store + review queue]  PostgreSQL + PostGIS + pgvector, S3-compatible object storage
[Trust & safety]  removal requests (48-hour target, copies found via duplicate search),
                  quarantine + NCMEC reports (safety-officer role only)
        |
        v
[Map serving]  GET /v1/incidents (GeoJSON for bbox) → native MapView: red dots, tap → thumbnail + summary sheet
```

**Why originals are uploaded:** authenticity checks (C2PA signatures, EXIF, forensics) need the unedited file. Blurring on the phone would itself be an edit. Instead the server blurs faces and plates immediately and only reviewers can open the encrypted original, with every access audit-logged.

## 3. Models

| Model | Runs on | Role | Approx. size |
|---|---|---|---|
| DINOv3 ViT-S/16 (distilled) | phone + server | Shared backbone: embeddings for all heads, duplicate search, damage heatmap | ~20–25 MB (int8) |
| Linear / small MLP heads | phone + server | Incident (multi-label), severity, content policy (violence/gore, nudity/sexual), damage heatmap | < 1 MB |
| EfficientSAM (Ti/S) or MobileSAM | phone (+ server for re-render) | Damage mask from box prompts | ~10–40 MB |
| TF-IDF + logistic regression (JSON weights) | phone + server | Claim text → incident types | ≤ 5 MB |
| MediaPipe Face Detector | server | Face blurring | < 1 MB |
| YOLOX-Nano (fine-tuned) | server | License-plate blurring | ~3–6 MB |
| Forensic detector | server | AI-generation / manipulation score (one signal, never a verdict) | TBD in Phase 5 |
| CSAM hash matching (PhotoDNA or Cloudflare CSAM Scanning Tool) | server, external service | Match uploads against known CSAM hashes | external |
| Llama 4 Scout (vision) | server, via hosted API or self-hosted GPU | Escalation only: context check + written rationale | external |
| ImageBind | — | Deferred to v2 (audio, thermal, depth, cross-modal search) | — |

**Phone model budget:** ≤ 80 MB total.

**Changes from the earlier plan:** Llama 3.2 Vision 11B/90B replaced by Llama 4 Scout for escalations only. DINOv2 replaced by DINOv3. SAM 2 replaced by EfficientSAM/MobileSAM on the phone (SAM 3, at ~848M parameters, is too large for phones). Llama Guard 3 Vision removed (not replaced by Llama Guard 4: it is built for moderating chatbot conversations, needs a GPU, and isn't the standard tool for detecting abuse imagery). Violence, gore, nudity and sexual content are handled by the content policy and its classifier; known CSAM by hash matching (§5).

### 3.1 DINOv3
- Self-supervised Meta vision backbone with strong frozen features. The ViT-S/16 variant is distilled from the 7B model and small enough for phones.
- Use: frozen backbone; train small heads on its embeddings. One forward pass feeds every head.
- Practice: store `embedding_version` with every record; re-index when the backbone changes. DINOv3 has its own license (not Apache 2.0) and gated downloads.

### 3.2 Damage localization
- DINOv3 patch tokens → heatmap per incident class → boxes → EfficientSAM/MobileSAM masks.
- Masks are for reviewers and the rationale (e.g. damaged area fraction), not for automatic decisions.

### 3.3 Content-policy classifier
- Multi-label head on the shared embedding (~0 MB extra on the phone) with two categories: `violence_gore` and `nudity_sexual`. Blocks uploads on the phone; the server re-runs it and discards violating images, keeping only a hash.
- Tuned for high recall on both categories while keeping false positives low on ordinary crash and disaster scenes.
- Blocking nudity/sexual content on the phone keeps most such material from ever reaching the server. It does not replace server-side CSAM hash matching (§5).

### 3.4 Escalation (Llama 4 Scout)
- Called only for low-confidence, high-severity, device/server-disagreement or reviewer-escalated cases, under a daily budget.
- Receives the **blurred** image. Produces a caption, rationale and a context check (does the claim match the scene, location and historical weather?).
- Do not use for: content-policy decisions, final authenticity verdicts.

### 3.5 Runtimes
- Phone: ExecuTorch (one PyTorch export path for both Android and iOS).
- Server: ONNX Runtime on CPU; no GPU needed except for optional self-hosted escalation.

### 3.6 ImageBind (v2 only)
- Meta multimodal embedding model binding image/video, text, audio, depth, thermal and IMU into one representation space.
- Use later: voice-note + photo search, thermal hotspot correlation, drone depth fusion.
- Why deferred: no v1 benefit for single RGB photos; adds data and eval cost.

## 4. Authenticity Layer (Real vs. Fake)

No model here is a reliable fake detector on its own. The server combines independent signals:

1. **Provenance and integrity:** file hash, EXIF consistency, timestamp/GPS plausibility vs. device-reported values, editing-software tags.
2. **C2PA content credentials:** valid / invalid / absent; a manifest declaring a generative-AI tool is a strong signal.
3. **Capture source and device attestation:** in-app camera captures with valid Play Integrity / App Attest tokens are the most trustworthy. Gallery and web uploads simply lack these signals; they aren't treated as suspicious on their own.
4. **Internal duplicates:** pHash + DINOv3 embedding search over past reports catches re-uploads presented as new incidents.
5. **Web reverse image search:** catches old photos from the internet reposted as new (the most common kind of fake). Uses the blurred copy.
6. **Corroboration:** independent reports (distinct verified accounts on distinct devices) of the same incident type near the same place and time.
7. **Forensic score:** AI-generation/manipulation detector, calibrated on held-out real photos; one input among many.
8. **Context check (escalation only):** does the claim match the scene, location and weather?
9. **Fusion rule:** combine signals into likely-real / needs-review / likely-manipulated with reasons. High-severity or low-confidence cases always go to human review.
10. **UX wording:** show "signals observed" and confidence; never "proven fake/real".

## 5. Trust, Safety and Legal Compliance (U.S.)

> Not legal advice. Have a lawyer review this section before any public launch.

### 5.1 Accounts and age
- Every user (submitter, reviewer, staff) has an account. Roles: `user`, `reviewer`, `safety_officer`, `admin`.
- Signup: email + password (argon2id), email verification required before the first upload, date of birth checked against `min_age` (default 18). Under-age signups are rejected and their date of birth is not stored; only "age confirmed at signup" is kept. Setting the minimum at 13 or above keeps COPPA out of scope; 18 also fits the incident content.
- **Account deletion** from inside both apps and from a web page (required by the App Store and Google Play). Deletion removes the account, its reports and media, except items under a legal preservation hold (§5.2).
- Rate limits, policy acceptance, repeat-violation suspension and corroboration all key on the account.

### 5.2 Child sexual abuse material (18 U.S.C. § 2258A, as expanded by the REPORT Act, 2024)
- A provider that gains actual knowledge of apparent CSAM, child sex trafficking or enticement of a minor on its service must report it to NCMEC's CyberTipline. The law doesn't require proactive scanning, but iVouch hash-matches every upload anyway.
- **Hash matching:** every upload is checked on the server against known-CSAM hashes (PhotoDNA, or Cloudflare's CSAM Scanning Tool) before any other processing.
- **Reviewer flag:** reviewers and safety staff can mark any item as suspected CSAM, which removes it from their view and moves it to quarantine. This is how "actual knowledge" from human review is captured.
- **Quarantine, not deletion:** matched or flagged items go to a separate encrypted bucket with its own key. Only the `safety_officer` role can access it, every access is audit-logged, and items are preserved for **one year** under a legal hold that retention jobs and account deletion cannot override. Storage is secured consistent with the NIST Cybersecurity Framework.
- **Reporting:** a safety officer reviews the prepared report and submits it to NCMEC. The system never submits automatically in development or test environments.
- The uploading account is suspended. The user sees only a generic "upload could not be accepted" message.
- Quarantined items never enter training data, eval sets, reviewer queues, logs, thumbnails or backups outside the quarantine store.
- Agents never collect, download or generate such material. Tests use provider-supplied test hashes or a mock that "matches" a benign fixture.

### 5.3 Nonconsensual intimate images (TAKE IT DOWN Act; compliance date May 19, 2026; enforced by the FTC)
- A public, plain-language removal-request page, linked from the apps, the website footer and the map, that does not require an account.
- Requests include: the requester's name and contact, a physical or electronic signature, information to locate the content, and a good-faith statement that it was shared without consent.
- Valid requests are actioned within **48 hours** (internal target: 24 hours). The content is removed, and identical copies are found with the duplicate search (pHash + embeddings) and removed too.
- Requests, decisions and removal times are audit-logged. A dashboard shows open requests and time remaining.
- Because nudity and sexual content are already blocked, such requests should be rare, but the process is legally required regardless.

### 5.4 Other policies
- Content policy and terms of service are versioned; users re-accept when they change.
- Violent/gory or nudity/sexual uploads that aren't CSAM are discarded (hash, time, category and account id kept). Repeated violations suspend the account (threshold in `thresholds.yaml`).

## 6. Data and Labeling Plan

**Seed datasets**

| Dataset | Use |
|---|---|
| Incidents1M | Main incident-classification data (car accidents, floods, fires, storms, earthquakes, etc.) |
| CrisisMMD | Damage-severity labels, extra disaster images, claim-text training data, partial policy positives |
| xBD | Registered only. Satellite imagery doesn't match phone photos; not used for v1 training unless shown to help |

Plus: user-provided/approved violence/gore and adult nudity/sexual-content sets for the policy classifier, a few hundred car-crash images labeled for severity (no public set has this), ~200 images with damage masks, a license-plate dataset, and held-out real phone photos for the false-accusation evaluation. See §8.2.

- Labels per photo: incident types, severity, policy violation, manipulated/clean (if known), duplicate group id.
- Licenses recorded per image; these datasets are mostly research-licensed, so commercial use needs review.
- Location record per report: `lat, lng, accuracy_m, source (exif-gps | device-gps | manual-pin | claim-text | none), consented (bool)`. Reports with `source: none` or `consented: false` are excluded from map queries.
- Reviewer workflow: two annotators + adjudicator for severity and authenticity edge cases. Reviewer corrections are exported as new training labels.
- **Privacy:** originals encrypted at rest, reviewer-only, deleted after `RAW_RETENTION_DAYS`; all public images have faces/plates blurred and EXIF stripped. For map display, exact coordinates stay server-side; non-reviewer roles get a display coordinate jittered ~100–500 m (deterministic per report so it can't be averaged out). Reviewers may see exact pins with audit logging.
- **Policy-rejected images are never stored**; only a hash, time, category and account id are kept. The one exception is CSAM matches or flags, which are quarantined and preserved as required by law (§5.2) and never used as data.
- Version: dataset version + embedding version + model checkpoint recorded on every training run.

## 7. API / UX Outline

Minimal v1 API (full contract in `contracts/openapi.yaml`, Phase 0). Every endpoint requires a logged-in account unless marked *public*.

- Accounts: `POST /v1/auth/register` *(public)*, `POST /v1/auth/verify-email` *(public)*, `POST /v1/auth/login` *(public)*, `POST /v1/auth/refresh` *(public)*, `POST /v1/auth/logout`, `POST /v1/auth/password-reset` + `/confirm` *(public)*, `GET /v1/account`, `DELETE /v1/account`.
- `GET /v1/policy` *(public)* — current content policy, terms and removal-request notice + versions; `POST /v1/policy/accept`.
- `POST /v1/attestation/challenge` — single-use nonce for Play Integrity / App Attest.
- `POST /v1/analyze` — original photo + metadata (`capture_metadata`, `location`, optional `claim_text`, `device_result`, `client_report_id`, attestation token) → `202 {report_id}`. Requires a verified email and the current policy accepted. Idempotent on `client_report_id` + account for offline retries.
- `GET /v1/reports/{id}` — incident types, severity, rationale, masks, authenticity result + reasons, confidence, `location { lat_display, lng_display, accuracy_m, source, verified }`, `thumbnail_url`, `photo_url` (blurred). Exact coordinates and originals are reviewer-only.
- `GET /v1/review-queue` — reviewer only.
- `POST /v1/reviews/{id}` — reviewer verdict: confirm / correct / escalate / flag suspected CSAM.
- `POST /v1/takedown-requests` *(public)* — TAKE IT DOWN removal request; `GET /v1/takedown-requests/{id}` (requester token) for status.
- Safety-officer only: takedown queue and actions, quarantine list, NCMEC report preparation and status.
- `GET /v1/incidents?bbox=minLng,minLat,maxLng,maxLat&zoom={z}&types={csv}&severity={csv}&since={iso8601}&limit={n}` — GeoJSON `FeatureCollection` of map dots in the viewport. Each feature: `id, geometry (Point, display coordinates), properties { incident_type, severity, authenticity, confidence, created_at, thumbnail_url }`. `limit` default 500, max 2000; `truncated: true` tells the client to zoom in. Excludes non-consented, ungeolocated and policy-rejected reports; `likely-manipulated` excluded unless `include_flagged=true` (reviewer only).

Example `GET /v1/incidents` response:

```json
{
  "type": "FeatureCollection",
  "truncated": false,
  "features": [
    {
      "type": "Feature",
      "id": "rep_123",
      "geometry": { "type": "Point", "coordinates": [-71.0589, 42.3601] },
      "properties": {
        "incident_type": "car_crash",
        "severity": "moderate",
        "authenticity": "likely-real",
        "confidence": 0.82,
        "created_at": "2026-10-27T12:00:00Z",
        "thumbnail_url": "/thumbs/rep_123.jpg"
      }
    }
  ]
}
```

Geo-index: `GEOGRAPHY(Point, 4326)` in PostGIS with a GIST index; bbox + filter query must stay < 300 ms p95 at 1M reports.

**Mobile UX (native)**
- First run: sign up or log in (age gate, email verification), then the content policy screen; both are required before capture. Capture and on-device analysis work offline once logged in.
- Settings: account, delete account, content policy, removal-request page link.
- Capture → instant on-device report card (or policy block with explanation) → queued upload → server-verified report card → reviewer actions (reviewers only).
- Always show uncertainty, "needs human review" state and "Not for emergencies: call your local emergency number".

**Mobile map (native)**
- MapLibre Native (Android/iOS) with free OSM-derived vector tiles (OpenFreeMap or self-hosted); provider behind config for a later Mapbox/Google swap.
- Full-screen map centered on device location (with permission) else last viewport; red-dot markers (≥ 24 dp hit area) with clustering; cluster badge shows count, tap zooms in.
- Tap dot → bottom sheet: thumbnail, `incident_type — severity`, authenticity banner, time, confidence; `View details` and reviewer actions.
- Filters: incident type, severity, `24h / 7d / 30d`, `likely-manipulated` hidden by default; reflected in query params.
- Reports without location appear in a list with `Add location (manual pin)`, never as dots.
- Performance: initial dots < 2 s on 4G, pan/zoom refetch debounced 300 ms, thumbnails lazy-loaded + cached.
- Accessibility: dots have screen-reader descriptions ("car crash, moderate"); severity is never shown by color alone.

**Web (server-rendered)**
- Account pages (signup, login, verify email, password reset, delete account), upload page (server-side analysis, policy acknowledgment required), reviewer console (queue, report detail, signals, original access with audit log, review actions), public removal-request page, and a restricted safety console (takedown queue, quarantine, NCMEC reports).

## 8. Build Phases

Work is done by coding agents. There is no calendar; phases are ordered by dependency, and each has a spec with objectives, acceptance criteria, functions and agent notes. Agent roles and rules live in [`agents/orchestrator.md`](agents/orchestrator.md) and [`agents/builder.md`](agents/builder.md); per-spec logs in [`logs/`](logs/README.md).

| Phase | Spec | Why it's a separate phase | Depends on |
|---|---|---|---|
| 0 Foundations & contracts | [phase-0-foundations.md](specs/phase-0-foundations.md) | Freezes schemas, taxonomy, thresholds and conventions so later phases run in parallel | — |
| 1 Data pipeline & labels | [phase-1-data.md](specs/phase-1-data.md) | Long-running downloads + one license sign-off; produces fixed, versioned splits | 0 |
| 2 Core image models | [phase-2-core-models.md](specs/phase-2-core-models.md) | GPU work; produces the shared phone/server model + test vectors everything else tests against | 0, 1 |
| 3 Localization & privacy models | [phase-3-localization-privacy.md](specs/phase-3-localization-privacy.md) | Box/mask models with different labels and metrics; doesn't block the core model | 0, 1, 2 |
| 4 Backend core | [phase-4-backend.md](specs/phase-4-backend.md) | Different stack; owns accounts, ingest, CSAM quarantine and takedowns; starts early with stub models | 0 (+2, 3 for real models) |
| 5 Authenticity & escalation | [phase-5-authenticity.md](specs/phase-5-authenticity.md) | Highest-risk subsystem with external providers and its own strict eval | 0, 2, 4 |
| 6 Android app | [phase-6-android.md](specs/phase-6-android.md) | First client; reference behavior; buildable on Windows/Linux | 0, 2, 3, 4 |
| 7 iOS app | [phase-7-ios.md](specs/phase-7-ios.md) | Needs macOS/Xcode + Apple account; mirrors Android | 0, 2, 3, 4, 6 |
| 8 Web: accounts, upload, review & safety consoles | [phase-8-web-review.md](specs/phase-8-web-review.md) | Different surface and users; needs real authenticity signals | 4, 5 |
| 9 Hardening & pilot readiness | [phase-9-hardening.md](specs/phase-9-hardening.md) | Red-team, bias, load and abuse tests only mean something end to end | 4–8 |

### 8.1 Order and parallelism

```text
0 ──► 1 ──► 2 ──► 3
│           │     │
└──► 4 ◄────┴─────┘   (4 starts after 0 with stub models)
     │
     ├──► 5 ──► 8
     │
     └──► 6 ──► 7
               all ──► 9
```

Parallel tracks after Phase 0: **ML** (1 → 2 → 3) and **backend** (4). Once Phase 2 artifacts exist: 5 and 6 in parallel; then 7 and 8 in parallel; then 9. Allowed concurrent pairs: 1–4, 2–4, 3–4, 3–5, 5–6, 5–7, 6–8, 7–8. Every phase, including a parallel one, starts only when the user says `start phase N` (see `agents/orchestrator.md`).

### 8.2 Human inputs (provide up front so agents aren't blocked)

| Input | Phase |
|---|---|
| Exact Meta model IDs for each tier in `agents/models.yaml` | before 0 |
| Minimum age decision (default 18) | 0 (non-blocking) |
| Dataset access (Incidents1M, CrisisMMD) + license approval for intended use | 1 |
| Violence/gore and adult nudity/sexual-content image sets (licensed or approved; adults only) for the policy classifier | 1 |
| A few hundred car-crash images labeled minor/moderate/severe | 1 |
| DINOv3 license acceptance + download token | 2 |
| GPU access (one modern GPU) | 2, 3 |
| ~200 images with damage-region masks; approved license-plate dataset; face eval images | 3 |
| Email-sending provider (for verification and password reset) | 4 (mock in dev) |
| CSAM hash-matching access (PhotoDNA application or Cloudflare CSAM Scanning Tool) | 4 (mock in dev) |
| NCMEC CyberTipline registration as an electronic service provider | 4, 9 (mock in dev) |
| Named safety officer(s) and takedown contact address | 8, 9 |
| Google Play Integrity setup (Cloud project, Play Console, service account) | 5, 6 |
| Apple Developer account (Team ID, bundle ID) for App Attest | 5, 7 |
| Reverse image search provider + API key | 5 |
| Escalation model host + key (Llama 4 Scout) or GPU to self-host | 5 |
| Forensic training data or approval/budget to generate AI images | 5 |
| Held-out real, consented phone photos (≥ 300 ideal) for false-accusation eval | 5 |
| Physical mid-range Android phone and iPhone (or a device cloud) | 6, 7 |
| macOS with Xcode (Mac or macOS CI runner) | 7 |
| Hosting choice, privacy/legal review, commercial license review, pilot partner | 9 |
| Approval of the content policy text | 0 (non-blocking) |

Phase 0 creates `docs/HUMAN_INPUTS.md` to track these.

### 8.3 Conventions for agents (applies to every phase)

- **Contracts first:** `contracts/` and `config/` are the source of truth; changing them requires a version bump, updated examples and a decision record.
- **Don't stop for reversible decisions:** record them in `docs/decisions/` and continue. Stop only for the user-only decisions in `agents/orchestrator.md` §9, irreversible actions, or missing human inputs with no mock.
- **Missing human input:** use the mock/fallback named in the phase spec, log it in `docs/BLOCKED.md`, and continue with the rest of the phase.
- **Acceptance criteria are tests:** an objective is done only when its criteria pass via a command (`make check`, `./gradlew check`, `xcodebuild test`, eval scripts). **Lowering any numeric target, including ones marked "initial", needs the user's approval**; raising one needs only a decision record.
- **No magic numbers:** thresholds live in `config/thresholds.yaml`.
- **No secrets in git;** every env var listed in `.env.example`.
- **Commits:** only the orchestrator commits, once per accepted objective and once per completion report, with the phase name, a one-paragraph summary and the exact models used. Agents never push.
- **Licenses:** record the license of every dataset and model; avoid AGPL dependencies (e.g. Ultralytics YOLO) unless approved.
- **Never collect, download, generate or open material that could be CSAM.** Policy-classifier data comes only from user-approved adult sources. Hash-matching is tested only with provider test hashes or a mock. If anything suspicious appears in any dataset, stop, don't copy or view it, and record it in `docs/BLOCKED.md` for the user.
- **Never submit real NCMEC reports or contact outside organizations.** Agents build the workflow; humans operate it.

## 9. Test Plan

- Unit: preprocessing (Python/Kotlin/Swift parity), provenance and C2PA checks, attestation verifiers, fusion rules, API schemas, policy gating, auth and roles
- Model evals: held-out incident set; macro-F1 + calibration, not just top-1; severity weighted kappa per incident type
- Policy eval: recall per category (violence/gore, nudity/sexual); false-positive rate on ordinary crash/disaster images
- Accounts: signup/age gate, email verification, account deletion (incl. legal-hold exceptions), role-based access
- Compliance: hash-match → quarantine flow (mock), legal hold survives retention and account deletion, takedown request → removal of content and copies within the 48-hour window (frozen clock)
- Parity: quantized phone models vs. server reference on shared test vectors; Android vs. iOS outputs
- Segmentation eval: IoU on damage masks + reviewer correction rate
- Retrieval eval: duplicate recall@k on synthetic transforms
- Authenticity eval: false-accusation rate on held-out real photos; forensic AUC incl. held-out generators
- E2E: capture → offline queue → upload → report → review verdict; chaos cases (no GPS, stripped EXIF, re-encoded image, HEIC, offline then reconnect, provider timeouts)
- Map eval: bbox query latency (< 300 ms p95), dot tap → popup on mid-range Android (< 2 s on 4G), clustering correctness, manual-pin fallback
- On-device performance: analysis p50 ≤ 1.5 s, models ≤ 80 MB

## 10. Risks and Issues

1. **Fake detection is never certain.** Adversarial edits and new generators degrade detectors. Mitigation: many independent signals, probabilistic wording, mandatory human review for high-severity cases.
2. **False accusations.** Calling a real victim's photo "fake" causes harm. Mitigation: false-accusation rate as a hard acceptance criterion, conservative thresholds, audit trail, corrections flow.
3. **Content policy errors.** Over-blocking would stop legitimate crash/disaster reports; under-blocking lets violent or sexual content through. Mitigation: hard-negative evaluation on crash scenes, server re-check, reviewer removal, takedown runbook.
4. **Phone results can be tampered with.** A modified app can send fake device results. Mitigation: server re-runs all models; attestation; device results are only advisory.
5. **Legal non-compliance (CSAM reporting, TAKE IT DOWN).** Missed reports, deleted evidence or late removals carry large fines. Mitigation: hash matching on every upload, quarantine with legal holds, reviewer flag path, 48-hour takedown dashboard, legal review before launch.
6. **Fake accounts.** Required accounts can still be mass-created to fake corroboration or evade suspensions. Mitigation: email verification, device attestation, per-account and per-device limits, corroboration counted across distinct accounts and devices.
7. **Privacy and legal exposure.** Faces, plates, GPS, account data; originals are uploaded. Mitigation: consent, server-side blurring, encrypted reviewer-only originals with retention limits and audit logs, jittered public coordinates, minimal account data, regional legal review.
8. **Liability for wrong triage.** Underestimated severity could delay help. Mitigation: no auto-dispatch in v1; "not for emergency use" labeling; escalation defaults.
9. **Bias and generalization.** Models may underperform on underrepresented regions, night scenes or low-end phones. Mitigation: stratified evals, targeted data collection.
10. **Thin labels for car-crash severity.** No public dataset covers it. Mitigation: human-labeled set; crashes routed to review until it exists.
11. **On-device constraints.** App size, battery and slow low-end phones. Mitigation: ≤ 80 MB model budget, int8 quantization, performance criteria on mid-range devices.
12. **Platform dependencies.** iOS needs macOS/Xcode; attestation needs Google/Apple accounts. Mitigation: listed as up-front human inputs; dev-mode mocks.
13. **Data and model licensing.** Seed datasets are mostly research-licensed; DINOv3 and Llama have custom licenses. Mitigation: license registry, commercial review before launch, takedown process.
14. **Cost.** Escalations and reverse image search cost money per call. Mitigation: phone-first design, daily budgets, caching by hash.

## 11. Open Decisions

- **Minimum age:** default 18 (`min_age` in `config/policy.yaml`). Must not go below 13 without a COPPA review.
- **CSAM hash-matching provider:** PhotoDNA (application required) or Cloudflare CSAM Scanning Tool (requires serving images through Cloudflare); check current eligibility.
- **Retention period** for encrypted originals (`RAW_RETENTION_DAYS`). Legal holds (§5.2) override it.
- **Providers:** reverse image search, escalation model host, email sending, production hosting.
- **Sign-in options:** v1 is email + password only. Adding Google or other third-party sign-in later also requires offering Sign in with Apple on iOS.

## 12. Sources

Meta models
- DINOv3: https://github.com/facebookresearch/dinov3
- Llama 4: https://ai.meta.com/blog/llama-4-multimodal-intelligence/
- EfficientSAM: https://github.com/yformer/EfficientSAM
- ExecuTorch: https://pytorch.org/executorch/
- ImageBind: https://ai.meta.com/blog/imagebind-six-modalities-binding-ai/

Other components
- MobileSAM: https://github.com/ChaoningZhang/MobileSAM
- MediaPipe Face Detector: https://ai.google.dev/edge/mediapipe/solutions/vision/face_detector
- YOLOX: https://github.com/Megvii-BaseDetection/YOLOX
- C2PA: https://c2pa.org
- Play Integrity API: https://developer.android.com/google/play/integrity
- App Attest (DeviceCheck): https://developer.apple.com/documentation/devicecheck
- MapLibre: https://maplibre.org
- OpenFreeMap: https://openfreemap.org
- Open-Meteo: https://open-meteo.com

Legal and compliance
- REPORT Act (Public Law 118-59): https://www.congress.gov/118/plaws/publ59/PLAW-118publ59.htm
- REPORT Act summary (Wilson Sonsini): https://www.wsgrdataadvisor.com/2024/05/new-minor-safety-obligations-for-online-services-report-act-expands-child-sexual-exploitation-reporting-requirements/
- TAKE IT DOWN Act for covered platforms (Reed Smith): https://www.reedsmith.com/our-insights/blogs/viewpoints/102ms5e/covered-platforms-are-you-ready-to-take-it-down/
- NCMEC CyberTipline: https://report.cybertip.org/
- Microsoft PhotoDNA: https://www.microsoft.com/photodna
- Cloudflare CSAM Scanning Tool: https://blog.cloudflare.com/the-csam-scanning-tool

Datasets
- Incidents1M: http://incidentsdataset.csail.mit.edu/
- CrisisMMD: https://crisisnlp.qcri.org/crisismmd
- xBD / xView2: https://xview2.org/dataset

Verify each link and license before relying on it.
