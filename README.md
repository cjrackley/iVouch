# iVouch

Incident photo analyzer. Users photograph incidents (natural disasters,
car crashes). The software answers two questions:

1. Is this photo likely real, manipulated, AI-generated, or reposted out
   of context?
2. What incident does it show, and how severe is it?

Every authenticity result is probabilistic and needs human review.
It is never presented as certain.

This repository holds two scopes:

- **`lite/`** — the working demo. Web-only, local-only, $0 inference.
  This is what you can run today.
- **`specs/`, `DEVELOPMENT_PLAN.md`** — the full v1 plan. Android-first
  with a verifying server. Not built yet.

## Features (Lite demo, working today)

### Accounts

- Email plus password signup with argon2id hashing.
- Email verification through console mail files (no email provider
  needed; the token lands in `lite/data/mail/`).
- Minimum-age gate at signup (default 18+). Date of birth is checked,
  not stored.
- Login, logout, login rate limiting, and account deletion from the
  account page.
- Roles: `user` and `reviewer`. The reviewer flag is granted only by
  the local CLI. There is no web path to self-promote.

### Upload and result card

- One JPEG or PNG photo per report (10 MB cap), plus optional claim
  text, plus a required map location with an explicit consent checkbox.
- The upload form states the sharing rule before submit: photo, claim
  text, approximate location, and verdict become visible to other
  logged-in demo users. Email, exact coordinates, and file paths are
  never shared.
- Local checks run in order: file sanity, mock safety gate (SHA-256
  against a fixture list only), provenance-lite (EXIF, capture time,
  GPS, editing-software tags), exact plus perceptual-hash duplicates,
  CLIP zero-shot incident type, CLIP zero-shot severity, image-vs-claim
  similarity, then fusion-lite.
- The result card shows `likely-real`, `needs-review`, or
  `likely-manipulated` with "signals observed" reasons, incident and
  severity labels with one-decimal percentages, and a demo disclaimer
  on every result. Missing EXIF alone is never treated as fake.
  There is no forensic AI-detector score (`None` in Lite).

### Reports, feed, saved, community

- Owner detail page (`/reports/{id}`) and community page
  (`/shared/{id}`) share one layout: hero photo, trust badge,
  mini-map preview at the jittered display point only, claim text.
- Vouches (add/remove), comments, and edit/delete of your own report.
- Community feed (`/feed`) and saved places (`/saved`, list and map
  views, empty states included).
- Reviewer correction overlay: when a reviewer corrects a report, the
  owner sees "corrected by reviewer" with the new values while the
  original demo verdict stays visible.

### Login-required map

- `GET /map` ( `/` redirects there). Anonymous visitors are redirected
  to login.
- Each accepted report appears as a dot at its jittered approximate
  location (200–500 m). Tap a dot for a bottom sheet with photo,
  verdict, and a View Details link to the community page.
- Street/satellite toggle, recenter and zoom controls, geolocate
  button, drag/click pin picker on upload, and a list fallback when
  the map CDN is unreachable.
- Photo-to-place matching is human visual judgement only. Lite never
  claims a photo matches its location automatically.

### Review queue

- Reviewer-only queue (`/review`), `needs_review` first then newest,
  plus per-report detail (`/review/{id}`) and an audit page.
- Reviewers can confirm or correct (incident type, severity) and see
  probabilities, provenance flags, duplicate links, and claim
  similarity, but never the uploader's email.
- Rejected uploads get a generic message. Policy and safety behavior
  is mock-only and is never described as real screening.

## Specs: Lite vs v1

### Lite specs (`lite/specs/`, 8 specs, sequential)

| Order | Spec | Covers |
|---|---|---|
| 0 | `spec-0-foundations.md` | Config, thresholds, DB schema, tooling |
| 1 | `spec-1-image-checks.md` | CLIP checks, provenance, duplicates, fusion |
| 2 | `spec-2-server.md` | FastAPI auth, upload, storage, CLI |
| 3 | `spec-3-web.md` | Pages: signup, upload, reports, account |
| 4 | `spec-4-review-hardening.md` | Review queue, audit, abuse limits |
| 5 | `spec-5-map.md` | Login-required map, jitter, consent |
| 6 | `spec-6-polish.md` | Native-app restyle, orphan-route audit |
| 7 | `spec-7-redesign.md` | Display fixes, map reliability, verify flow |

### v1 specs (`specs/`, 9 phases, sequential, not built)

| Phase | Spec | Covers |
|---|---|---|
| 0 | `phase-0-foundations.md` | Contracts, taxonomy, thresholds, tooling |
| 1 | `phase-1-data.md` | Datasets, splits, labeling pipeline |
| 2 | `phase-2-core-models.md` | DINOv3 heads, trained incident/severity/policy |
| 3 | `phase-3-localization-privacy.md` | SAM masks, face/plate blurring |
| 4 | `phase-4-backend.md` | Accounts, ingest, CSAM quarantine, takedowns |
| 5 | `phase-5-authenticity.md` | Fusion, reverse image search, escalation |
| 6 | `phase-6-android.md` | Native Android app, on-device inference |
| 7 | `phase-7-web-review.md` | Web upload, reviewer and safety consoles |
| 8 | `phase-8-hardening.md` | Red-team, bias, load, pilot readiness |

### Lite vs v1

