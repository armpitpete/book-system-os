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

## Rehearsal runner standard

Every protected production rehearsal or acceptance script must use the same operational controls unless a stricter gate-specific control replaces one of them:

- `set -Eeuo pipefail` and `umask 077`;
- an exact reviewed commit guard before mutation;
- an exact protected target where rollback is possible;
- explicit `EXIT`, `HUP`, `INT` and `TERM` handling;
- a private evidence directory with mode `0700`;
- evidence files written with private permissions;
- detached execution through `nohup` or an equivalent operator-controlled session;
- a separate launch log and a stable latest-evidence pointer where practical;
- `pipefail` whenever output is passed through `tee` so a failing command cannot appear green;
- controlled fixtures owned by the service account that must read them;
- no credential values, manuscript bodies or private tokens copied into evidence;
- a required terminal `PASS` or `FAIL` result record;
- no improvised cleanup, target selection or forward deployment after failure.

H-09 uses the committed `scripts/h09_live_rehearsal.sh` orchestration through `scripts/run_protected_rehearsal.sh`. The live runner proves the stopped-worker readiness boundary before invoking the lower-level rollback utility. Do not replace that reviewed path with a pasted terminal programme or a direct production call to `rollback_server.sh`.

## Rollback utility

The lower-level exact rollback utility is:

```text
scripts/rollback_server.sh
```

It is invoked by the committed H-09 live runner after the worker-readiness proof. The utility requires:

- root authority;
- a full forty-character expected current commit;
- a different full forty-character target commit;
- an exact ancestor relationship from target to current;
- a completed retained job ID;
- a new private evidence directory outside the repository;
- the literal confirmation `exact-rollback`.

It does not select a target automatically and does not use a moving branch name as rollback authority.

## What the rollback utility proves

Before changing the checkout, the utility:

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

If any check fails, the utility records failure evidence and attempts only to restart the two services. It does not improvise another Git target, delete data, overwrite configuration or silently return to the candidate commit.

## Controlled H-09 rehearsal

The live rehearsal must use the final merged H-09 commit as the exact candidate and the previously accepted H-08 production commit as the exact rollback target.

The committed live runner performs this sequence:

1. verifies the exact candidate, target, clean checkout and protected `config/env` boundary;
2. audits every retained job path as the `www-data` service account;
3. verifies the installed worker restart limit and independent `OnFailure` alarm;
4. proves the candidate worker holds one PID without increasing `NRestarts`;
5. confirms ordinary local and public health and readiness;
6. stops the worker deliberately;
7. confirms `/health` still reports API liveness while local and public `/ready` return HTTP 503 without exposing paths or job identifiers;
8. restores and rechecks the worker before rollback;
9. invokes the guarded exact rollback utility;
10. proves the H-08 target, service-account access, worker stability, health, readiness, configuration and completed-job evidence remain intact;
11. stops before any forward deployment.

Stopping the worker is a controlled simulation of an unsuitable deployment state. It does not alter application code or persistent job records. Do not submit, retry, archive, recover or clean any job during the rehearsal.

Review every placeholder immediately before launch:

```bash
set -Eeuo pipefail

CURRENT="<exact merged H-09 candidate commit>"
TARGET="1a6f8d65dc066828749b6b5e8bb25de80e92839f"
JOB_ID="<existing completed production job>"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE="/opt/book-system-rehearsals/h09-rollback-${STAMP}"
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

The launcher confirms that the detached runner is alive and prints the PID, launch-log, PID-file and result-sidecar paths. Do not paste credential values into the command or evidence record.

## Required successful ending

The outer runner result must say:

```text
rehearsal-runner-result=PASS
exit-code=0
signal=none
```

The protected H-09 script must also finish with:

```text
===== H-09 LIVE REHEARSAL RESULT =====
h09-live-rehearsal=PASS
candidate-commit=<exact H-09 candidate>
restored-commit=<exact H-08 target>
job-id=<completed evidence job>
evidence=<private evidence directory>
next-protected-action=review evidence, then separately redeploy exact candidate
```

The nested rollback evidence must contain its own `rollback-result=PASS`. A green outer runner without complete H-09 and rollback evidence is not acceptance.

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

The local branch will be behind `origin/main` after a successful rollback. That is expected evidence, not a reason to pull forward automatically.

## Separate return to the current accepted release

Rollback proof and release restoration are separate protected actions. H-09 is not complete while production remains on the older H-08 target.

After the rollback evidence has been reviewed and accepted:

1. re-verify that `origin/main` still resolves to the exact merged H-09 commit;
2. deploy that exact H-09 merge commit with `scripts/deploy_server.sh --expected-commit <exact-H-09-commit>`;
3. do not use a moving branch name as the deployment authority;
4. confirm both services are active and the worker remains stable for the bounded window;
5. confirm local and public health, readiness and status;
6. recheck the same completed evidence job and every manifest-declared download;
7. confirm `config/env`, the job-store inventory and retained outputs remain unchanged;
8. record the final deployed commit and evidence on issues #42 and #31.

A successful rollback rehearsal followed by a failed return deployment must stop with evidence. Do not close H-09 or the hardening programme in that state.

## Final immutable hardening tag

Only after the final H-09 commit is redeployed and accepted may the operator create the annotated release tag:

```text
v0.1.8-hardened
```

The tag must resolve to the exact final accepted H-09 commit. It must never be created on the temporarily restored H-08 commit.

Before creation, check both local and remote state:

```bash
FINAL_COMMIT="<exact accepted H-09 commit>"
TAG="v0.1.8-hardened"

