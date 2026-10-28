# Phase 4 — Backend Core

**Why separate:** the backend is a different stack (FastAPI,
PostgreSQL/PostGIS/pgvector) and owns the system of record: accounts,
every upload, and the legally required trust-and-safety workflows
(CSAM quarantine and reporting, TAKE IT DOWN removals). Under the
sequential block schedule it runs after Phases 2–3 are accepted, so
real models are normally already published; it still starts against
stub models and mock providers within its own objectives and swaps in
the registered real models for its "real models" criteria, so a model
gap degrades to stubs instead of blocking the legal workflows. In
practice stubs are a fallback for model gaps, not the default path.

| | |
|---|---|
| Depends on | Phase 0 (contracts); Phases 2–3 artifacts for the "real models" criteria |
| Unblocks | Phases 5, 6, 7 |
| Execution | Sequential only — Block 2, phase 1 of 2 (Phase 5 follows automatically in the same block) |
| Stack | FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic, PostgreSQL 16 + PostGIS + pgvector, MinIO (S3 API), ONNX Runtime (CPU), pillow-heif, PyJWT, argon2-cffi |

## Human inputs (gate)

| Input | If missing (agent uses) |
|---|---|
| Email-sending provider + credentials | `ConsoleEmailSender` (writes emails to a local folder; dev/test only) |
| CSAM hash-matching access (PhotoDNA or Cloudflare) | `MockHashMatcher` (Phase 0; dev/test only) |
| NCMEC CyberTipline ESP registration + API credentials | `MockCyberTipClient` (records locally; never contacts NCMEC) |

Production hosting is decided in Phase 8. The server refuses to start
outside `dev`/`test` with any mock provider configured. Absent Docker
or database services are **ENV-BLOCKED**, never counted as builder
failures (orchestrator §7). Credentials are checked only via
`python tasks.py env-check --names ...`.

## Defaults (change only via decision record)

- **Every user has an account.** No anonymous access except endpoints
  marked *public* in DEVELOPMENT_PLAN §7. Roles: `user`, `reviewer`,
  `safety_officer`, `admin` (an account can hold several).
- **Auth:** email + password (argon2id), email verification required
  before the first upload, short-lived JWT access tokens + rotating
  refresh tokens (30 days, revocable, stored hashed). Token lifetimes
  and other protocol constants come from `config/policy.yaml`, not
  literals in code.
- **Age gate:** date of birth checked against `min_age` at signup and
  **not stored**; only `age_confirmed_at` is kept.
- **Job queue** is a Postgres `jobs` table polled with
  `SELECT … FOR UPDATE SKIP LOCKED` by a separate worker. No Redis.
- **Originals** encrypted at rest (envelope encryption, key from
  `ORIGINALS_KEY` in dev) and deleted after `RAW_RETENTION_DAYS`
  (in `thresholds.yaml`) unless under legal hold.
- **Quarantine** uses a separate bucket and key (`QUARANTINE_KEY`),
  readable only by code paths that check `safety_officer`.

## Objectives

### 4.1 Database schema and migrations

Tables: `accounts`, `account_roles`, `refresh_tokens`, `email_tokens`,
`devices` (install_id, platform, attestation key info, linked account
ids), `reports`, `media`, `analyses`, `locations`
(`GEOGRAPHY(Point,4326)` exact + display point), `embeddings`
(`vector(D)`), `authenticity`, `reviews`, `audit_log`, `jobs`,
`policy_acceptances`, `policy_rejections` (hash + time + category +
account id only, no image), `legal_holds`, `quarantine_items`,
`cybertip_reports`, `takedown_requests`, `takedown_actions`.
Migrations are a shared file set: one brief at a time (orchestrator §5).

**Acceptance criteria**

- [ ] `alembic upgrade head` and `downgrade base` both succeed on a
  clean DB (ENV-BLOCKED if no database is available, with the error
  recorded).
- [ ] GIST index on location points; HNSW (or IVFFlat) index on embeddings.
- [ ] No column stores date of birth (schema test).

### 4.2 Accounts and auth

