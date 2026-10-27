# Phase 4 — Backend Core

**Why this is its own phase:** The backend is a different stack (FastAPI, PostgreSQL/PostGIS/pgvector) and owns the system of record: accounts, every upload, and the legally required trust-and-safety workflows (CSAM quarantine and reporting, TAKE IT DOWN removals). It can start right after Phase 0 using stub models and mock providers, so it runs in parallel with model training and swaps in real models when Phases 2–3 publish them.

| | |
|---|---|
| Depends on | Phase 0 (contracts); Phases 2–3 artifacts for the "real models" criteria |
| Unblocks | Phases 5, 6, 7, 8 |
| Parallel with | Phases 1, 2, 3 |
| Stack | FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic, PostgreSQL 16 + PostGIS + pgvector, MinIO (S3 API), ONNX Runtime (CPU), pillow-heif, PyJWT, argon2-cffi |

## Human inputs (gate)

| Input | If missing (agent uses) |
|---|---|
| Email-sending provider + credentials | `ConsoleEmailSender` (writes emails to a local folder; dev/test only) |
| CSAM hash-matching access (PhotoDNA or Cloudflare CSAM Scanning Tool) | `MockHashMatcher` (Phase 0; dev/test only) |
| NCMEC CyberTipline electronic service provider registration + API credentials | `MockCyberTipClient` (records the report locally; never contacts NCMEC) |

Production hosting is decided in Phase 9. The server refuses to start outside `dev`/`test` with any mock provider configured.

## Defaults (change only via decision record)

- **Every user has an account.** No anonymous access to any endpoint except those marked *public* in DEVELOPMENT_PLAN §7. Roles: `user`, `reviewer`, `safety_officer`, `admin` (an account can hold several).
- **Auth:** email + password (argon2id), email verification required before the first upload, short-lived JWT access tokens (15 min) + rotating refresh tokens (30 days, revocable, stored hashed).
- **Age gate:** date of birth checked against `min_age` at signup and **not stored**; only `age_confirmed_at` is kept. Under-age attempts are rejected without creating an account.
- **Job queue** is a Postgres `jobs` table polled with `SELECT … FOR UPDATE SKIP LOCKED` by a separate worker process. No Redis.
- **Originals** are encrypted at rest (envelope encryption, key from `ORIGINALS_KEY` env var in dev) and deleted after `RAW_RETENTION_DAYS` (in `thresholds.yaml`) unless under a legal hold.
- **Quarantine** uses a separate bucket and a separate key (`QUARANTINE_KEY`), readable only by code paths that check the `safety_officer` role.

## Objectives

### 4.1 Database schema and migrations

Tables: `accounts`, `account_roles`, `refresh_tokens`, `email_tokens` (verification + password reset), `devices` (install_id, platform, attestation key info, linked account ids), `reports` (account_id), `media` (original_key, blurred_key, thumb_key, sha256, phash), `analyses` (device + server outputs, model versions), `locations` (`GEOGRAPHY(Point,4326)` exact + display point), `embeddings` (`vector(D)`), `authenticity` (signals + result), `reviews`, `audit_log`, `jobs`, `policy_acceptances`, `policy_rejections` (sha256 + time + category + account id only, no image), `legal_holds`, `quarantine_items`, `cybertip_reports`, `takedown_requests`, `takedown_actions`.

**Acceptance criteria**
- [ ] `alembic upgrade head` and `downgrade base` both succeed on a clean DB.
- [ ] GIST index on location points; HNSW (or IVFFlat) index on embeddings.
- [ ] No column stores date of birth (schema test).

### 4.2 Accounts and auth

