# iVouch — Development Plan

Incident photo analyzer: users photograph incidents (natural disasters,
car crashes). The software answers:

1. Is this photo likely real vs. manipulated / AI-generated / miscontextualized?
2. What incident(s) does it show, and how severe?

> Authenticity output is probabilistic and requires human review.
> Never present it as certain.

**Architecture: Android-first.** Small image models run on the phone for
an instant result that also works offline. A thin server verifies every
result, runs the authenticity checks, stores, de-duplicates,
corroborates, maps and queues reports for human review. Large models are
called only for rare escalations.

**Scope:** v1 ships **Android only**. iOS is removed entirely (no Swift
app, no Xcode/macOS CI, no App Attest, no Sign in with Apple obligations)
to cut build and review resources. An iOS client can be added in v2
against the same contracts. All parity requirements are Python <-> Kotlin
only.

**Build approach:** coding agents implement the system in phases. Each
phase has its own spec in `specs/` (see §8). Agents are dispatched in
Muse per `AGENTS.md` §3 (tool mapping) and `agents/models.yaml`.
Native sub-agents always inherit the session model/effort — no spawn
parameter can change that. A builder gets an assigned model only via
workflow dispatch (`muse.workflow` -> `host.agent({model, effort})`),
only for a brief type with a non-null tier in `agents/models.yaml`, and
only once the user has set `tiers_verified: true` there. Until then
every builder inherits. Procedure: `agents/orchestrator.md` §2.

## 1. Product Scope

### In scope (v1)

- **Accounts required for everyone.** No anonymous submissions. Email +
  password signup with email verification, a minimum-age gate at signup
  (default 18+, see §11), and account deletion from inside the app and
  on the web.
- One RGB photo per report from the native **Android (Kotlin)** app,
  plus a web upload page. In-app camera capture is preferred; gallery
  and web uploads are allowed but carry fewer authenticity signals.
- Optional short claim text with each photo, handled by a small text
  classifier.
- **On-device analysis (works offline):** incident type(s), severity,
  damage-region mask, content-policy check. The server re-checks every
  result.
- Incident classification (multi-label): car crash, fire, flood, storm
  damage, earthquake damage, none-of-these.
- Severity estimate: minor / moderate / severe + short templated
  rationale (e.g. "Flood (91%). Water region covers ~46% of the image.")
- Authenticity signals: likely-real / needs-review /
  likely-manipulated + reasons.
- **Content policy:** no real violence or gore, and no nudity or sexual
  content. A written policy is shown before the first upload; an
  on-device classifier blocks violating photos and the server re-checks.
- **Legal compliance (U.S.):** server-side CSAM hash matching with a
  restricted quarantine, one-year preservation and NCMEC reporting
  workflow; a public removal-request process for nonconsensual intimate
  images (TAKE IT DOWN Act). See §5.
- Human review queue for low-confidence and high-severity cases.
- Mobile incident map: red dots on a real basemap for geolocated
  reports; tap dot → photo + summary bottom sheet.
- English UI and reports.

### Out of scope (v1, consider for v2)

- iOS app (contracts stay platform-neutral so it can be added later
  without a contract break).
- Automatic emergency dispatch or insurance claim decisions.
- Reports without a photo. Real-time video. Audio notes, thermal/drone
  depth, multi-photo fusion.
- Server-delivered model updates (v1 ships models inside app releases).
- Legal proof of authenticity.

## 2. Architecture