```python
# server/ivserver/accounts/service.py
async def register(email: str, password: str, date_of_birth: date, accepted_terms_version: str) -> Account: ...  # raises UnderAge, EmailTaken
async def verify_email(token: str) -> None: ...
async def login(email: str, password: str) -> AuthTokens: ...
async def refresh(refresh_token: str) -> AuthTokens: ...          # rotates; reuse revokes the family
async def logout(refresh_token: str) -> None: ...
async def request_password_reset(email: str) -> None: ...          # same response whether or not the email exists
async def confirm_password_reset(token: str, new_password: str) -> None: ...
async def accept_policy(account_id: str, policy_version: str) -> None: ...
async def delete_account(account_id: str) -> DeletionReport: ...   # see 4.10
async def suspend_account(account_id: str, reason: str, actor: str) -> None: ...

# server/ivserver/accounts/deps.py
def current_account(required_roles: set[str] = {"user"}, require_verified: bool = True,
                    require_policy: bool = False) -> Callable: ...

# server/ivserver/email/sender.py
class EmailSender(Protocol):
    async def send(self, to: str, template: str, data: dict) -> None: ...
class ConsoleEmailSender: ...
```

**Acceptance criteria**

- [ ] Under-age signup returns a generic rejection, creates no
  account, stores no date of birth (test).
- [ ] Unverified accounts cannot upload; accounts without the current
  policy version cannot upload (tests).
- [ ] Password-reset and registration responses don't reveal whether
  an email exists (test).
- [ ] Refresh-token reuse revokes all tokens in that family (test).
- [ ] Login and password-reset endpoints rate-limited per IP and per
  email (limits in `thresholds.yaml`).
- [ ] Suspended accounts get 403 on all non-public endpoints and their
  reports leave the public map.

### 4.3 Ingest endpoint

`POST /v1/analyze` (multipart, authenticated): `photo` (original
bytes), `metadata` (JSON: `capture_metadata`, `location`, optional
`claim_text`, `device_result`, `client_report_id`, `attestation`).

```python
# server/ivserver/api/analyze.py
async def analyze(photo: UploadFile, metadata: AnalyzeMetadata,
                  account: Account = Depends(current_account(require_policy=True))) -> AnalyzeAccepted: ...
# server/ivserver/attestation/base.py
class AttestationVerifier(Protocol):
    async def verify(self, token: str | None, nonce: str, install_id: str,
                     account_id: str, platform: str) -> AttestationResult: ...
class DevAttestationVerifier: ...  # tokens only when ENV=dev; real Play Integrity verifier in Phase 5
```

**Acceptance criteria**

- [ ] Accepts JPEG, PNG, HEIC ≤ the size limit in `config/policy.yaml`;
  rejects others with 415/413.
- [ ] Same `client_report_id` + account returns the existing
  `report_id` (idempotent; offline queues retry).
- [ ] Returns `202 {report_id, status: "queued"}` in < 300 ms p95
  (bytes stored, job enqueued).
- [ ] The install is linked to the account in `devices`.

### 4.4 Processing worker

```python
# server/ivserver/worker/pipeline.py
def process_report(report_id: str) -> None: ...
def decode_and_orient(raw: bytes) -> Image.Image: ...
def csam_check(raw: bytes, matcher: HashMatcher) -> HashMatchResult: ...
def policy_recheck(img: Image.Image, runner: ModelRunner) -> PolicyDecision: ...
def run_core(img: Image.Image, runner: ModelRunner) -> CoreOutputs: ...
def compare_with_device(server: CoreOutputs, device: DeviceResult | None) -> ParityRecord: ...
def route_for_review(report: Report, thresholds: Thresholds) -> ReviewRouting: ...

# server/ivserver/models/runner.py
class ModelRunner(Protocol):
    def core(self, img: Image.Image) -> CoreOutputs: ...
    def segment(self, img: Image.Image, boxes: list[Box]) -> list[np.ndarray]: ...
    def faces(self, img: Image.Image) -> list[Box]: ...
    def plates(self, img: Image.Image) -> list[Box]: ...
class StubModelRunner: ...   # deterministic fake outputs keyed on image hash
class OnnxModelRunner: ...   # loads registered Phase 2-3 ONNX artifacts via the registry
```

Pipeline order:

1. **CSAM hash match** on raw bytes. Match → `quarantine_report()`
   (4.8), stop.
2. Decode + orient.
3. **Policy re-check**. Violation → delete stored bytes, record
   `policy_rejections` row, status `rejected_policy`, increment
   violation count (suspend at the `policy.yaml` threshold).
4. Core models → parity record → face/plate blur → public derivatives
   → encrypt original.
5. Authenticity (`AuthenticityService` stub here, real in Phase 5) →
   review routing → status `complete`.

**Acceptance criteria**

- [ ] Hash matching runs before any other processing, thumbnail or log
  line that includes image content (test asserts call order).