**Functions**
```python
# server/ivserver/accounts/service.py
async def register(email: str, password: str, date_of_birth: date, accepted_terms_version: str) -> Account: ...  # raises UnderAge, EmailTaken
async def verify_email(token: str) -> None: ...
async def login(email: str, password: str) -> AuthTokens: ...
async def refresh(refresh_token: str) -> AuthTokens: ...          # rotates; reuse of an old token revokes the family
async def logout(refresh_token: str) -> None: ...
async def request_password_reset(email: str) -> None: ...          # same response whether or not the email exists
async def confirm_password_reset(token: str, new_password: str) -> None: ...
async def accept_policy(account_id: str, policy_version: str) -> None: ...
async def delete_account(account_id: str) -> DeletionReport: ...   # see 4.10
async def suspend_account(account_id: str, reason: str, actor: str) -> None: ...

# server/ivserver/accounts/deps.py
def current_account(required_roles: set[str] = {"user"}, require_verified: bool = True,
                    require_policy: bool = False) -> Callable: ...   # FastAPI dependency

# server/ivserver/email/sender.py
class EmailSender(Protocol):
    async def send(self, to: str, template: str, data: dict) -> None: ...
class ConsoleEmailSender: ...
```

**Acceptance criteria**
- [ ] Under-age signup returns a generic rejection, creates no account, and stores no date of birth (test).
- [ ] Unverified accounts cannot upload; accounts without the current policy version accepted cannot upload (tests).
- [ ] Password reset and registration responses don't reveal whether an email exists (test).
- [ ] Refresh-token reuse revokes all tokens in that family (test).
- [ ] Login and password-reset endpoints are rate-limited per IP and per email.
- [ ] Suspended accounts get 403 on all non-public endpoints and their reports leave the public map.

### 4.3 Ingest endpoint

`POST /v1/analyze` (multipart, authenticated): `photo` (original bytes), `metadata` (JSON: `capture_metadata`, `location`, optional `claim_text`, `device_result`, `client_report_id`, `attestation`).

**Functions**
```python
# server/ivserver/api/analyze.py
async def analyze(photo: UploadFile, metadata: AnalyzeMetadata,
                  account: Account = Depends(current_account(require_policy=True))) -> AnalyzeAccepted: ...
# server/ivserver/attestation/base.py
class AttestationVerifier(Protocol):
    async def verify(self, token: str | None, nonce: str, install_id: str,
                     account_id: str, platform: str) -> AttestationResult: ...
class DevAttestationVerifier: ...  # accepts tokens only when ENV=dev; real verifiers in Phase 5
```

**Acceptance criteria**
- [ ] Accepts JPEG, PNG, HEIC ≤ 15 MB; rejects others with 415/413.
- [ ] Same `client_report_id` + account returns the existing `report_id` (idempotent; offline queues retry).
- [ ] Returns `202 {report_id, status: "queued"}` in < 300 ms p95 (bytes stored, job enqueued).
- [ ] The install is linked to the account in `devices`.

### 4.4 Processing worker

**Functions**
```python
# server/ivserver/worker/pipeline.py
def process_report(report_id: str) -> None: ...
def decode_and_orient(raw: bytes) -> Image.Image: ...
def csam_check(raw: bytes, matcher: HashMatcher) -> HashMatchResult: ...
def policy_recheck(img: Image.Image, runner: ModelRunner) -> PolicyDecision: ...   # per-category thresholds
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
class OnnxModelRunner: ...   # loads registered Phase 2–3 ONNX artifacts
```

Pipeline order:
1. **CSAM hash match** on the raw bytes. Match → `quarantine_report()` (4.8), stop.
2. Decode + orient.
3. **Policy re-check** (`violence_gore`, `nudity_sexual`). Violation → delete stored bytes, record `policy_rejections` row, status `rejected_policy`, increment the account's violation count (suspend at the `policy.yaml` threshold).
4. Core models → parity record → face/plate blur → public derivatives → encrypt original.
5. Authenticity (`AuthenticityService` stub here, real in Phase 5) → review routing → status `complete`.

**Acceptance criteria**
- [ ] Hash matching runs before any other processing, thumbnail or log line that includes image content (test asserts call order).
- [ ] Policy-violating (non-CSAM) uploads leave **no image bytes** anywhere (storage, DB, logs) after processing (test with the stub flagging a fixture).
- [ ] Worker survives a crash mid-job; job is retried at most `max_attempts` times, then `failed` with an error.
- [ ] Device/server disagreement (top incident differs or severity differs by ≥ 2 levels) is recorded and forces review.
- [ ] Routing: low confidence, high severity, disagreement, `low_confidence` incident types, or an `unavailable` policy category → review queue.
- [ ] With `OnnxModelRunner`, server outputs match Phase 2–3 test vectors within their stated tolerances.