```text
[Android app]
  sign up / log in (email verified, age gate) → content policy accepted
  in-app capture (or gallery import) + time, GPS if consented, device
        |
        v
[On-device pipeline]  ExecuTorch, offline-capable
  preprocess → DINOv3 ViT-S backbone → heads: incident, severity, policy
  policy violation → block upload + show policy
  patch heatmap → box prompts → EfficientSAM / MobileSAM → damage mask
  claim text → small text classifier
  → instant report card + templated rationale
        |
        v   offline queue; uploads when connected
[Upload]  account token + ORIGINAL photo + capture metadata +
          device results + Play Integrity attestation token
        |
        v
[Server ingest: FastAPI + worker]
  verify account + attestation
  → CSAM hash match (match → restricted quarantine, preserve 1 year,
    NCMEC report; stop)
  → policy re-check (violation → discard image)
  → re-run image models on CPU (ONNX Runtime) → compare with device
  → face + plate detection → blurred copy + thumbnail for public use
  → original encrypted, reviewer-only, auto-deleted after retention
        |
        +---> [Authenticity service]
        |       EXIF / time / GPS checks, C2PA content credentials,
        |       capture source, Play Integrity attestation,
        |       internal duplicates (pHash + embeddings in pgvector),
        |       web reverse image search, corroboration,
        |       forensic score → fusion → likely-real / needs-review /
        |       likely-manipulated
        |
        +---> [Escalation, rare]  Llama 4 Scout (vision) via provider
        |       context check + written rationale for low-confidence /
        |       high-severity / disputed cases
        v
[Report store + review queue]  PostgreSQL + PostGIS + pgvector,
                               S3-compatible object storage
[Trust & safety]  removal requests (48-hour target, copies found via
                  duplicate search), quarantine + NCMEC reports
                  (safety-officer role only)
        |
        v
[Map serving]  GET /v1/incidents (GeoJSON for bbox) → Android MapView:
               red dots, tap → thumbnail + summary sheet
```

**Why originals are uploaded:** authenticity checks (C2PA signatures,
EXIF, forensics) need the unedited file. Instead the server blurs faces
and plates immediately and only reviewers can open the encrypted
original, with every access audit-logged.

## 3. Models

| Model | Runs on | Role | Approx. size |
|---|---|---|---|
| DINOv3 ViT-S/16 (distilled) | phone + server | Shared backbone: embeddings, duplicate search, damage heatmap | ~20–25 MB (int8) |
| Linear / small MLP heads | phone + server | Incident, severity, content policy, damage heatmap | < 1 MB |
| EfficientSAM (Ti/S) or MobileSAM | phone (+ server re-render) | Damage mask from box prompts | ~10–40 MB |
| TF-IDF + logistic regression (JSON) | phone + server | Claim text → incident types | ≤ 5 MB |
| MediaPipe Face Detector | server | Face blurring | < 1 MB |
| YOLOX-Nano (fine-tuned) | server | License-plate blurring | ~3–6 MB |
| Forensic detector | server | AI-generation / manipulation score (one signal, never a verdict) | TBD in Phase 5 |
| CSAM hash matching (PhotoDNA or Cloudflare) | server, external | Match against known CSAM hashes | external |
| Llama 4 Scout (vision) | server, via API or self-hosted | Escalation only | external |
| ImageBind | — | Deferred to v2 | — |

**Phone model budget:** ≤ 80 MB total. **Artifacts** are stored outside
git under `ARTIFACT_ROOT` (default `data/artifacts/`), registered with
sha256 in `registry/models.yaml`; test vectors reference artifact
versions, never committed weights.

**Provisional mini-models.** The v1 heads are deliberately small —
linear/MLP heads on a frozen backbone, a TF-IDF text model — so a
usable first artifact does not need full-scale training. When GPU
time, dataset scale or a licence sign-off is missing, Phases 2–3 may
train on the data and compute actually available (a CPU/GPU
subsample, research-licensed data), register the artifact with
`provisional: true`, set untrained categories to `unavailable`, and
record the unmet metric criteria as open. The objective is then
BUILD-ACCEPTED (orchestrator §7): downstream phases integrate the
artifact behind the stub fallback, and no metric, launch or pilot
claim may rest on it until the criteria pass on the real inputs.

### 3.1–3.6 Notes

