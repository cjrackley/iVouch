# Lite Spec 0 — Foundations

**Why separate:** every later Lite spec shares one layout, one config
file, one test command, and one local model choice. Freezing those
here keeps later specs small.

| | |
|---|---|
| Depends on | nothing |
| Unblocks | specs 1-5 |
| Execution | Sequential only — spec 1 of 6 |
| Stack | Python 3.12, FastAPI, SQLite, Pillow, pytest, local CLIP |

## Human inputs

None required. Python 3.12, `uv` (or pip), and this PC's GPU are
checked, not assumed. Missing GPU means CPU inference (orchestrator
`ENV-BLOCKED` note, work continues). Docker is not required for Lite.

## Objectives

### 0.1 Layout and tooling

Create:

```text
lite/
  app/server/        # FastAPI app (specs 2-3)
  app/checks/        # image-check modules (spec 1)
  app/cli.py         # local CLI: make-reviewer (spec 2 creates, spec 4 uses)
  tests/             # pytest suite for all Lite specs
  data/artifacts/    # local model files (git-ignored, never committed)
  data/uploads/      # local upload store (git-ignored)
  data/mail/         # console-email files (git-ignored)
  work/checkpoints/  # builder checkpoints + entry files (git-ignored)
  config.yaml        # all Lite thresholds; no magic numbers in code
  requirements.txt   # every dependency pinned with exact version
```

`lite/DEMO.md` appears in spec 4 (extended in spec 5). `lite/logs/`
holds the per-spec logs the orchestrator writes.

Runner: plain commands, no `tasks.py` in Lite.

- `python -m pytest lite/tests -q` — the one test gate for all specs.
- `python -m lite.app.server` — local dev server (spec 2 wires routes).

**Acceptance criteria**

- [ ] `python -m pytest lite/tests -q` passes from a clean checkout
  of `lite/` on Windows PowerShell.
- [ ] `lite/requirements.txt` pins every dependency; each licence is
  recorded in the builder entry. No AGPL/GPL packages.
- [ ] `lite/data/` and `lite/work/` are git-ignored (verify with
  `git check-ignore`); no weights, uploads, mail files, or
  checkpoints in git.
- [ ] Python version is 3.12 (checked and logged). 3.11 is permitted
  with a log note (not a stop); below 3.11 is `ENV-BLOCKED` with the
  exact gap and a stop for the user.

### 0.2 Configuration

One file, `lite/config.yaml`, loaded by a single typed loader. Keys:

- `max_upload_bytes`, `allowed_types` (`jpeg`, `png`)
- `clip_model_id` (pinned, e.g. `openai/clip-vit-base-patch32`),
  `clip_device` (`cuda` with CPU fallback)
- `incident_prompts`, `severity_prompts` (spec 1 defines the text)
- `low_confidence_below`, `claim_mismatch_below`
- `phash_max_distance`, `duplicate_window`
- `policy_mock_hashes_path` (test-fixture hash list, spec 1)
- `min_age` (default 18), `jwt_access_minutes` (short-lived access token)
- `upload_cap_per_account` (spec 4 returns 429 past this)
- `login_ratelimit_max_attempts`, `login_ratelimit_window_seconds` (spec 4)
- `jitter_min_m`, `jitter_max_m` (display-point offset bounds, spec 5;
  default 200 and 500)
- `console_mail_dir` (default `lite/data/mail/`, spec 2)
- `location_required` (always `true` in Lite; spec 2 rejects uploads
  without location plus consent, spec 5 collects them)

Later specs use these keys as-is. If a later spec needs a new key,
its brief names the key and the builder adds it here with a default
and a decision note; the loader still rejects any key no spec names.

**Acceptance criteria**

- [ ] Loader rejects unknown keys and missing values with a clear
  error (unit tests).
- [ ] No threshold is re-typed as a literal outside the loader
  (grep test or code review note in the log).

### 0.3 Synthetic fixtures

Small generated images with Pillow (solid scenes, text, shapes) plus
variants: no EXIF, EXIF with GPS, EXIF with editor tag, re-encoded
JPEG quality 50, PNG. Unit-test use only, safe to commit, < 5 MB.

**Acceptance criteria**

- [ ] Fixtures are deterministic for a fixed seed (test). The
  generator pins the Pillow version (see `requirements.txt`) and
  uses only Pillow's built-in default font, so re-runs on the same
  checkout produce byte-identical fixtures.
- [ ] Each EXIF variant parses as claimed (test with Pillow/piexif).

### 0.4 Local model smoke check

Load the pinned CLIP model once from `lite/data/artifacts/` (download
from HuggingFace on first use; host listed in the brief's
`network_allowed`), run one fixture, record device used and load time.

**Acceptance criteria**

- [ ] Smoke test passes on GPU, or on CPU with the fallback logged.
- [ ] Model id, revision, file sizes, and licence recorded in the log.
  Weights never committed.

## Agent notes

- Keep this spec boring. No API routes, no UI, no fusion logic here.
- If HuggingFace is unreachable, this objective is `ENV-BLOCKED` with
  the exact error. Do not substitute a different model silently; a
  model swap is a decision recorded in the log.
- Network: a brief that downloads the model lists the HuggingFace
  host in `network_allowed`; a brief that installs packages lists
  PyPI there. Browser tile fetching at demo time is not agent
  network use (see spec 5).

## Out of scope

Image checks (spec 1), HTTP API (spec 2), pages (spec 3), review
(spec 4), anything outside `lite/`.

## Definition of done

Every criterion recorded as passing in `lite/logs/spec0_log.md`,
`python -m pytest lite/tests -q` green, model smoke result logged.
