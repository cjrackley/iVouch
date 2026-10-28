# Lite Spec 2 — Server (API, accounts, storage)

**Why separate:** spec 1 proved the checks as functions. This spec
owns persistence and HTTP: accounts, upload, pipeline order, and
report retrieval. No pages here (spec 3), no review actions (spec 4).

| | |
|---|---|
| Depends on | spec-0, spec-1 |
| Unblocks | spec-3 |
| Execution | Sequential only — spec 3 of 6 |
| Stack | FastAPI, SQLite (stdlib sqlite3 or SQLAlchemy), argon2, PyJWT |

## Human inputs

None. Email is a console sender that writes messages as files under
`console_mail_dir` (`lite/data/mail/`, git-ignored; dev/test only).
Production email, hosting, and secrets management are out of Lite.

## Defaults

- Every user has an account. No anonymous endpoints.
- Passwords hashed with argon2id. Access is a short-lived JWT;
  lifetime is `jwt_access_minutes` and size limits come from
  `lite/config.yaml`.
- Age gate: date of birth checked against `min_age` (default 18) at
  signup and never stored; only `age_confirmed_at` is kept.
- Storage: SQLite file under `lite/data/`, uploads under
  `lite/data/uploads/`, mail under `lite/data/mail/`. All
  git-ignored. No Docker, no migrations framework; schema is one
  `CREATE TABLE` module with a version row. Lite is a fresh-install
  demo: schema changes mean recreating the database, never a
  migration.
- Sharing model (community demo): accepted reports are visible to
  every logged-in user through the shared endpoints and pages
  (`GET /api/incidents`, `GET /shared/{id}`, `GET /map`). Shared
  fields only: photo, claim text, display (jittered) location,
  incident type, severity, label, reasons, confidence, time.
  Never shared in any response: uploader email, exact coordinates,
  raw file paths. Owner endpoints (`GET /reports`, `GET
  /reports/{id}`) stay owner-only. Mock-gate-rejected uploads
  create no report row and no community entry; reviewers see only
  an audit event (hash, time, account id), never the bytes.
- Location is required: every upload must include coordinates plus
  an explicit consent flag (see 2.3). There are no location-less
  reports in Lite.

## Objectives

### 2.1 Schema and stores

Tables: `accounts` (id, email, password_hash, email_verified,
age_confirmed_at, status, reviewer (integer 0/1, default 0, set
only by the `make-reviewer` CLI), created_at), `reports` (id,
account_id, client_report_id, sha256, phash, status, created_at,
`location_lat` NOT NULL, `location_lng` NOT NULL,
`location_consented` (must be true), `location_source`
(`browser` or `manual_pin`)), `check_results` (report_id,
incident_probs, severity_probs, provenance, verdict, reasons),
`review_actions` (report_id, reviewer_account_id, action, before,
after, created_at; spec 4 fills this, create the table here),
`audit_events` (id, kind, actor_account_id, report_id nullable,
detail, created_at; kinds: `mock_rejection`, `review_action`,
`account_deletion`. Mock rejections store hash + time + account
id only, never image bytes or claim text).

This spec also creates `lite/app/cli.py` with
`python -m lite.app.cli make-reviewer <email>` (sets `reviewer`
to 1; errors on unknown email). Spec 4 uses it; no other role
changes exist in Lite.

**Acceptance criteria**

- [ ] Schema creates cleanly on an empty database and refuses a
  second init without error (tests).
- [ ] No column stores date of birth (schema test).
- [ ] Same `client_report_id` + account returns the existing report
  id without creating a new row or storing new files
  (first-wins idempotency test, including with differing bytes).
- [ ] `make-reviewer` sets the flag for a known email and errors
  for an unknown one (test).

### 2.2 Accounts and auth

Endpoints: `POST /auth/register`, `POST /auth/verify-email`,
`POST /auth/login`, `GET /account`, `DELETE /account`.

**Acceptance criteria**