- **DINOv3:** self-supervised Meta backbone, frozen; train small heads on
  embeddings. One forward pass feeds every head. Store
  `embedding_version` on every record. DINOv3 has its own license (not
  Apache 2.0) and gated downloads; access is checked with
  `python tasks.py env-check --names HF_TOKEN` (present/missing only).
- **Damage localization:** patch tokens → per-class heatmap → boxes →
  EfficientSAM/MobileSAM masks. Masks inform reviewers and the
  rationale, not automatic decisions.
- **Content-policy classifier:** multi-label head on the shared
  embedding, categories `violence_gore` and `nudity_sexual`. Blocks on
  the phone; the server re-runs it and discards violating images,
  keeping only a hash. Does not replace CSAM hash matching (§5).
- **Escalation (Llama 4 Scout):** low-confidence, high-severity,
  device/server-disagreement or reviewer-escalated cases only, under a
  daily budget. Receives the **blurred** image. Never used for policy
  decisions or final authenticity verdicts.
- **Runtimes:** phone ExecuTorch (Android); server ONNX Runtime on CPU.
- **ImageBind:** v2 only.

## 4. Authenticity Layer (Real vs. Fake)

No single model is a reliable fake detector. The server combines:

1. **Provenance and integrity:** file hash, EXIF consistency,
   timestamp/GPS plausibility, editing-software tags.
2. **C2PA content credentials:** valid / invalid / absent; a manifest
   declaring a generative-AI tool is a strong signal.
3. **Capture source and attestation:** in-app captures with valid Play
   Integrity tokens are most trustworthy. Gallery and web uploads lack
   these signals; they aren't treated as suspicious on their own.
4. **Internal duplicates:** pHash + DINOv3 embedding search over past
   reports.
5. **Web reverse image search:** catches old photos reposted as new.
   Uses the blurred copy.
6. **Corroboration:** independent reports (distinct verified accounts
   on distinct devices) of the same type near the same place and time.
7. **Forensic score:** calibrated detector output; one input among many.
8. **Context check (escalation only):** claim vs. scene, location,
   weather.
9. **Fusion rule:** combine into likely-real / needs-review /
   likely-manipulated with reasons. High-severity or low-confidence
   cases always go to human review.
10. **UX wording:** "signals observed" and confidence; never
    "proven fake/real".

## 5. Trust, Safety and Legal Compliance (U.S.)

> Not legal advice. Have a lawyer review this section before any
> public launch.

### 5.1 Accounts and age

- Roles: `user`, `reviewer`, `safety_officer`, `admin`. Every user has
  an account.
- Signup: email + password (argon2id), email verification required
  before the first upload, date of birth checked against `min_age`
  (default 18) and **not stored**; only "age confirmed at signup" is
  kept. Setting the minimum at 13+ keeps COPPA out of scope.
- **Account deletion** from inside the app and from a web page (Google
  Play requires both). Deletion removes the account, its reports and
  media, except items under a legal preservation hold (§5.2).
- Rate limits, policy acceptance, repeat-violation suspension and
  corroboration all key on the account.

### 5.2 CSAM (18 U.S.C. § 2258A, REPORT Act 2024)

- Hash-match every upload server-side (PhotoDNA or Cloudflare CSAM
  Scanning Tool) **before any other processing**.
- Reviewers/safety staff can flag suspected CSAM, moving it to
  quarantine and capturing "actual knowledge".
- **Quarantine, not deletion:** separate encrypted bucket and key, only
  the `safety_officer` role, every access audit-logged, preserved **one
  year** under a legal hold that retention and account deletion cannot
  override.
- A safety officer reviews the prepared report and submits it to
  NCMEC. The system never submits automatically. The uploading account
  is suspended; the user sees only a generic rejection message.
- Quarantined items never enter training data, eval sets, reviewer
  queues, logs, thumbnails or general backups.
- Agents never collect, download or generate such material. Tests use
  provider test hashes or a mock that "matches" a benign fixture.

### 5.3 Nonconsensual intimate images (TAKE IT DOWN Act)

