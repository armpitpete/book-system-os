# Protected production rehearsal runner

## Purpose

`scripts/run_protected_rehearsal.sh` provides one reusable detached launcher for production acceptance and rollback scripts.

It does not authorise a rehearsal. The exact script, commit, target, evidence job and arguments remain protected owner decisions.

## Guarantees

The runner:

- uses `set -Eeuo pipefail` and `umask 077`;
- accepts only a regular non-symlink script inside the repository `scripts/` directory;
- requires new absolute launch-log and PID-file paths outside the repository;
- launches through `nohup` with standard input disconnected;
- writes the detached runner PID with mode `0600`;
- records SHA-256 digests for itself and the protected script;
- forwards `HUP`, `INT` and `TERM` as termination to the protected child;
- waits for the protected script and preserves its exit status;
- writes a private atomic `.result` sidecar with `PASS` or `FAIL`, exit code and signal;
- never selects a Git commit, rollback target or evidence job;
- never deletes files, cleans a repository or retries a failed operation.

The protected script remains responsible for its own exact-head checks, service recovery and gate-specific evidence.

## H-09 launch shape

H-09 uses the committed gate-specific runner:

```text
scripts/h09_live_rehearsal.sh
```

That script performs the service-account audit, verifies the installed worker restart guard, proves stopped-worker readiness failure, restores the worker, invokes `scripts/rollback_server.sh`, and verifies the exact rollback target. It deliberately stops before any forward redeployment.

Review every placeholder immediately before launch:

```bash
set -Eeuo pipefail

CURRENT="<exact merged H-09 candidate commit>"
TARGET="1a6f8d65dc066828749b6b5e8bb25de80e92839f"
JOB_ID="<existing completed production job>"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE="/opt/book-system-rehearsals/h09-live-${STAMP}"
LAUNCH_LOG="/root/book-system-h09-${STAMP}-launch.log"
PID_FILE="/root/book-system-h09-${STAMP}.pid"

cd /opt/book-system
sudo bash scripts/run_protected_rehearsal.sh \
  --script scripts/h09_live_rehearsal.sh \
  --launch-log "$LAUNCH_LOG" \
  --pid-file "$PID_FILE" \
  -- \
  --expected-current "$CURRENT" \
  --target "$TARGET" \
  --job-id "$JOB_ID" \
  --evidence-dir "$EVIDENCE" \
  --confirm exact-h09-rehearsal
```

The initial command returns only after the detached runner is confirmed alive. It prints:

```text
rehearsal-runner-pid=<pid>
rehearsal-launch-log=<path>
rehearsal-pid-file=<path>
rehearsal-result-file=<path>.result
```

## Result review

Inspect the PID, launch log, runner result and gate-specific result:

```bash
PID="$(cat "$PID_FILE")"
kill -0 "$PID" 2>/dev/null && echo running || echo finished
tail -n 200 "$LAUNCH_LOG"
cat "${LAUNCH_LOG}.result"
cat "$EVIDENCE/result.json"
```

A runner `PASS` means only that the protected script exited successfully. H-09 still requires review of the private rollback evidence, independent health/readiness checks, the separate exact-commit return deployment and final tag procedure in `docs/DEPLOYMENT_ROLLBACK.md`.

## Failure rule

A missing result file, non-zero exit, recorded signal or incomplete rollback evidence is a failed rehearsal. Preserve the launch log, PID file, result sidecar and gate-specific evidence. Do not rerun with a different target, repair production data or pull forward without a new protected instruction.
