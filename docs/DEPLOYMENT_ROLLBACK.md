# Book System OS deployment rollback

## Purpose

This procedure governs H-09 under issues #31 and #42. It returns the tracked application checkout from one exact deployed commit to an earlier exact accepted commit while preserving the production job store, operational logs and `config/env`.

It does not authorise automatic rollback. Each production rehearsal or real rollback requires an explicit current commit, target commit, completed evidence job and operator-authorised evidence location.

## Protected boundaries

The application checkout is `/opt/book-system`.

The rollback may change tracked repository files only. It must not overwrite, remove or reconstruct:

- `books/jobs/`;
- repository-level `logs/`;
- `config/env`;
- `/etc/systemd/system/book-system-api.service`;
- `/etc/systemd/system/book-system-worker.service`.

The job store and logs are ignored runtime data. `config/env` is an untracked protected secret file. The script refuses to continue if Git reports persistent runtime files as tracked, the repository has tracked modifications, the exact target is not an ancestor of the exact current commit, or installed service-unit boundaries differ from the accepted `/opt/book-system` deployment.

## Rollback utility

Use:

```text
scripts/rollback_server.sh
```

The script requires:

- root authority;
- a full forty-character expected current commit;
- a different full forty-character target commit;
- an exact ancestor relationship from target to current;
- a completed retained job ID;
- a new private evidence directory outside the repository;
- the literal confirmation `exact-rollback`.

It does not select a target automatically and does not use a moving branch name as rollback authority.

## What the script proves

Before changing the checkout, the script:

1. fetches refs without changing the working tree;
2. verifies the exact current and target commits;
3. verifies the tracked tree is clean;
4. confirms required application and service-unit source files exist at the target;
5. confirms persistent runtime paths contain no tracked files;
6. records installed systemd unit boundaries without credentials;
7. stops both services;
8. refuses a job store containing queued/running jobs or lock files;
9. hashes `config/env` without copying its contents;
10. snapshots every non-lock job-store file;
11. snapshots every operational log file;
12. creates a detailed integrity record for one completed job.

It then uses:

```bash
git reset --hard <exact-target-commit>
```

This rewinds the checked-out branch to the authorised commit. It does not run `git clean`, delete untracked files, restore a backup over the live store or copy service units.

While services remain stopped, it proves that:

- `config/env` has the same SHA-256 digest;
- the complete non-lock job-store snapshot is byte-for-byte identical;
- operational log files are byte-for-byte identical;
- the target checkout compiles;
- the target checkout is clean and exactly at the requested commit.

After service recovery, it proves:

- API and worker are active;
- local and public health pass;
- local and public readiness pass;
- local and public status endpoints pass;
- the selected completed job has the same files, sizes, modes and SHA-256 digests;
- authenticated job detail is readable;
- every output declared by the selected manifest downloads successfully;
- every downloaded byte stream matches the retained output digest;
- pre-existing operational logs were not removed, truncated or replaced;
- `config/env` remains unchanged.

If any check fails, the script records failure evidence and attempts only to restart the two services. It does not improvise another Git target, delete data, overwrite configuration or silently return to the candidate commit.

## Controlled H-09 rehearsal

The live rehearsal must use the final merged H-09 commit as the exact candidate and the previously accepted H-08 production commit as the exact rollback target.

A safe unsuitable-candidate simulation is:

1. deploy the exact H-09 merge commit through the protected deployment procedure;
2. confirm ordinary health and readiness first;
3. select one existing completed production job whose source, metadata, outputs, manifest, logs and history are present;
4. record the candidate commit, target commit, selected job ID and `config/env` digest;
5. stop the worker service deliberately;
6. confirm `/health` still reports API liveness while `/ready` reports not ready;
7. do not submit, retry, archive, recover or clean any job;
8. run the exact rollback command below;
9. review all generated evidence before declaring the rehearsal passed.

Stopping the worker is a controlled simulation of an unsuitable deployment state. It does not alter application code or persistent job records. The rollback target remains an exact earlier accepted commit.

Example command shape:

```bash
set -euo pipefail

CURRENT="<exact merged H-09 candidate commit>"
TARGET="1a6f8d65dc066828749b6b5e8bb25de80e92839f"
JOB_ID="<existing completed production job>"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE="/opt/book-system-rehearsals/h09-rollback-${STAMP}"

cd /opt/book-system
sudo bash scripts/rollback_server.sh \
  --expected-current "$CURRENT" \
  --target "$TARGET" \
  --job-id "$JOB_ID" \
  --evidence-dir "$EVIDENCE" \
  --confirm exact-rollback
```

The exact current commit, target and job ID must be reviewed immediately before execution. Do not paste credential values into the command or evidence record.

## Required successful ending

The script must finish with:

```text
===== H-09 ROLLBACK RESULT =====
rollback-result=PASS
previous-commit=<exact candidate>
restored-commit=<exact accepted target>
job-id=<completed evidence job>
duration-seconds=<measured value>
evidence=<private evidence directory>
```

Afterward, independently verify:

```bash
git -C /opt/book-system rev-parse HEAD
systemctl is-active book-system-api.service
systemctl is-active book-system-worker.service
curl -fsS http://127.0.0.1:8080/health
curl -fsS http://127.0.0.1:8080/ready
curl -fsS -4 https://publish.toiletrage.co.uk/health
curl -fsS -4 https://publish.toiletrage.co.uk/ready
```

The local branch will be behind `origin/main` after a successful rollback. That is expected evidence, not a reason to pull forward automatically. Returning to a newer release is a separate protected deployment action.

## Evidence files

The private evidence directory contains no credential values or manuscript text copied separately. It records:

- rollback log and final result;
- before/after Git state;
- installed service-unit text;
- environment-file digests only;
- complete job-store hash inventories before and after the tracked reset;
- operational-log inventories;
- completed-job before/after integrity snapshots;
- authenticated download names, sizes and SHA-256 digests;
- local/public health, readiness and status responses;
- final systemd state.

The job snapshots necessarily include relative filenames, sizes, modes and digests. They do not include file contents.

## Stop rules

Stop and preserve evidence if:

- either exact commit differs from the reviewed authority;
- the target is not an ancestor of the candidate;
- the tracked tree is dirty;
- persistent paths appear as tracked files;
- the installed units do not use `/opt/book-system`, `config/env`, `www-data`, `books` and `logs` as expected;
- any job is queued or running;
- any lock exists;
- the selected evidence job is not completed;
- any declared output is absent or empty;
- `config/env` changes;
- the job-store inventory changes while services are stopped;
- a pre-existing operational log disappears, shrinks or changes before its previous end;
- local health or readiness fails after rollback;
- public health or readiness fails after local recovery;
- authenticated job detail or any output download fails;
- the final checkout is not the exact target commit.

Do not repair a failed rehearsal by deleting jobs, editing status files, changing credentials, selecting another target or pulling `main`. Record the failure and return for review.

## Exclusions

This procedure does not add automatic rollback, release deletion, backup restoration over an existing store, infrastructure migration, v0.2 routes, printer-specific production or Semantic Architect behaviour.