- Public plain-language removal-request page, no account required,
  linked from the app, the website footer and the map.
- Requests include name/contact, signature, content locator, good-faith
  statement. Valid requests actioned within **48 hours** (internal
  target 24). Content removed; identical copies found via duplicate
  search and removed too. Requests, decisions and times are audit-logged
  with a time-remaining dashboard.

### 5.4 Other policies

Content policy and terms are versioned; users re-accept on change.
Violent/gory or nudity/sexual uploads that aren't CSAM are discarded
(hash, time, category, account id kept). Repeated violations suspend the
account (threshold in `config/thresholds.yaml`).

## 6. Data and Labeling Plan

Seed datasets: **Incidents1M** (main incident data), **CrisisMMD**
(severity labels, extra disaster images, claim text, partial policy
positives), **xBD** (registered only; satellite imagery, not used for v1
training unless a decision record shows benefit). Plus user-approved
policy sets, a few hundred labeled car-crash severity images, ~200
damage-mask images, a license-plate dataset, and held-out real phone
photos for the false-accusation evaluation (Phase 1/5 specs).

- Labels per photo: incident types, severity, policy violation,
  manipulated/clean if known, duplicate group id. License recorded per
  image; never mark `commercial-approved` without a user decision.
- Location record: `lat, lng, accuracy_m, source, consented`. Reports
  with `source: none` or `consented: false` are excluded from maps.
- Reviewer workflow: two annotators + adjudicator; corrections export
  as new training labels.
- **Privacy:** originals encrypted at rest, reviewer-only, deleted
  after `RAW_RETENTION_DAYS` (a fixed protocol constant in
  `config/policy.yaml`, set by the retention decision in §11 — not a
  calibrated threshold); public images have faces/plates blurred
  and EXIF stripped; public map coordinates are deterministically
  jittered ~100–500 m; reviewers may see exact pins with audit logging.
- **Policy-rejected images are never stored**; only hash, time,
  category, account id. CSAM matches/flags are the one exception
  (quarantine, §5.2), never used as data.
- Dataset version + embedding version + model checkpoint recorded on
  every training run. Long data jobs are resumable and checkpointed
  (`work/checkpoints/`, see `agents/builder.md` §4).

## 7. API / UX Outline

Minimal v1 API (full contract in `contracts/openapi.yaml`, Phase 0).
Every endpoint requires a logged-in account unless marked *public*.

- Accounts: `POST /v1/auth/register`, `verify-email`, `login`,
  `refresh`, `logout`, `password-reset` + `/confirm` *(public where
  applicable)*, `GET /v1/account`, `DELETE /v1/account`.
- `GET /v1/policy` *(public)*; `POST /v1/policy/accept`.
- `POST /v1/attestation/challenge` — single-use nonce for Play
  Integrity.
- `POST /v1/analyze` — original photo + metadata → `202 {report_id}`.
  Requires verified email and current policy accepted. Idempotent on
  `client_report_id` + account.
- `GET /v1/reports/{id}` — types, severity, rationale, masks,
  authenticity + reasons, confidence, display location, thumbnail and
  blurred photo URLs. Exact coordinates and originals are
  reviewer-only.
- `GET /v1/review-queue`, `POST /v1/reviews/{id}` (confirm / correct /
  escalate / flag suspected CSAM) — reviewer only.
- `POST /v1/takedown-requests` *(public)*;
  `GET /v1/takedown-requests/{id}` (requester token).
- Safety-officer only: takedown queue, quarantine, NCMEC preparation.
- `GET /v1/incidents?bbox=…&zoom=…&types=…&severity=…&since=…&limit=…`
  — GeoJSON `FeatureCollection` (display coordinates), `limit` default
  500 / max 2000, `truncated: true` when cut. Excludes non-consented,
  ungeolocated and policy-rejected reports; `likely-manipulated`
  excluded unless `include_flagged=true` (reviewer only). PostGIS
  `GEOGRAPHY(Point, 4326)` with GIST index; < 300 ms p95 at 1M reports.

