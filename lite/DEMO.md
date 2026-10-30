# iVouch Lite Demo Script

A manual click-through of the Lite demo. Takes 5-10 minutes once the
CLIP model is cached (first run adds the model download on top; see
step 1). Follow `lite/README.md` ("Run the demo locally") for setup.

Use two accounts so both sides of the sharing model are visible:

- Reporter: `reporter@example.com` (uploads the photo)
- Reviewer: `reviewer@example.com` (works the review queue)

## What this demo proves

- Signup, email verification (via console mail files), and login work.
- An upload with location plus consent produces a result card.
- A reviewer can confirm or correct a report, and the correction is
  shown to the owner with the original verdict still visible.
- Uploads are shared by design: another logged-in user can view the
  shared page. Email, exact coordinates, and file paths are never
  shared.

## What this demo does NOT prove

- Zero-shot labels are demo-grade, not accurate. No accuracy claim.
- The safety gate is a mock list over synthetic fixtures, not real
  screening, and is never described as such.
- There is no forensic AI-detector score (`None` in Lite).
- Nothing here is launch-ready or pilot-ready. Every result says
  "demo - needs human review."

## Steps

1. Start the server (about 30 seconds when warm).

   python -m lite.app.server

   Open http://127.0.0.1:8000 in the browser. First run only: the
   pinned CLIP model (openai/clip-vit-base-patch32, about 1.8 GB)
   downloads from HuggingFace into git-ignored
   `lite/data/artifacts/`. That download can take a long while and
   is the only slow step; everything below assumes it is cached.

2. Sign up the reporter account (about 1 minute).

   Go to `/signup`, enter `reporter@example.com` plus a password and
   submit. The page replies generically (it does not reveal whether
   an address is registered).

3. Verify the reporter via the console mail file (about 1 minute).

   Open the newest `verify_reporter_example_com_*.txt` file in
   `lite/data/mail/`, copy the `token:` value, and submit it on the
   `/verify` page (or the verify API). Log in as the reporter.

4. Sign up, verify, and promote the reviewer (about 2 minutes).

   Repeat steps 2-3 for `reviewer@example.com`, then in a terminal:

   python -m lite.app.cli make-reviewer reviewer@example.com

   Log in as the reviewer in a second browser profile (or private
   window) so both accounts stay signed in side by side.

5. Upload an image as the reporter (about 1-2 minutes on CPU).

   As the reporter, open `/upload`, pick a JPEG or PNG photo, add
   optional claim text, pick the required map location, tick the
   consent checkbox (it states the photo, claim text, approximate
   location, and verdict become visible to other logged-in demo
   users), and submit. The first inference after a fresh server start
   warms up the model and is slower; later uploads are faster.

6. Read the result page (about 1 minute).

   The result card shows the verdict (`likely-real`, `needs-review`,
   or `likely-manipulated`) with "signals observed" reasons, plus the
   demo disclaimer. Note the incident/severity labels: they are
   zero-shot guesses, not ground truth.

7. Work the review queue (about 2 minutes).

   As the reviewer, open `/review`. The queue lists `needs_review`
   first, then newest. Open the new report: the detail shows
   incident/severity probabilities, provenance flags, duplicate links,
   claim similarity, and fusion reasons, but never the uploader's
   email. Submit `correct` with a different incident type or
   severity, then submit `confirm` on another report (or a second
   upload) so both actions are exercised.

8. Re-read the result page as the reporter (about 1 minute).

   As the reporter, reopen the report. It now says "corrected by
   reviewer" with the new values, while the original demo verdict
   stays visible. The stored check outputs are unchanged; only the
   review overlay changed.

9. Open the shared page as the other user (about 1 minute).

   As the reviewer (or any second logged-in account), open the
   report's `/shared/{id}` page. Confirm the photo, claim text,
   approximate location, and verdict are visible, and that no email,
   exact coordinates, or file paths leak.

10. Map page: following-spec (spec 5, not yet built).

    There is currently no `/map` page in Lite; the login-required map
    with jittered dots arrives with spec 5. When it lands, this step
    becomes: as either user, open `/map` and confirm the accepted
    upload appears as a jittered dot whose photo matches the mapped
    area. Until then, skip this step.

11. DELETE flow (optional, about 1 minute).

    As the reporter, use the account page's delete action
    (`POST /account/delete`). Confirm the account and its data are
    removed and the session ends. Re-signup afterwards starts clean.

## Likely trouble

- Model download through proxies is slow or flaky. Retry the server
  start; the HuggingFace snapshot resumes into `lite/data/artifacts/`.
  If the network blocks HuggingFace entirely, the demo cannot run
  inference: record it as ENV-BLOCKED and stop, do not substitute
  another model or fake the verdicts.
- TestClient socket blocks do not affect real serving. The
  `WinError 10013` sandbox symptom applies to the test suite only;
  a real `python -m lite.app.server` in your own terminal binds and
  serves normally.
- Windows PowerShell variants. Activate with
  `.\.venv\Scripts\Activate.ps1`, set the secret with
  `$env:LITE_JWT_SECRET = "dev-only-local-demo-secret"`, and keep
  that terminal open for the server. `cmd.exe` uses
  `set LITE_JWT_SECRET=dev-only-local-demo-secret` instead.
- Port already in use. Either stop the other server or run
  `python -m lite.app.server --port 8001` and use
  http://127.0.0.1:8001 instead.
- Resetting the demo. Stop the server, delete `lite/data/ivouch.db`,
  `lite/data/uploads/`, and `lite/data/mail/` (all git-ignored), and
  restart. Keep `lite/data/artifacts/` so the model is not
  re-downloaded.