| | Lite (runs today) | v1 (planned) |
|---|---|---|
| Client | Web app only | Native Android app plus web |
| Server | FastAPI plus SQLite plus local files | FastAPI plus PostgreSQL, PostGIS, pgvector, S3 |
| Image models | CLIP zero-shot, local, $0 | DINOv3 fine-tuned heads, EfficientSAM, YOLO, MediaPipe |
| Authenticity | EXIF, duplicates, claim check, fusion-lite | Plus C2PA, Play Integrity, web reverse image search, corroboration, forensic score, Llama 4 Scout escalation |
| Safety | Mock hash list over fixtures | PhotoDNA or Cloudflare hash matching, quarantine, NCMEC reports |
| Map | Login-required, jittered dots, human comparison | Public GeoJSON map, native MapLibre, reviewer-only exact pins |
| Offline | No | On-device analysis, offline queue |
| Status | Demo-grade, never launch-ready | Pilot-gated, lawyer-reviewed |

Read `lite/README.md` for the Lite-local details and
`lite/DEMO.md` for the click-through script.
Read `DEVELOPMENT_PLAN.md` for the full v1 design.

## Start the project on another machine

Takes about 15 minutes plus the one-time model download.
Tested on Windows with Python 3.11.

### 1. Prerequisites

- Python 3.11.
- Git.
- A browser.
- About 2 GB free disk for the pinned CLIP model
  (`openai/clip-vit-base-patch32`, cached under
  `lite/data/artifacts/` after the first download).
- No Docker, GPU, API key, or email provider needed.

### 2. Copy the project

Copy the whole repository folder to the new machine (clone it, or
copy the directory as-is). All local state is git-ignored, so the
new machine starts clean.

### 3. Create the environment and install

Run from the repository root. Use a project-local environment.
Never install into the system interpreter.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r lite/requirements.txt
```

Linux or macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r lite/requirements.txt
```

### 4. Set the dev-only JWT secret

Local demo only. Never commit a real secret, and never reuse this
value anywhere else.

```powershell
$env:LITE_JWT_SECRET = "dev-only-local-demo-secret"
```

`cmd.exe` uses `set LITE_JWT_SECRET=dev-only-local-demo-secret`.
Bash uses `export LITE_JWT_SECRET=dev-only-local-demo-secret`.

Without the variable the server still starts but logs a warning and
uses an insecure fallback. That fallback is for local development
only.

### 5. Start the server

```powershell
python -m lite.app.server
```

This serves `http://127.0.0.1:8000`. Host and port are overridable:

```powershell
python -m lite.app.server --host 127.0.0.1 --port 8000
python -m lite.app.server --help
```

First run only: the CLIP model (about 1.8 GB) downloads from
HuggingFace into git-ignored `lite/data/artifacts/` and is reused
on later runs. Allow time and disk space. CPU fallback is normal
without a GPU; inference is slower but works. Keep this terminal
open. Open a second terminal (with the environment activated) for
the commands below.

### 6. Sign up

1. Open `http://127.0.0.1:8000` in the browser.
2. Go to `/signup`. Enter an email (for example
   `reporter@example.com`) and a password, confirm you meet the age
   gate, and submit. The reply is generic by design.
3. Verify the account. Open the newest
   `verify_reporter_example_com_*.txt` file in `lite/data/mail/`,
   copy the `token:` value, and submit it on the `/verify` page.
4. Log in on `/login` with the same credentials.

### 7. Use the website

Follow `lite/DEMO.md` for the full script. The short version:

1. **Upload.** As the reporter, open `/upload`. Pick a JPEG or PNG
   photo, add optional claim text, set the pin (geolocate button or
   drag/click), tick the consent checkbox, and submit. The first
   inference after a fresh start warms up the model and is slower.
2. **Read the result.** The result card shows the verdict with
   "signals observed" reasons, incident and severity labels with
   percentages, and the demo disclaimer. Zero-shot labels are
   guesses, not ground truth.
3. **Work the review queue.** Sign up a second account
   (`reviewer@example.com`), verify it, then promote it from the
   second terminal:

   ```powershell
   python -m lite.app.cli make-reviewer reviewer@example.com
   ```

   Log in as the reviewer in a second browser profile. Open
   `/review`, open a report, and submit `confirm` or `correct`.
   Reopen the report as the reporter to see the reviewer overlay.
4. **Share and map.** Open the report's `/shared/{id}` page as the
   other user. Confirm only the photo, claim, approximate location,
   and verdict are visible. Open `/map`, click a dot, follow View
   Details, and compare the photo against the street and satellite
   views.
5. **Save and feed.** Bookmark reports from the map sheet or detail
   page, browse `/saved` and `/feed`, and manage your pins from
   `/account`.
6. **Delete (optional).** Use the account page delete action
   (`POST /account/delete`). The account and its data are removed
   and the session ends.

### 8. Where local state lives

All git-ignored. Safe to delete to reset (keep `artifacts/` so the
model is not re-downloaded).

- SQLite database: `lite/data/ivouch.db`.
- Uploaded photos: `lite/data/uploads/<account-id>/`.
- Console mail (verification tokens): `lite/data/mail/`.
- Model weights: `lite/data/artifacts/`.
- Scratch and checkpoints: `lite/work/`.

To reset the demo: stop the server, delete `lite/data/ivouch.db`,
`lite/data/uploads/`, and `lite/data/mail/`, then restart.

### 9. Likely trouble

- **Model download is slow or flaky.** Retry the server start.
  HuggingFace snapshots resume into `lite/data/artifacts/`. If the
  network blocks HuggingFace entirely, inference cannot run. Stop
  and record it. Never substitute another model or fake verdicts.
- **Port already in use.** Stop the other server, or serve on
  another port (`--port 8001`) and use
  `http://127.0.0.1:8001` instead.
- **Test-only socket errors.** A `WinError 10013` failure applies
  to the test suite's TestClient under a blocking sandbox, not to
  real serving. `python -m lite.app.server` in your own terminal
  binds and serves normally.
- **Reviewer promotion fails.** The CLI errors clearly on an
  unknown email. Sign the account up first, then promote it.