**Android UX (native)**

- First run: sign up/log in (age gate, email verification), then the
  content policy screen; both required before capture. Capture and
  on-device analysis work offline once logged in.
- Settings: account, delete account, content policy, removal-request
  link.
- Capture → instant report card (or policy block) → queued upload →
  server-verified report card → reviewer actions (reviewers only).
- Always show uncertainty, "needs human review", and "Not for
  emergencies: call your local emergency number".

**Mobile map (native)**

- MapLibre Native Android with free OSM-derived vector tiles
  (OpenFreeMap or self-hosted); provider behind config.
- Full-screen map, red-dot markers (≥ 24 dp hit area) with clustering;
  tap dot → bottom sheet (thumbnail, type — severity, authenticity
  banner, time, confidence, View details, reviewer actions).
- Filters: type, severity, 24h/7d/30d; `likely-manipulated` hidden by
  default. Reports without location appear in a list with manual pin,
  never as dots. Initial dots < 2 s on 4G; pan/zoom refetch debounced
  300 ms; dots have screen-reader descriptions; severity never shown by
  color alone.

**Web (server-rendered)**

Account pages, upload page, reviewer console, public removal-request
page, restricted safety console. See Phase 7.

## 8. Build Phases

| Phase | Spec | Why separate | Depends on |
|---|---|---|---|
| 0 Foundations & contracts | `specs/phase-0-foundations.md` | Freezes schemas, taxonomy, thresholds, tooling | — |
| 1 Data pipeline & labels | `specs/phase-1-data.md` | Long downloads + one license sign-off; fixed versioned splits | 0 |
| 2 Core image models | `specs/phase-2-core-models.md` | GPU work; shared phone/server model + test vectors | 0, 1 |
| 3 Localization & privacy | `specs/phase-3-localization-privacy.md` | Box/mask models, different labels and metrics | 0, 1, 2 |
| 4 Backend core | `specs/phase-4-backend.md` | Accounts, ingest, CSAM quarantine, takedowns; starts with stubs | 0 (+2, 3 for real models) |
| 5 Authenticity & escalation | `specs/phase-5-authenticity.md` | Highest-risk subsystem, external providers, strict eval | 0, 2, 4 |
| 6 Android app | `specs/phase-6-android.md` | The only v1 client; built/tested on Windows/Linux | 0, 2, 3, 4 |
| 7 Web: accounts, upload, review & safety | `specs/phase-7-web-review.md` | Different surface and users; needs real backend + authenticity | 4, 5 |
| 8 Hardening & pilot readiness | `specs/phase-8-hardening.md` | Red-team, bias, load and abuse tests end to end | 4–7 |

Order: **strictly sequential, one spec at a time.** No two phases are
ever active together, and no brief for a later phase may be dispatched
while a phase is active. This costs the old parallel ML/backend tracks
(Phase 4 now waits for Phases 2–3 instead of starting on stubs); the
payoff is a shared working tree that only ever contains one phase's
changes, so diffs, commits and test failures are attributable to
exactly one spec.

Manual gates are per **block of two phases**, not per phase:

| Block | Runs, in order | User command |
|---|---|---|
| 0 | Phase 0 → Phase 1 | `start block 0` |
| 1 | Phase 2 → Phase 3 | `start block 1` |
| 2 | Phase 4 → Phase 5 | `start block 2` |
| 3 | Phase 6 → Phase 7 | `start block 3` |
| 4 | Phase 8 | `start block 4` |

```text
[start block 0]  0 ──► 1   ■ manual stop
[start block 1]  2 ──► 3   ■ manual stop
[start block 2]  4 ──► 5   ■ manual stop
[start block 3]  6 ──► 7   ■ manual stop
[start block 4]  8         ■ manual stop
```

