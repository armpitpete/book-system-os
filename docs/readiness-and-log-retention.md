# Readiness, worker heartbeat and log retention

This document defines the H-05 operational checks for the current single-server Book System OS deployment.

It does not add a public status product, external monitoring service or v0.2 publishing route.

## Liveness and readiness are different

API-process liveness:

```text
GET /health
```

A successful response means the API process can answer HTTP:

```json
{"status":"ok"}
```

Liveness does not claim that publishing can currently proceed.

Operational readiness:

```text
GET /ready
```

Readiness checks the publishing dependencies and returns:

- HTTP 200 with `status: ready` when every check passes;
- HTTP 503 with `status: degraded` when suspicious old queued work produces a warning;
- HTTP 503 with `status: not-ready` when a required dependency or running-work check fails.

The readiness response is deliberately operator-safe. It reports counts, ages, thresholds and dependency states. It does not expose credentials, manuscript text, worker identity, job IDs or filesystem paths.

## Readiness checks

The endpoint checks:

- the job-storage directory exists and is writable by the API service;
- the service-level worker heartbeat exists, is valid and is fresh;
- `pandoc` is available and executable;
- `xelatex` is available and executable;
- free space on the job-storage filesystem is at or above the configured minimum;
- queued and running jobs are not older than their configured operational thresholds;
- readiness configuration contains valid positive values.

The checks are bounded, non-mutating and do not submit or alter jobs.

## Worker service heartbeat

The worker atomically replaces:

```text
/opt/book-system/logs/worker-heartbeat.json
```

The record contains only:

- format version;
- an internal worker identifier;
- worker start time;
- latest heartbeat time;
- worker state: `starting`, `idle` or `running`.

The worker writes immediately at startup and state changes, then refreshes the record in a background thread while idle and during long exports.

The readiness endpoint does not return the internal worker identifier.

A stale heartbeat proves that the worker service is not making observable progress. It does not by itself authorise interrupted-job recovery. Recovery remains governed by the separate H-02 ownership and lock checks.

## Configuration

The default production values are:

```text
BOOK_WORKER_SERVICE_HEARTBEAT_SECONDS=2
BOOK_READINESS_WORKER_MAX_AGE_SECONDS=15
BOOK_READINESS_MIN_FREE_BYTES=536870912
BOOK_READINESS_QUEUED_WARN_SECONDS=900
BOOK_READINESS_RUNNING_FAIL_SECONDS=900
```

Meaning:

- worker heartbeat refresh: every 2 seconds;
- maximum accepted heartbeat age: 15 seconds;
- minimum free job-storage space: 512 MiB;
- queued-work warning threshold: 15 minutes;
- running-work failure threshold: 15 minutes.

`BOOK_READINESS_WORKER_MAX_AGE_SECONDS` must be greater than `BOOK_WORKER_SERVICE_HEARTBEAT_SECONDS`.

Invalid readiness configuration fails closed at `/ready` but does not change `/health`.

## Readiness response shape

A normal response contains:

```json
{
  "ready": true,
  "status": "ready",
  "checked_at": "2026-07-25T20:00:00+00:00",
  "checks": {
    "configuration": {"status": "pass"},
    "job_storage": {"status": "pass"},
    "worker": {"status": "pass"},
    "pandoc": {"status": "pass"},
    "xelatex": {"status": "pass"},
    "disk_space": {"status": "pass"},
    "active_work": {"status": "pass"}
  }
}
```

Check status values are:

- `pass`;
- `warning`;
- `fail`.

Old queued work produces `warning` and makes the endpoint degraded.

Old running work, invalid active-work timestamps, stale worker heartbeat, missing tools, unwritable storage or low disk space produce `fail`.

## Operator checks

From the production server:

```bash
curl -i http://127.0.0.1:8080/health
curl -i http://127.0.0.1:8080/ready
curl -i -4 https://publish.toiletrage.co.uk/health
curl -i -4 https://publish.toiletrage.co.uk/ready
```

