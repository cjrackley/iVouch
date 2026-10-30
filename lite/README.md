# iVouch Lite

A one-week, web-only, local-only demo of the iVouch idea. It lives in
this `lite/` folder so the full plan in `DEVELOPMENT_PLAN.md`,
`specs/`, and `agents/` stays untouched.

## What Lite is

- One web app: sign up, log in, upload one photo plus optional claim
  text plus a required map location, see a result card, browse other
  users' reports on a login-required map and community pages, and
  (for reviewers) work a review queue.
- One server: FastAPI + SQLite + local file storage. No Docker
  requirement, no PostGIS, no Redis, no cloud services.
- Local-only image checks on this PC's GPU. No paid vision or LLM
  calls anywhere in the default path. Inference cost is $0.
- Demo-grade only. Every result says "demo — needs human review."
  Lite is never described as launch-ready, pilot-ready, or accurate.

## What Lite is not

- No native Android app, no ExecuTorch, no offline queue.
- No trained models: no DINOv3 fine-tuning, no SAM masks, no 1M-image
  dataset. Classification is CLIP zero-shot with text prompts.
- No real PhotoDNA/CSAM screening, no NCMEC contact, no Play
  Integrity, no reverse image search, no Llama escalation. Safety and
  escalation are mocks over synthetic fixtures only.
- No PostGIS and no public (logged-out) map. Lite does include a
  simple login-required map (spec-5): every accepted submission
  carries a required location plus consent and is plotted as a
  jittered dot, and a person visually compares the photo with the
  mapped area. Automated photo-to-location matching is out of
  Lite (see spec-5).
- Uploads are shared by design: photo, claim text, approximate map
  location, and verdict are visible to other logged-in demo users.
  Email, exact coordinates, and file paths are never shared, and
  every upload form states this before submit (see specs 2, 3, 5).
- No multi-photo or video support.

## How the server checks a picture (in order)

1. File sanity: JPEG/PNG only, size cap, decodes cleanly.
2. Mock safety gate: SHA-256 against a test-fixture list only. A match
   gets a generic "upload could not be accepted" rejection. This is
   not real CSAM screening and is never described as such.
3. Provenance-lite: EXIF present/missing, capture-time sanity, GPS
   present/absent, editing-software tag. Missing EXIF alone is never
   treated as fake.
4. Duplicates: exact SHA-256, then perceptual-hash near-duplicates
   against prior uploads in Lite's own store.
5. Incident type: local CLIP zero-shot (e.g. openai/clip-vit-base-
   patch32 or a pinned equivalent) with prompts for `car_crash`,
   `fire`, `flood`, `storm_damage`, `earthquake_damage`, `none`.
6. Severity: second zero-shot pass (minor/moderate/severe prompts)
   plus confidence. Low confidence always routes to review.
7. Claim check: image-vs-claim-text similarity. A large mismatch adds
   a "claim may not match scene" reason.
8. Fusion-lite: a short ordered rule list produces `likely-real`,
   `needs-review`, or `likely-manipulated` with "signals observed"
   reasons. There is no forensic AI-detector score (`None` in Lite).

## Spec sequence (no day labels; run strictly in order)

| Order | Spec | Depends on |
|---|---|---|
| 1 | `specs/spec-0-foundations.md` | — |
| 2 | `specs/spec-1-image-checks.md` | spec-0 |
| 3 | `specs/spec-2-server.md` | spec-0, spec-1 |
| 4 | `specs/spec-3-web.md` | spec-2 |
| 5 | `specs/spec-4-review-hardening.md` | spec-3 |
| 6 | `specs/spec-5-map.md` | spec-2, spec-3 |

Only one spec is active at a time. A spec starts only after the prior
spec's completion report is committed (see `agents/orchestrator.md`).

## Budget guardrails ($200 total agent/API spend)

- Agent tokens: hard cap near $140 for all Lite work. Up to 3 parallel
  builders inside one spec, specs still sequential, at most one retry
  per brief (see agents files).
- External APIs: $0 by design. Local models and mocks only. Any future
  paid call needs a user decision first and a hard cap in code.
- Keep roughly $30 unspent as buffer. If spend approaches the cap,
  freeze features and finish tests, README, and demo script only.

## Roles

- `agents/orchestrator.md` — lead session. Divides, judges, logs,
  commits. Read it if you started the session.
- `agents/builder.md` — spawned worker. Implements one brief only.
- `logs/README.md` — log format. Logs live in `lite/logs/`.

Nothing outside `lite/` is edited by Lite work.

## Test environment

- Page and server tests use TestClient, which needs socket access.
- The default sandbox blocks sockets. Symptom is WinError 10013.
- Gate those tests through the sanctioned one-time escalation path.
- Socket-free checks run without it.