### 4.5 Report retrieval

`GET /v1/reports/{id}`: incident types, severity, rationale, masks (as polygons or PNG URLs), authenticity result, confidence, `location {lat_display, lng_display, accuracy_m, source, verified}`, `thumbnail_url`, `photo_url` (blurred).

**Acceptance criteria**
- [ ] Owners and other users never receive exact coordinates, the original, or the submitter's identity (test per role).
- [ ] Reviewer access to originals returns a short-lived signed URL and writes an `audit_log` row.
- [ ] Quarantined and removed reports return 404 to every role except `safety_officer` (via 4.8/4.9 endpoints only).

### 4.6 Review endpoints

`GET /v1/review-queue` (reviewer; sorted by severity, then confidence ascending, then age) and `POST /v1/reviews/{id}` (`confirm` / `correct` with corrected fields / `escalate` / `flag_csam`).

**Acceptance criteria**
- [ ] Every review action writes an audit row with reviewer id, before/after values.
- [ ] `flag_csam` immediately removes the report from all queues, the map and the reviewer's view, and calls `quarantine_report(source="reviewer_flag")` (test).
- [ ] Corrections are queryable for retraining (`export_review_labels()` used in Phase 8); quarantined items are never exported.

### 4.7 Map endpoint

`GET /v1/incidents?bbox=…&zoom=…&types=…&severity=…&since=…&limit=…` (authenticated) returning a GeoJSON `FeatureCollection` per DEVELOPMENT_PLAN §7.

**Functions**
```python
# server/ivserver/geo/display.py
def display_point(exact: tuple[float, float], report_id: str, secret: bytes, radius_m: tuple[int, int]) -> tuple[float, float]: ...
```

**Acceptance criteria**
- [ ] Display jitter is deterministic per report (seeded by HMAC of report id + server secret) so repeated requests cannot be averaged to recover the exact point (test).
- [ ] Excludes non-consented, ungeolocated, policy-rejected, quarantined, removed, suspended-account and (by default) `likely-manipulated` reports.
- [ ] p95 < 300 ms at 1M synthetic reports (load script `infra/load/seed_reports.py`).
- [ ] `truncated: true` when results exceed `limit`.

### 4.8 CSAM quarantine, legal holds and CyberTipline reports

**Functions**
```python
# server/ivserver/safety/quarantine.py
def quarantine_report(report_id: str, source: Literal["hash_match", "reviewer_flag"], match: HashMatchResult | None,
                      actor: str | None) -> QuarantineItem: ...
    # moves original bytes to the quarantine bucket (QUARANTINE_KEY), deletes every other copy
    # (blurred, thumbnail, embeddings, cached masks), places a 1-year legal hold, suspends the account
def place_legal_hold(object_ref: str, reason: str, until: datetime) -> None: ...
def release_expired_holds(now: datetime) -> list[str]: ...        # only after a safety officer confirms
def view_quarantined(item_id: str, officer: Account, justification: str) -> SignedUrl: ...  # audit-logged

# server/ivserver/safety/cybertip.py
def prepare_cybertip_report(item_id: str) -> CyberTipDraft: ...   # incident time, account email, IP, upload metadata, file reference
class CyberTipClient(Protocol):
    def submit(self, draft: CyberTipDraft, officer: Account) -> CyberTipSubmission: ...
class MockCyberTipClient: ...    # writes locally; the only client allowed in dev/test
```

**Acceptance criteria**
- [ ] After quarantine, the only remaining copy of the image is in the quarantine bucket (test lists all buckets/tables).
- [ ] Legal-held objects survive the retention job and account deletion (tests with a frozen clock).
- [ ] Only `safety_officer` can list, view or report quarantined items; every action requires a justification and writes an audit row (tests per role).
- [ ] Reports are submitted only by an explicit officer action; nothing is sent automatically. `MockCyberTipClient` is the only client usable when `ENV` is `dev`/`test` (test).
- [ ] The uploading user receives only a generic "upload could not be accepted" error; no quarantine details appear in any API response to them.
- [ ] Quarantine storage is excluded from general backups; its own backup path is documented in Phase 9.

