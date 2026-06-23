# Book System OS operator/admin manual

This note is for running and checking the Book System OS dashboard and publish gateway safely.

It is an operator guide, not a developer design document.

## Current service role

Book System OS is the publishing/job system behind:

    publish.toiletrage.co.uk

The current service supports the original book-system route and the first `/api/v1` publish gateway status route.

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
- `GET /api/v1/status`
- `POST /api/submit`
- `GET /api/jobs/{job_id}`

It may also list planned v1 publish routes that are not implemented yet.

Do not treat `not_yet_implemented` routes as live behaviour.

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
- archive eligible jobs only after confirmation
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

Do not assume planned `/api/v1/publish` routes exist until they move from `not_yet_implemented` to `implemented`.

## Stop rules

Stop and investigate if:

- local health fails after deploy
- public health fails after local health passes
- either service is not active
- dashboard version label does not match expected commit
- `/api/v1/status` returns non-JSON or `ok` is not true
- Retry appears for a non-failed job
- cleanup preview includes production, queued, or running jobs
- a deploy script reports API readiness failure

## Current manual gap

This manual records current operator behaviour only.

When new `/api/v1` publish routes are implemented, update this manual with:

- route purpose
- operator-facing risk
- dry-run behaviour if present
- required manual checks
- rollback or retry behaviour