Within a block, the second phase starts automatically as soon as the
first phase's completion report is committed — there is no user prompt
between them. A phase is launch-complete only when every objective is
ACCEPTED (orchestrator §7). A phase whose objectives are all ACCEPTED
or BUILD-ACCEPTED is BUILD-COMPLETE: its build completion report is
committed, the automatic transition runs, and the next block may
start, with every BUILD-ACCEPTED objective's open criteria carried in
`docs/BLOCKED.md`. BUILD-ACCEPTED never supports a launch, pilot or
store-submission claim. A phase with an objective open in
NEEDS-USER-APPROVAL (no mock available), ENV-BLOCKED (no provisional
path) or REJECTED produces no completion report, no automatic
transition and no next block. After the second phase, the orchestrator
writes a block handoff, stops, and waits for the next block command
(see `agents/orchestrator.md` §1). Dependency checks still apply at
every phase start: e.g. Phase 4's "real models" criteria need
Phases 2–3 artifacts, which the sequential order guarantees exist —
as accepted artifacts, or as registered provisional ones the backend
integrates behind its stub fallback.
Builders run one at a time on the shared tree
(`max_concurrent_builders: 1` in `agents/models.yaml`), counted on the
orchestrator's roster.

### 8.1 Human inputs (provide up front so agents aren't blocked)

| Input | Phase |
|---|---|
| Model/effort and dispatch defaults in `agents/models.yaml` | before 0 |
| Minimum age decision (default 18) | 0 (non-blocking) |
| Dataset access (Incidents1M, CrisisMMD) + license approval | 1 |
| Violence/gore and adult nudity/sexual-content sets (licensed, adults only) | 1 |
| A few hundred car-crash images labeled minor/moderate/severe | 1 |
| DINOv3 license acceptance + download token | 2 |
| GPU access (one modern GPU) | 2, 3 |
| ~200 damage-mask images; plate dataset; face eval images | 3 |
| Email provider | 4 (mock in dev) |
| CSAM hash-matching access | 4 (mock in dev) |
| NCMEC CyberTipline registration | 4, 8 (mock in dev) |
| Named safety officer(s), takedown contact | 7, 8 |
| Google Play Integrity setup | 5, 6 |
| Reverse image search provider + API key | 5 |
| Escalation model host + key (Llama 4 Scout) or GPU | 5 |
| Forensic training data or budget to generate AI images | 5 |
| Held-out real consented phone photos (≥ 300 ideal) | 5 |
| Physical mid-range Android phone (or Firebase Test Lab) | 6 |
| Hosting choice, privacy/legal review, commercial license review, pilot partner | 8 |
| Approval of content policy text | 0 (non-blocking) |

Phase 0 creates `docs/HUMAN_INPUTS.md` to track these. One rule covers
all of them: use the spec's mock/fallback to keep building, log it in
`docs/BLOCKED.md`, and continue with unaffected objectives — but a mock
never satisfies a criterion that requires the real input. Objectives
whose acceptance needs a missing input but which have a working
mock/fallback or provisional artifact are BUILD-ACCEPTED with those
criteria listed as open; objectives with no mock are
`NEEDS-USER-APPROVAL`, and missing infrastructure with no provisional
path is `ENV-BLOCKED` (orchestrator §1, §7). A BUILD-ACCEPTED phase
may sequence onward; it may never be launched from.

### 8.2 Conventions for agents (every phase)

- **Contracts first:** `contracts/` and `config/` are the source of
  truth; changing them needs a version bump, updated examples and a
  decision record. They are locked by default; a brief edits an
  existing contract or config file only by naming it in
  `unlocked_paths` under the orchestrator's §5.2 unlock procedure.
  Protected files (`AGENTS.md`, `agents/**`, `specs/**`, this plan,
  `.gitignore`) are never unlocked; only the user edits those.
- **Reversible decisions:** record in `docs/decisions/` and continue.
  Stop only for orchestrator §9 user-only decisions, irreversible
  actions, or missing inputs with no mock.