### 4.9 TAKE IT DOWN removal requests

`POST /v1/takedown-requests` (*public*, rate-limited, CAPTCHA-ready hook): requester name, email, electronic signature, content locator, good-faith statement. Returns a request id + status token. `GET /v1/takedown-requests/{id}?token=…` returns status.

**Functions**
```python
# server/ivserver/safety/takedown.py
async def submit_takedown(req: TakedownRequestIn) -> TakedownReceipt: ...       # sets deadline_at = received_at + 48 h
def validate_takedown(req_id: str, officer: Account) -> ValidationResult: ...  # complete fields + locatable content
def execute_takedown(req_id: str, officer: Account) -> TakedownActionReport: ...
    # removes the located content and finds identical copies via sha256 + pHash + embedding search; removes those too
def overdue_takedowns(now: datetime) -> list[TakedownRequest]: ...
```

**Acceptance criteria**
- [ ] Requests missing a required field are rejected with a clear message listing the missing fields.
- [ ] `execute_takedown` removes the target and every duplicate above the configured similarity threshold (test with resized/re-encoded copies).
- [ ] Requests open for more than `takedown.alert_after_h` (default 24 h, in `thresholds.yaml`) raise an alert; `overdue_takedowns` is exposed for the Phase 8 dashboard.
- [ ] Every step (received, validated, executed, notified) is audit-logged with timestamps.
- [ ] The requester is emailed on receipt and on completion.

### 4.10 Account deletion

**Acceptance criteria**
- [ ] `DELETE /v1/account` (and the Phase 8 web page) removes the account, its tokens, devices links, reports, media, embeddings and map entries.
- [ ] Items under legal hold are kept (detached from the deleted account's profile) and listed in the `DeletionReport` for audit only.
- [ ] Audit rows are kept with the account id pseudonymized.
- [ ] Deletion completes within the window stated in `TERMS.md` (configurable), tested with a frozen clock.

### 4.11 Policy, attestation challenge

- `GET /v1/policy` (*public*) → content policy, terms, removal-request notice + versions; `POST /v1/policy/accept`.
- `POST /v1/attestation/challenge` (authenticated) → single-use nonce (expires in 5 min) bound to account + `install_id`.

**Acceptance criteria**
- [ ] Nonces cannot be reused or used by another account (tests).
- [ ] Per-account, per-device and per-IP rate limits on `/v1/analyze` (values in `thresholds.yaml`).

### 4.12 Retention job

**Functions**
```python
# server/ivserver/jobs/retention.py
def purge_expired_originals(now: datetime) -> PurgeReport: ...
```

**Acceptance criteria**
- [ ] Originals older than `RAW_RETENTION_DAYS` are deleted from storage and their keys nulled, **except** objects under legal hold; test uses a frozen clock.

## Agent notes

- iPhones upload HEIC by default; register `pillow-heif` at startup.
- Strip EXIF only from **public derivatives**. The encrypted original keeps it for Phase 5.
- Keep every endpoint matching `contracts/openapi.yaml`; add a contract test that diffs FastAPI's generated schema against it.
- **Never** use real CSAM in any test. The mock hash matcher "matches" benign synthetic fixtures only.
- Never contact NCMEC or any outside party. The CyberTip client is built and tested against the mock; a human submits real reports.
- Check NCMEC's current CyberTipline API documentation (available after registration) before finalizing `CyberTipDraft` fields; keep them configurable until then.

## Out of scope

Real attestation verification, duplicates for authenticity, C2PA, reverse search, corroboration, forensic scoring, escalation (Phase 5); web pages and consoles (Phase 8).

## Definition of done

`make up && make check` green; end-to-end tests passing with `StubModelRunner` and mock providers: (1) register → verify → accept policy → upload fixture → complete report → review action; (2) upload a mock-matched fixture → quarantine → officer prepares mock CyberTip report; (3) takedown request → execute → target and copies removed. Re-run (1) with `OnnxModelRunner` once Phase 2–3 artifacts exist.
