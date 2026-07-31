# Book System OS operator/admin manual

This note is for running and checking the Book System OS dashboard and publish gateway safely.

It is an operator guide, not a developer design document.

## Current service role

Book System OS is the publishing/job system behind:

    publish.toiletrage.co.uk

The current service supports the original book-system route, `/api/v1` status,
manuscript validation and publish dry-run planning.

## Important URLs

Local server checks:

    http://127.0.0.1:8080/health

Public checks:

    https://publish.toiletrage.co.uk/health
    https://publish.toiletrage.co.uk/api/v1/status

The `/api/v1/status` endpoint reports:

- gateway identity
- service name
- app version
- enabled route group
- whether write actions are enabled
- implemented routes
- planned routes not implemented yet

## Current implemented routes

At the current checkpoint, `/api/v1/status` should list these implemented routes:

- `GET /health`
- `GET /ready`
- `GET /api/v1/status`
- `POST /api/v1/validate`
- `POST /api/v1/publish/dry-run`
- `POST /api/submit`
- `GET /api/jobs/{job_id}`

It may also list planned v1 publish execution routes that are not implemented yet.

Do not treat `not_yet_implemented` routes as live behaviour.

## Publish dry-run

The publish dry-run route is:

    POST /api/v1/publish/dry-run

It uses the existing API-key authentication in production.

Dry-run validates the supplied manuscript and returns whether it is publishable,
the validation findings and summary, the source byte count and SHA-256, and the
four planned output files:

- `pdf_standard` -> `book-standard.pdf`
- `pdf_nd` -> `book-nd.pdf`
- `epub` -> `book.epub`
- `docx` -> `book.docx`

The route must report:

- `job_state: production`
- `rendering_attempted: false`
- `job_created: false`

Dry-run must not create a job directory, queue entry, lock, history record, log
directory, output directory, manifest, retained manuscript copy, worker activity
or export subprocess. Validation may still use the existing sandboxed Pandoc
parser subprocess.

## Dashboard version label

Dashboard pages show a footer label like:

    Book System OS v0.1.x - commit abc1234

Use this to confirm which deployed code is running.

If the commit shows `unknown`, the app could not read the git commit. That is not automatically a service failure, but it should be noted during deploy checks.

## Safe deploy script

Use the safe deploy script on the server:

    scripts/deploy_server.sh

The script should:

- pull latest `main` with `git pull --ff-only`
- show recent commits
- compile key Python modules
- restart `book-system-api.service`
- restart `book-system-worker.service`
- wait for local `/health`
- check public `/health`

## Deploy rule

Do not rely on the public endpoint first.

The safe order is:

1. Pull latest code.
2. Compile Python modules.
3. Restart services.
4. Confirm local health.
5. Confirm public health.
6. Confirm `/api/v1/status`.
7. Confirm the dashboard version label.

## Manual deploy check

After deployment, run or check:

```bash
systemctl is-active book-system-api.service
systemctl is-active book-system-worker.service
curl -i http://127.0.0.1:8080/health
curl -i -4 https://publish.toiletrage.co.uk/health
curl -i https://publish.toiletrage.co.uk/api/v1/status
```

Expected result:

- services are `active`
- local health returns success
- public health returns success
- `/api/v1/status` returns JSON with `ok: true`
- dashboard footer shows the expected app version and commit

## Failed job retry

Failed jobs can be retried from the dashboard job detail page.

Retry is only for jobs with status:

    failed

Retry should:

- preserve the original input Markdown
- preserve metadata
- clear stale work/output/log folders
- remove stale lock file if present
- queue the job again

Do not use Retry for jobs that are queued, running, done, or archived.

## Retry check

Before retrying a failed job, confirm:

- the job failed for a reason that may now be fixed
- the original input still exists
- `metadata.json` still exists
- there is no reason to preserve the old work/output/log folders before retry

After pressing Retry, confirm:

- job returns to queued/running state
- a new log sequence begins
- the job eventually reaches done or failed
- the previous failure is not silently hidden from the operator notes