- **Acceptance criteria are tests:** done only when criteria pass via a
  command that can actually run here (`python tasks.py check`,
  `gradlew.bat check` on Windows, eval scripts). Local results are
  authoritative; CI results are appended when the user pushes. The
  `- [ ]` boxes in a spec are the spec's source text, not project
  state: agents never edit `specs/**`, so a criterion counts as met
  only when the phase log records it passing (§6.2 of the orchestrator
  file via `logs/README.md`). "Definition of done" in every spec means
  exactly that, never a ticked box. A criterion that can only run on a
  missing real input is recorded as open under a BUILD-ACCEPTED
  objective (orchestrator §7): the phase may then be build-complete
  and sequence onward, but the criterion still has not passed.
  **Lowering any numeric target, including "initial" ones, needs user
  approval** (§9); raising one needs only a decision record. If a
  target is unreachable for data reasons, use the orchestrator §3
  evidence-pack exit instead of burning the second attempt. Each brief
  gets at most 2 attempts (orchestrator §3).
- **No magic numbers in code:** calibrated thresholds live in
  `config/thresholds.yaml` under `# CALIBRATE: Phase N` keys. Fixed
  protocol constants (JWT lifetimes, the 48-hour takedown deadline,
  image size limits) live in `config/policy.yaml` or the API contract
  and are referenced, not re-typed, in code.
- **No secrets in git;** every env var in `.env.example`. Agents check
  credentials only via `python tasks.py env-check --names ...`
  (present/missing), never by reading `.env`.
- **Commits:** only the orchestrator commits, once per accepted
  objective and once per completion report. Agents never push.
- **Windows:** developed natively on Windows; every project task runs
  through `python tasks.py <target>` (Phase 0), which also runs on the
  Linux CI runner. Android builds use `gradlew.bat` on Windows.
- **Models/artifacts:** weights and datasets live outside git under
  `ARTIFACT_ROOT`/`data/`; the registry records sha256 so any session
  can locate and verify them.
- **Long jobs** (downloads, embeddings, training) are resumable and
  write checkpoints to `work/checkpoints/`.
- **Licenses:** record every dataset/model license; avoid AGPL
  dependencies (e.g. Ultralytics YOLO) unless approved.
- **Safety:** never collect, download, generate or open material that
  could be CSAM. A suspect file stops that file only, is listed by
  path in `docs/BLOCKED.md`, and work resumes past it. Never submit
  real NCMEC reports or contact outside organisations.

## 9. Test Plan

- Unit: preprocessing (Python/Kotlin parity), provenance/C2PA,
  attestation verifier, fusion rules, API schemas, policy gating,
  auth and roles.
- Model evals: held-out incident set; macro-F1 + calibration; severity
  weighted kappa per incident type.
- Policy eval: recall per category; false positives on ordinary
  crash/disaster images.
- Accounts: signup/age gate, email verification, deletion incl.
  legal-hold exceptions, role-based access.
- Compliance: hash-match → quarantine (mock), legal hold survives
  retention and deletion, takedown → removal of content and copies
  within 48 hours (frozen clock).
- Parity: quantized phone model vs. server reference on shared test
  vectors (Python <-> Kotlin only).
- Segmentation eval: IoU on damage masks + reviewer correction rate.
- Retrieval eval: duplicate recall@k on synthetic transforms.
- Authenticity eval: false-accusation rate on held-out real photos;
  forensic AUC incl. held-out generators.
- E2E: capture → offline queue → upload → report → review; chaos cases
  (no GPS, stripped EXIF, re-encoded image, HEIC, offline then
  reconnect, provider timeouts).
- Map eval: bbox latency (< 300 ms p95), dot tap → sheet on mid-range
  Android (< 2 s on 4G), clustering, manual-pin fallback.
- On-device performance: analysis p50 ≤ 1.5 s, models ≤ 80 MB.

## 10. Risks and Issues