Also confirm:

```bash
systemctl is-active book-system-api.service
systemctl is-active book-system-worker.service
```

Use the readiness body to identify the failed check before changing configuration or job state.

## Inactive worker evidence

A controlled worker-stop check is:

1. Confirm no job is queued or running.
2. Stop `book-system-worker.service`.
3. Wait longer than `BOOK_READINESS_WORKER_MAX_AGE_SECONDS`.
4. Confirm `/health` still returns HTTP 200.
5. Confirm `/ready` returns HTTP 503 with the worker check reporting a stale heartbeat.
6. Restart the worker.
7. Confirm `/ready` returns HTTP 200 again.

Do not perform this check while a real job is active.

## Toolchain evidence

A missing-tool check must use an isolated process or controlled PATH rather than renaming or deleting the production binaries.

The expected result is:

- `/health` remains HTTP 200;
- `/ready` returns HTTP 503;
- the missing `pandoc` or `xelatex` check reports `fail`;
- no job is created or changed.

## Low-space evidence

A low-space check must inject or isolate the reported free-space value. Do not fill the production disk deliberately.

The expected result is HTTP 503 with:

```text
checks.disk_space.status=fail
```

Normal production acceptance must also confirm the real filesystem passes the configured minimum.

## Suspicious active work

The endpoint reads active job status records without modifying them.

It reports:

- count of old queued jobs;
- count of old running jobs;
- count of active records with invalid timestamps;
- oldest queued and running ages;
- configured thresholds.

An old queued job means publishing may have stopped even if the worker heartbeat is fresh. Investigate locks, worker logs and queue state.

An old running job is a failure. Use the H-02 recovery preview before taking any action. Never delete `.lock` or edit `status.json` manually.

## Deployment behaviour

The protected deploy script:

1. checks API liveness;
2. waits for local readiness;
3. prints local liveness, readiness and status;
4. checks public liveness, readiness and status;
5. stops before `DEPLOY COMPLETE` when readiness remains unavailable.

A readiness failure after deployment is not hidden by a passing liveness response.

## Service-log rotation and retention

API and worker stdout/stderr are stored in the systemd journal.

Inspect current use:

```bash
journalctl --disk-usage
journalctl -u book-system-api.service --since "24 hours ago"
journalctl -u book-system-worker.service --since "24 hours ago"
```

The host should have an explicit journald retention policy. A suitable single-server starting point is:

```ini
# /etc/systemd/journald.conf.d/book-system-retention.conf
[Journal]
SystemMaxUse=250M
RuntimeMaxUse=100M
MaxRetentionSec=14day
Compress=yes
```

This is a host-wide policy and is not installed automatically by the repository deploy script. Review it against other services before applying it.

After an authorised change:

```bash
systemctl restart systemd-journald
journalctl --disk-usage
```

Review journal disk use and recent API/worker errors at least monthly and after every failed production acceptance.

## Job-log retention

Per-job files such as:

```text
books/jobs/JOB_ID/logs/build.log
books/jobs/JOB_ID/logs/error.log
```

are evidence belonging to that job. They are not rotated independently because truncating them would damage job history.

Their retention is bounded by:

- the H-04 per-job storage limit;
- the H-04 total retained-storage limit;
- conservative Test-job archiving;
- backup and operator-approved lifecycle decisions.

Production job logs are never deleted automatically to make room.

The service heartbeat is a single atomically replaced JSON record rather than an append-only log, so it requires no rotation.

## Stop rules

Stop and investigate when:

- `/health` fails;
- `/health` passes but `/ready` returns HTTP 503;
- the worker heartbeat is missing, invalid or stale;
- Pandoc or XeLaTeX is unavailable;
- free space is below the configured minimum;
- queued work is old enough to produce a warning;
- running work is old enough to fail readiness;
- readiness exposes a path, credential, manuscript fragment, worker identifier or job ID;
- deployment reaches liveness but cannot reach readiness;
- journal retention is undefined or journal use grows without review.