git -C /opt/book-system fetch --tags origin

git -C /opt/book-system show-ref --verify --quiet "refs/tags/$TAG" && {
  echo "tag already exists locally"
  exit 1
}

git ls-remote --exit-code --tags origin "refs/tags/$TAG" >/dev/null 2>&1 && {
  echo "tag already exists remotely"
  exit 1
}

[[ "$(git -C /opt/book-system rev-parse HEAD)" == "$FINAL_COMMIT" ]]
git -C /opt/book-system tag -a "$TAG" "$FINAL_COMMIT" \
  -m "Book System OS v0.1.8 production hardening accepted"
[[ "$(git -C /opt/book-system rev-list -n 1 "$TAG")" == "$FINAL_COMMIT" ]]
git -C /opt/book-system push origin "refs/tags/$TAG"
```

Tag creation and push are protected actions. If the tag already exists, stop and inspect it; never move, delete or replace it as part of the rehearsal. Record the tag name and resolved commit in the completion evidence.

## Evidence files

The private evidence directory contains no credential values or manuscript text copied separately. It records:

- outer runner launch log, PID and atomic result sidecar;
- H-09 live-rehearsal log and atomic result;
- copied rehearsal scripts and their SHA-256 digests;
- failure stage and terminating signal when applicable;
- rollback log and nested final result;
- before/after Git state;
- installed service-unit text and effective restart controls;
- environment-file digests only;
- complete job-store hash inventories before and after the tracked reset;
- service-account access reports before and after;
- operational-log inventories;
- completed-job before/after integrity snapshots;
- authenticated download names, sizes and SHA-256 digests;
- stopped-worker and recovered local/public health and readiness responses;
- final systemd state.

The job snapshots necessarily include relative filenames, sizes, modes and digests. They do not include file contents.

## Stop rules

Stop and preserve evidence if:

- either exact commit differs from the reviewed authority;
- the target is not an ancestor of the candidate;
- the tracked tree is dirty;
- persistent paths appear as tracked files;
- the installed units do not use `/opt/book-system`, `config/env`, `www-data`, `books` and `logs` as expected;
- the worker restart limit or `OnFailure` alarm differs from the reviewed units;
- the worker PID changes or `NRestarts` increases during a stability window;
- the service-account job-store audit fails;
- any job is queued or running;
- any lock exists;
- the selected evidence job is not completed;
- any declared output is absent or empty;
- `config/env` changes;
- the job-store inventory changes while services are stopped;
- a pre-existing operational log disappears, shrinks or changes before its previous end;
- stopped-worker readiness does not fail with HTTP 503 or leaks a private identifier;
- local health or readiness fails after rollback;
- public health or readiness fails after local recovery;
- authenticated job detail or any output download fails;
- the final checkout is not the exact target commit;
- the separate return deployment does not reach the exact H-09 commit;
- the final tag exists already or resolves to another commit.

Do not repair a failed rehearsal by deleting jobs, editing status files, changing credentials, selecting another target or pulling `main`. Record the failure and return for review.

## Exclusions

This procedure does not add automatic rollback, release deletion, backup restoration over an existing store, infrastructure migration, v0.2 routes, printer-specific production or Semantic Architect behaviour.