1. **Fake detection is never certain.** Many independent signals,
   probabilistic wording, mandatory human review for high severity.
2. **False accusations.** Hard false-accusation criterion, conservative
   thresholds, audit trail, corrections flow.
3. **Content policy errors.** Hard-negative evaluation on crash scenes,
   server re-check, reviewer removal, takedown runbook.
4. **Phone results can be tampered with.** Server re-runs all models;
   Play Integrity attestation; device results only advisory.
5. **Legal non-compliance (CSAM, TAKE IT DOWN).** Hash matching on
   every upload, quarantine with legal holds, reviewer flag path,
   48-hour dashboard, legal review before launch.
6. **Fake accounts.** Email verification, attestation, per-account and
   per-device limits, corroboration across distinct accounts/devices.
7. **Privacy exposure.** Consent, server-side blurring, encrypted
   reviewer-only originals with retention and audit logs, jittered
   public coordinates, minimal account data.
8. **Liability for wrong triage.** No auto-dispatch in v1; "not for
   emergency use" labeling; escalation defaults.
9. **Bias and generalization.** Stratified evals, targeted data.
10. **Thin car-crash severity labels.** Human-labeled set; crashes go
    to review until it exists.
11. **On-device constraints.** ≤ 80 MB budget, int8 quantization,
    performance criteria on mid-range Android.
12. **Platform dependencies.** Play Integrity needs a Google Cloud /
    Play Console setup; listed as an up-front human input with a dev
    mock.
13. **Data and model licensing.** Mostly research-licensed seeds;
    DINOv3 and Llama have custom licenses; commercial review before
    launch.
14. **Cost.** Phone-first design, daily budgets, caching by hash for
    escalations and reverse search.
15. **Agent-environment drift (new).** Builders depend on Docker, a
    GPU, an emulator/phone and network access that a given Muse
    session may not have. Mitigation: `ENV-BLOCKED` status, resumable
    checkpoints, mock-first design, and local test gates that never
    silently require CI or hardware.

## 11. Open Decisions

- **Minimum age:** default 18 (`min_age` in `config/policy.yaml`).
  Must not go below 13 without a COPPA review.
- **CSAM hash-matching provider:** PhotoDNA (application required) or
  Cloudflare CSAM Scanning Tool (eligibility check needed).
- **Retention period** for encrypted originals (`RAW_RETENTION_DAYS`).
  Legal holds override it.
- **Providers:** reverse image search, escalation model host, email
  sending, production hosting.
- **Sign-in options:** v1 is email + password only.
- **iOS (v2 question):** if an iOS client is added later, it mirrors
  the Android app against these same contracts; nothing in v1 should
  bake in Android-only assumptions in `contracts/` or `config/`.

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
- MapLibre: https://maplibre.org
- OpenFreeMap: https://openfreemap.org
- Open-Meteo: https://open-meteo.com

Legal and compliance

- REPORT Act (Public Law 118-59): https://www.congress.gov/118/plaws/publ59/PLAW-118publ59.htm
- REPORT Act summary (Wilson Sonsini): https://www.wsgrdataadvisor.com/2024/05/new-minor-safety-obligations-for-online-services-report-act-expands-child-sexual-exploitation-reporting-requirements/
- TAKE IT DOWN Act (Reed Smith): https://www.reedsmith.com/our-insights/blogs/viewpoints/102ms5e/covered-platforms-are-you-ready-to-take-it-down/
- NCMEC CyberTipline: https://report.cybertip.org/
- Microsoft PhotoDNA: https://www.microsoft.com/photodna
- Cloudflare CSAM Scanning Tool: https://blog.cloudflare.com/the-csam-scanning-tool

Datasets

- Incidents1M: http://incidentsdataset.csail.mit.edu/
- CrisisMMD: https://crisisnlp.qcri.org/crisismmd
- xBD / xView2: https://xview2.org/dataset

Verify each link and license before relying on it.
