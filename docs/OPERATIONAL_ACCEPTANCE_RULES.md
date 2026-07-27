# Book System OS operational acceptance rules

## Purpose

These rules apply to protected deployment, rollback, recovery and production-acceptance work. They reduce paste errors, service-account permission failures, false issue closure and invisible restart loops without expanding the product boundary.

## Committed runners, not terminal programmes

A production acceptance that requires more than a short command sequence must be committed, reviewed and tested in the repository. The operator command should identify an exact commit and invoke one reviewed script.

The script must:

- use `set -Eeuo pipefail` and a private umask;
- guard the exact current and target commits;
- write private evidence outside the repository;
- record an unambiguous PASS or FAIL result;
- trap interruption signals where service state could be left incomplete;
- avoid credentials, manuscript bodies and private tokens in evidence;
- refuse improvised targets, cleanup or forward deployment.

## Operational issue closure

A pull request must use `Relates to #<issue>` whenever merge is followed by deployment, live rehearsal, physical inspection or other acceptance evidence.

Closing keywords such as `Closes`, `Fixes` and `Resolves` are allowed only when merge itself satisfies every criterion. Operational issues are closed explicitly after the final evidence is recorded.

## Service-account fixture boundary

Any fixture or retained job that the production service must inspect is created as `www-data` or passes:

```text
scripts/audit_job_service_access.py
```

The audit checks real service-user access rather than root access. It reports aggregate failure categories by default and reveals relative paths only when `--include-paths` is deliberately used in a private evidence directory.

Deployment and rollback acceptance must stop before service restart when the audit fails.

## Worker restart-loop boundary

The worker systemd unit has two independent controls in addition to application readiness:

- no more than three failed starts within five minutes;
- an `OnFailure` journal alarm tagged `book-system-worker-alarm`.

The start limit prevents an unbounded restart storm. The alarm provides a process-level signal that does not depend on the application heartbeat or readiness implementation.

Acceptance must verify the effective installed `StartLimitIntervalUSec`, `StartLimitBurst` and `OnFailure` properties, then prove the worker holds one PID without increasing `NRestarts` during a bounded stability window.

## Isolated rehearsal root

Non-final fixtures should use an isolated production-like root created by:

```text
scripts/prepare_rehearsal_root.py
```

The helper creates service-owned `books/jobs` and `logs` directories outside `/opt/book-system`. It copies no credentials and no production jobs. Tests may point `BOOK_SYSTEM_ROOT` at that root.

An isolated rehearsal does not replace final production acceptance. It catches ownership, traversal and mutation defects before the protected live gate.

## H-09 application

H-09 uses a committed live-rehearsal runner. It verifies exact commits, job-store access, worker restart controls, stopped-worker readiness, rollback integrity and post-rollback stability. Returning production to the final H-09 commit remains a separate protected deployment after rollback evidence is reviewed.