- [ ] Policy-violating (non-CSAM) uploads leave **no image bytes**
  anywhere after processing (test with the stub flagging a fixture).
- [ ] Worker survives a crash mid-job; job retried at most
  `max_attempts` times, then `failed` with an error.
- [ ] Device/server disagreement (top incident differs or severity
  differs by ≥ 2 levels) is recorded and forces review.
- [ ] Routing: low confidence, high severity, disagreement,
  `low_confidence` incident types, or an `unavailable` policy category
  → review queue.
- [ ] With `OnnxModelRunner`, server outputs match Phase 2–3 test
  vectors within tolerance. Missing artifacts make this criterion
  ENV-BLOCKED (expected path named), not failed.

### 4.5 Report retrieval

`GET /v1/reports/{id}`: incident types, severity, rationale, masks,
authenticity result, confidence, display location, `thumbnail_url`,
`photo_url` (blurred).

**Acceptance criteria**

- [ ] Owners and other users never receive exact coordinates, the
  original, or the submitter's identity (test per role).
- [ ] Reviewer access to originals returns a short-lived signed URL
  and writes an `audit_log` row.
- [ ] Quarantined and removed reports return 404 to every role except
  `safety_officer` (via 4.8/4.9 endpoints only).

### 4.6 Review endpoints

`GET /v1/review-queue` (reviewer; severity, then confidence ascending,
then age) and `POST /v1/reviews/{id}` (`confirm` / `correct` /
`escalate` / `flag_csam`).

**Acceptance criteria**

- [ ] Every review action writes an audit row with reviewer id and
  before/after values.
- [ ] `flag_csam` immediately removes the report from all queues, the
  map and the reviewer's view, and calls
  `quarantine_report(source="reviewer_flag")` (test).
- [ ] Corrections are queryable for retraining
  (`export_review_labels()`, used in Phase 7); quarantined items are
  never exported.

### 4.7 Map endpoint

`GET /v1/incidents?bbox=…&zoom=…&types=…&severity=…&since=…&limit=…`
(authenticated), GeoJSON `FeatureCollection` per DEVELOPMENT_PLAN §7.

```python
# server/ivserver/geo/display.py
def display_point(exact: tuple[float, float], report_id: str, secret: bytes, radius_m: tuple[int, int]) -> tuple[float, float]: ...
```

**Acceptance criteria**

- [ ] Display jitter deterministic per report (HMAC of report id +
  server secret), so repeated requests can't be averaged to recover
  the exact point (test).
- [ ] Excludes non-consented, ungeolocated, policy-rejected,
  quarantined, removed, suspended-account and (by default)
  `likely-manipulated` reports.
- [ ] p95 < 300 ms at 1M synthetic reports (load script
  `infra/load/seed_reports.py`; ENV-BLOCKED without a database).
- [ ] `truncated: true` when results exceed `limit`.

### 4.8 CSAM quarantine, legal holds and CyberTipline reports

```python
# server/ivserver/safety/quarantine.py
def quarantine_report(report_id: str, source: Literal["hash_match", "reviewer_flag"], match: HashMatchResult | None,
                      actor: str | None) -> QuarantineItem: ...
def place_legal_hold(object_ref: str, reason: str, until: datetime) -> None: ...
def release_expired_holds(now: datetime, officer: Account) -> list[str]: ...  # officer confirms each release
def view_quarantined(item_id: str, officer: Account, justification: str) -> SignedUrl: ...  # audit-logged

# server/ivserver/safety/cybertip.py
def prepare_cybertip_report(item_id: str) -> CyberTipDraft: ...
class CyberTipClient(Protocol):
    def submit(self, draft: CyberTipDraft, officer: Account) -> CyberTipSubmission: ...
class MockCyberTipClient: ...    # writes locally; the only client allowed in dev/test
```

**Acceptance criteria**

- [ ] After quarantine, the only remaining copy is in the quarantine
  bucket (test lists all buckets/tables).
- [ ] Legal-held objects survive the retention job and account
  deletion (frozen-clock tests).
- [ ] Only `safety_officer` can list, view or report quarantined
  items; every action requires a justification and writes an audit
  row (tests per role).
- [ ] Reports are submitted only by an explicit officer action; nothing
  is sent automatically. `MockCyberTipClient` is the only client when
  `ENV` is `dev`/`test` (test).
- [ ] The uploading user receives only a generic "upload could not be
  accepted" error.
- [ ] Quarantine storage is excluded from general backups; its own
  backup path is documented in Phase 8.

