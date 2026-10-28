# Phase 8 — Hardening and Pilot Readiness

This is the final v1 phase: Block 4, a single phase.

**Why separate:** red-teaming, bias evaluation, load testing and abuse
controls only mean something once everything is integrated end to end.
This phase is the final gate before any partner pilot, and the
remaining human decisions (hosting, legal review, pilot partner) are
concentrated here.

| | |
|---|---|
| Depends on | Phases 4–7 |
| Unblocks | Pilot |
| Execution | Sequential only — Block 4, single phase (manual stop after this phase; end of v1 build) |
| Stack | pytest + Playwright E2E, Locust or k6 for load, structured logging + Prometheus-style metrics |

## Human inputs (gate)

ENV-BLOCKED and user-decision items are listed separately: missing
infrastructure never blocks report-writing objectives, and no public
launch happens while a launch-checklist item is `blocked`.

| Input | If missing |
|---|---|
| Production hosting choice + credentials | Deploy to a local/staging Docker Compose environment only |
| Privacy/legal review (consent text, terms, minimum age, retention, regional rules, CSAM and TAKE IT DOWN workflows) | Launch-checklist items `blocked` |
| NCMEC CyberTipline registration and real CSAM hash-matching access | Launch-checklist items `blocked`; **no public launch without them** |
| Commercial license review of datasets and models | Registry rows stay `research`; launch checklist `blocked` |
| Pilot partner organization | Prepare pilot pack; stop before contact |

## Objectives

### 8.1 End-to-end and chaos tests

**Acceptance criteria**

- [ ] E2E suites for Android (emulator) and web: register → verify →
  capture/upload → report → review → map dot → account deletion.
  Emulator unavailability is ENV-BLOCKED with the error recorded.
- [ ] Chaos cases pass: no GPS, stripped EXIF, re-encoded image, HEIC,
  offline capture then reconnect, expired session while offline,
  worker crash mid-job, provider timeouts (reverse search, escalation,
  hash matching, email), DB restart.
- [ ] Hash-matching provider outage: uploads stay queued (not
  processed, not published) until the check succeeds (test).

### 8.2 Red-team suite

`eval/redteam/` with automated cases:

- AI-generated incident images (held-out generators), spliced/edited
  photos, old web photos re-uploaded as new, forged EXIF times/GPS,
  replayed attestation tokens, tokens bound to another account, same
  image from many accounts (fake corroboration), many accounts on one
  device, mass account creation, suspended users re-registering,
  policy evasion for both categories (crops, filters, overlays),
  takedown evasion (re-uploading removed content with small edits).

**Acceptance criteria**

- [ ] Each case has an expected outcome (e.g. `needs-review` at
  minimum, or `invalid` attestation) and runs in CI whenever the user
  pushes (local runs are the agent-side evidence; CI results are
  appended to the log when available).
- [ ] Results summarized in `eval/reports/redteam.md` with any
  threshold changes recorded as decisions. Threshold *lowering* still
  needs the user (orchestrator §9).

### 8.3 Bias and robustness evaluation

**Acceptance criteria**

- [ ] Incident, severity, policy and authenticity metrics reported
  stratified by region (where metadata allows), lighting
  (day/night/low-light), device class, and capture source.
- [ ] Any stratum whose false-accusation rate exceeds 2× the overall
  rate is flagged with a mitigation plan.

### 8.4 Load and performance

**Acceptance criteria**

- [ ] `GET /v1/incidents` p95 < 300 ms at 1M reports under concurrent
  load (ENV-BLOCKED without a database/load environment; the load
  script and baseline numbers are still deliverables).
- [ ] Ingest sustains a target uploads/minute (set in
  `thresholds.yaml` after a baseline run — setting it from a measured
  baseline is calibration, not lowering a target) with worker scaling
  documented.
- [ ] Device-vs-server parity drift tracked as a metric with an alert
  threshold.

### 8.5 Abuse controls and security

**Acceptance criteria**

- [ ] Rate limits per account, per device, per IP and per attestation
  identity verified by tests; signup and login limits included.
- [ ] Role-based access matrix test: every endpoint × every role
  (`anonymous`, `user`, `reviewer`, `safety_officer`, `admin`) returns
  the expected status.
- [ ] Dependency vulnerability scan in CI (pip-audit, Gradle
  dependency check) with no high/critical findings.
- [ ] Secrets only from env/secret manager; a test greps the repo and
  built artifacts for key patterns (and confirms `tasks.py env-check`
  output contains no secret values).
- [ ] Security checklist (auth, CSRF, signed URLs, audit log
  integrity, encryption at rest, TLS) completed in
  `docs/SECURITY_CHECKLIST.md`.

### 8.6 Operations

**Acceptance criteria**

- [ ] `docs/RUNBOOK.md`: deploy, rollback, rotate keys (incl.
  `QUARANTINE_KEY`), handle a TAKE IT DOWN request end to end, handle
  a hash match or reviewer CSAM flag (quarantine → officer review →
  CyberTipline report → legal hold), respond to a policy-violating
  upload that slipped through, handle an account deletion request,
  model rollback (registry + `ARTIFACT_ROOT`).
- [ ] Retention purge verified on staging (or local Docker) with real
  timestamps; legal-held items confirmed untouched.
- [ ] Backups + restore tested once; quarantine storage backed up
  separately with the same access controls, or excluded with the
  decision recorded.
- [ ] Quarantine storage security checked against the NIST
  Cybersecurity Framework items listed in `docs/SECURITY_CHECKLIST.md`.

### 8.7 Pilot readiness pack

**Acceptance criteria**

- [ ] `docs/PILOT_PACK.md`: what the system does and doesn't do, "not
  for emergency use", no auto-dispatch, account requirements and
  minimum age, known limitations from model cards and red-team
  results, reviewer and safety-officer training notes,
  contact/takedown process. States plainly that v1 is Android + web
  only.
- [ ] Store-compliance check: account deletion in the Android app and
  on the web, Play Console data-safety form drafted for the user to
  submit.
- [ ] Launch checklist with every human gate from all phases and its
  status. A blocked launch item keeps this objective open
  (NEEDS-USER-APPROVAL) and Phase 8 incomplete: the checklist being
  written is not the same as the launch being ready, and no phase
  status may imply "ready for the user to finish launch". Only when
  every item is provided, or removed by the user editing the
  requirement itself, does the objective pass — and even then
  it means "ready for the user to launch", never "launched".

## Agent notes

- Do not contact any external organization (including NCMEC). The
  pilot pack is prepared for the user to send.
- Red-team images for both policy categories must come from the
  approved Phase 1 policy sets; never collect new ones from the web.
- CSAM handling is red-teamed only with mock-matched synthetic
  fixtures. Never use or seek real material.
- Every long suite (load, red-team, bias eval) is checkpointed under
  `work/checkpoints/` so a session boundary doesn't restart it. Briefs
  list load-tool and browser-download hosts in `network_allowed`.

## Out of scope

Auto-dispatch, insurance integrations, v2 features (iOS client,
multi-photo fusion, video, ImageBind, server-delivered model updates).

## Definition of done

All suites green locally, reports published, and every acceptance
criterion recorded as passing in `logs/spec8_log.md` (the boxes above
are spec source text and are never ticked; see `logs/README.md`). A
suite that cannot run is ENV-BLOCKED with the missing environment
named, and a launch checklist with any item still blocked keeps 8.7
open (NEEDS-USER-APPROVAL); either keeps Phase 8 incomplete under
orchestrator §7. Human-owned items remaining on the checklist are
reported in `# Phase status`, not absorbed into a completion report.
There is no partial completion.