## Cleanup old test jobs

The dashboard includes a cleanup helper for old test jobs.

The cleanup helper is deliberately conservative.

It should:

- preview old test jobs before archiving
- archive eligible old test jobs only after confirmation
- archive rather than delete folders
- skip queued jobs
- skip running jobs
- affect test jobs only

## Cleanup rule

Always preview before archiving.

Do not archive production jobs with this helper.

Do not archive running or queued jobs.

If the preview list looks wrong, stop and investigate before pressing the archive button.

## Cleanup check

Before using cleanup:

- confirm the threshold in days
- confirm the jobs shown are test jobs
- confirm listed jobs are old enough
- confirm none are queued or running
- confirm archiving is acceptable

After cleanup:

- confirm archived count matches expectation
- confirm archived jobs moved to archived state
- confirm active dashboard filters still show the expected jobs

## Interrupted-job recovery

The worker writes a structured JSON lease to each active job's `.lock` file. The lease records:

- a unique worker ID;
- process ID and hostname;
- operating-system boot identity where available;
- process start identity where available;
- acquisition and heartbeat timestamps.

Heartbeat age is useful evidence, but elapsed time alone never authorises recovery. A recovery is allowed only when the previous ownership is proven invalid or a running job has no lock owner.

Use the operator CLI from `/opt/book-system`.

Preview all recovery-relevant jobs without changing them:

```bash
sudo -u www-data .venv/bin/python scripts/recover_jobs.py preview
```

Preview one job:

```bash
sudo -u www-data .venv/bin/python scripts/recover_jobs.py preview \
  --job-id JOB_ID
```

The important classifications are:

- `active` — the recorded process still owns a running job; recovery is refused;
- `abandoned` — a running job has no owner or its same-host owner is proven dead;
- `stale-lock` — a queued job retains a lock whose owner is proven dead;
- `uncertain` — ownership is remote, malformed or cannot be proved; recovery is refused;
- `owned-lock` — a live process owns a lock while the status is not running; stop and investigate.

To return a proven abandoned job to the queue:

```bash
sudo -u www-data .venv/bin/python scripts/recover_jobs.py recover JOB_ID \
  --to queued \
  --operator "OPERATOR NAME" \
  --reason "Worker was deliberately terminated during controlled recovery"
```

To mark it failed instead:

```bash
sudo -u www-data .venv/bin/python scripts/recover_jobs.py recover JOB_ID \
  --to failed \
  --operator "OPERATOR NAME" \
  --reason "Interrupted export requires inspection before retry"
```

Recovery preserves:

- `input/book.md`;
- `metadata.json`;
- existing work, output and log files;
- all previous `events.jsonl` history.

A successful action adds `recovery-authorised` and `recovered` events and records the operator, reason, previous status and recovery count in `status.json`.

## Recovery operating rule

Always run `preview` immediately before `recover`.

Do not recover a job classified as `active`, `uncertain` or `owned-lock`.

Do not edit or delete `.lock` manually. The CLI rechecks ownership and refuses the action if ownership changes.

After requeueing an abandoned job, confirm:

- the lock was released;
- status changed to `queued` and then `running`;
- recovery events are present;
- original input and metadata remain unchanged;
- the job finishes predictably as `done` or `failed`.

After marking an abandoned job failed, inspect its preserved logs before using the ordinary failed-job Retry control.

## Resource limits

The service reads six positive configuration values from `config/env`:

```text
BOOK_MAX_REQUEST_BYTES=6291456
BOOK_MAX_MANUSCRIPT_BYTES=5242880
BOOK_MAX_ACTIVE_JOBS=20
BOOK_EXPORT_COMMAND_TIMEOUT_SECONDS=300
BOOK_MAX_JOB_BYTES=209715200
BOOK_MAX_TOTAL_STORAGE_BYTES=10737418240
```

The defaults are intended for the current single-server deployment:

- request body: 6 MiB;
- UTF-8 Markdown manuscript: 5 MiB;
- queued plus running jobs: 20;
- each Pandoc command, including XeLaTeX descendants: 300 seconds;
- one complete job directory: 200 MiB;
- retained `books/jobs` storage: 10 GiB.

A new job also reserves 64 KiB for metadata, status and event records before its directory is created. Completed jobs reserve another 64 KiB before final status and manifest publication.

## Resource-limit responses

Submission refusals are controlled JSON responses with a stable `code` field:

- `request-too-large` — HTTP 413 before JSON or form parsing;
- `manuscript-too-large` — HTTP 413 before job creation;
- `queue-capacity-reached` — HTTP 503 while active capacity is full;
- `job-storage-reservation-exceeded` — HTTP 413 when a new job cannot fit its per-job reserve;
- `total-storage-capacity-reached` — HTTP 507 when retained storage cannot admit another job;
- `invalid-resource-limit-config` — HTTP 503 when a configured limit is absent from the valid positive-number range.

Runtime failures remain attached to the job:

- `step: export-timeout` means the process group exceeded `BOOK_EXPORT_COMMAND_TIMEOUT_SECONDS` and was terminated;
- `step: resource-limit` means per-job or total retained storage crossed its configured boundary;
- `limit_code`, `limit` and `actual` are recorded in `status.json` for storage-limit failures;
- `logs/error.log` and `logs/build.log` remain available for diagnosis.

No limit enforcement deletes or truncates an existing job to make room.

## Resource-limit operating rule

Before changing a limit:

1. Record the current value and reason for the change.
2. Measure the largest accepted manuscript and completed job currently retained.
3. Check active queue depth and total `books/jobs` use.
4. Keep the request limit above the manuscript limit to allow JSON or form overhead.
5. Keep the per-job limit above the manuscript limit plus output and record space.
6. Restart both services through the protected deploy procedure.
7. Submit one normal Test job and confirm all four formats still complete.

When a limit refusal occurs:

- do not edit status files or remove locks manually;
- do not delete production jobs merely to force a submission through;
- inspect the response code or job status before deciding whether to raise a limit, archive eligible Test jobs, or investigate abnormal output growth;
- treat repeated export timeouts as a manuscript/toolchain fault until evidence shows the configured timeout is genuinely too low.

## Dashboard operating checks

Use the dashboard to check:

- job status
- job state: test, production, archived
- job detail logs
- retry controls on failed jobs
- cleanup preview for old test jobs
- version label in footer

If the dashboard shows stale or surprising data, check service health and git commit before changing jobs.

## Status endpoint check

Use `/api/v1/status` to check the publish gateway shape.

Important fields:

- `ok`
- `gateway`
- `service`
- `version`
- `routes_enabled`
- `write_enabled`
- `implemented`
- `not_yet_implemented`

If `write_enabled` is true, treat the system as capable of accepting write actions through implemented write routes.

Do not assume planned `/api/v1/publish` execution routes exist until they move
from `not_yet_implemented` to `implemented`.

## Stop rules

Stop and investigate if:

- local health fails after deploy
- public health fails after local health passes
- either service is not active
- dashboard version label does not match expected commit
- `/api/v1/status` returns non-JSON or `ok` is not true
- Retry appears for a non-failed job
- cleanup preview includes production, queued, or running jobs
- recovery preview reports `uncertain` or `owned-lock`
- an active job appears recoverable
- a recovery command does not record operator and reason
- a request or manuscript above its configured boundary creates a job
- queue saturation creates an additional job
- an export timeout leaves Pandoc or XeLaTeX descendants running
- a resource-limit failure deletes or changes an existing production job
- publish dry-run creates retained files, queues work or attempts export rendering
- a deploy script reports API readiness failure

## Current manual gap

This manual records current operator behaviour only.

When new `/api/v1` publish routes are implemented, update this manual with:

- route purpose
- operator-facing risk
- dry-run behaviour if present
- required manual checks
- rollback or retry behaviour