### 4.9 TAKE IT DOWN removal requests

`POST /v1/takedown-requests` (*public*, rate-limited, CAPTCHA-ready
hook): requester name, email, electronic signature, content locator,
good-faith statement. Returns request id + status token.
`GET /v1/takedown-requests/{id}?token=…` returns status.

```python
# server/ivserver/safety/takedown.py
async def submit_takedown(req: TakedownRequestIn) -> TakedownReceipt: ...  # deadline_at = received_at + deadline hours from policy.yaml
def validate_takedown(req_id: str, officer: Account) -> ValidationResult: ...
def execute_takedown(req_id: str, officer: Account) -> TakedownActionReport: ...
def overdue_takedowns(now: datetime) -> list[TakedownRequest]: ...
```

**Acceptance criteria**

- [ ] Missing required fields are rejected with a clear message
  listing them.
- [ ] `execute_takedown` removes the target and every duplicate above
  the configured similarity threshold (test with resized/re-encoded
  copies).
- [ ] Requests open longer than `takedown.alert_after_h` (in
  `thresholds.yaml`) raise an alert; `overdue_takedowns` is exposed
  for the Phase 7 dashboard.
- [ ] Every step (received, validated, executed, notified) is
  audit-logged with timestamps.
- [ ] The requester is emailed on receipt and on completion.

### 4.10 Account deletion

**Acceptance criteria**

- [ ] `DELETE /v1/account` (and the Phase 7 web page) removes the
  account, its tokens, device links, reports, media, embeddings and
  map entries.
- [ ] Legal-held items are kept (detached from the deleted profile)
  and listed in the `DeletionReport` for audit only.
- [ ] Audit rows are kept with the account id pseudonymized.
- [ ] Deletion completes within the window in `config/policy.yaml`
  (surfaced in `TERMS.md`), tested with a frozen clock.

### 4.11 Policy, attestation challenge

- `GET /v1/policy` (*public*) → policy, terms, removal notice +
  versions; `POST /v1/policy/accept`.
- `POST /v1/attestation/challenge` (authenticated) → single-use nonce
  (expiry from `policy.yaml`) bound to account + `install_id`.

**Acceptance criteria**

- [ ] Nonces cannot be reused or used by another account (tests).
- [ ] Per-account, per-device and per-IP rate limits on `/v1/analyze`
  (values in `thresholds.yaml`).

### 4.12 Retention job

```python
# server/ivserver/jobs/retention.py
def purge_expired_originals(now: datetime) -> PurgeReport: ...
```

**Acceptance criteria**

- [ ] Originals older than `RAW_RETENTION_DAYS` are deleted and their
  keys nulled, **except** legal-held objects; frozen-clock test.

## Agent notes

- Android uploads may include HEIC (gallery imports); register
  `pillow-heif` at startup.
- Strip EXIF only from **public derivatives**. The encrypted original
  keeps it for Phase 5.
- Keep every endpoint matching `contracts/openapi.yaml`; add a
  contract test that diffs FastAPI's generated schema against it.
  Briefs that add or change endpoints list `contracts/openapi.yaml` in
  `unlocked_paths`.
- **Never** use real CSAM in any test. The mock hash matcher matches
  benign synthetic fixtures only.
- Never contact NCMEC or any outside party. Humans submit real reports.
- Check NCMEC's current CyberTipline API documentation (available
  after registration) before finalizing `CyberTipDraft`; keep fields
  configurable until then.

## Out of scope

Real Play Integrity verification (Phase 5), duplicates/C2PA/reverse
search/corroboration/forensics/escalation (Phase 5), web pages (Phase 7).

## Definition of done

`python tasks.py up` and `python tasks.py check` green, and every
acceptance criterion recorded as passing in `logs/spec4_log.md` (the
boxes above are spec source text and are never ticked; see
`logs/README.md`). End-to-end tests with
`StubModelRunner` and mock providers: (1) register → verify → accept
policy → upload fixture → complete report → review action; (2) upload
mock-matched fixture → quarantine → officer prepares mock CyberTip
report; (3) takedown request → execute → target and copies removed.
Re-run (1) with `OnnxModelRunner` once Phase 2–3 artifacts exist.
Criteria defined against mocks (the flows above) can pass on mocks.
Criteria that name a real input — the `OnnxModelRunner` test-vector
criterion, the 1M-report map latency criterion without a database —
stay open (ENV-BLOCKED, missing service or expected path named) and
keep the phase incomplete under orchestrator §7. There is no partial
completion.