- [ ] Under-age signup creates no account and stores no birth date
  (test).
- [ ] Unverified accounts cannot upload (test in 2.3).
- [ ] Register and password flows never reveal whether an email
  exists beyond the generic response (test).
- [ ] `DELETE /account` removes the account, its reports, and its
  uploaded files (test). No legal-hold concept in Lite.

### 2.3 Upload and processing pipeline

`POST /analyze` (multipart: photo + optional claim text +
`client_report_id` + required `location_lat`, `location_lng`,
`location_consented`, `location_source`). Location and consent
are mandatory: missing coordinates, missing consent flag, or
`location_consented` false returns 422 and stores nothing
(files, rows, audit events). `location_source` is `browser` or
`manual_pin`. Pipeline order is exactly spec 1's: file sanity,
mock hash gate, provenance, duplicates, CLIP checks, claim, fusion.
Processing is synchronous in Lite (small images, one user at a time);
the response is the finished report. This is a deliberate Lite
simplification — record it in the log, do not build a job queue.

Status mapping: unsupported type 415; oversize 413; unverified
account 403; missing location or consent 422. A completed upload
returns 200 with the finished report. A mock-hash match returns a
generic rejection body only ("upload could not be accepted" plus
the demo content notice), stores no file and no report row, and
writes one `mock_rejection` audit event (hash + time + account
id). There is no report id to fetch for a rejected upload.

**Acceptance criteria**

- [ ] JPEG/PNG accepted; other types 415; oversize 413 (tests).
- [ ] Missing coordinates or unchecked consent returns 422 with
  nothing stored (tests).
- [ ] Mock-hash-matched fixture: generic rejection body only, no
  file on disk, no report row, one audit event with hash/time/
  account and no image bytes (test).
- [ ] Pipeline call order asserted by a test with instrumented
  check functions (mock gate before CLIP).
- [ ] A completed upload returns incident probs, severity, verdict,
  reasons, confidence, and `needs_review` from spec 1 unchanged
  (test).

### 2.4 Report retrieval

Owner endpoints: `GET /reports/{id}` for the owner;
`GET /reports` lists own reports. Shared endpoints: `GET
/api/incidents` (spec 5; GeoJSON-style list of shared fields for
accepted reports from all accounts) and the community page
`GET /shared/{id}` (spec 5; shared fields plus photo for one
accepted report). Exact coordinates, uploader emails, and raw
file paths appear in no response from any endpoint.

**Acceptance criteria**

- [ ] Another account cannot read the owner endpoints (403/404
  test), but can read the shared endpoints for an accepted
  report (test).
- [ ] Every report response (owner and shared) contains no
  uploader email, no exact coordinates, and no raw file path
  (tests). The map receives only the deterministically jittered
  display point (spec 5).
- [ ] Rejected (mock-gate) uploads have no report id and return
  404 on every report endpoint (test); only the audit event
  exists, readable by reviewers (spec 4 test).

### 2.5 End-to-end smoke

Register, verify (console email file), upload a fixture with the
required location plus consent, read the report back. Scripted as
a pytest test against the app with a stubbed CLIP encoder, plus
one manual run with the real local model logged.

**Acceptance criteria**

- [ ] The stubbed end-to-end test passes in the suite.
- [ ] One real-model run is recorded in the log with device, timings,
  and the verdict produced. No accuracy claim is made.

## Agent notes

- Keep it one process and one database file. No workers, no queues,
  no caching layers.
- Console email only. Never wire a real email provider in Lite.
- If synchronous CLIP inference is slow on CPU, that is an observed
  timing in the log, not a reason to add infrastructure.

## Out of scope

HTML pages (spec 3), reviewer roles and actions (spec 4), real
email, rate limiting beyond the per-account upload cap and the
spec-4 login counter (both configured in `config.yaml`), any
external service.

## Definition of done

Every criterion recorded as passing in `lite/logs/spec2_log.md`,
full Lite suite green, one real-model end-to-end run logged.
