# Book System OS backup and restore

## Purpose

This procedure protects the persistent Book System OS job store before later production-hardening work changes runtime behaviour.

It does not back up application source code. Application code is restored from an exact Git tag or commit. It does not copy usable runtime credentials; those must be restored separately from the operator's protected credential source.

## Persistent-data boundary

The backup archive contains:

- `books/jobs/<job-id>/input/` — submitted source manuscripts;
- `books/jobs/<job-id>/metadata.json` — job identity, title and creation time;
- `books/jobs/<job-id>/status.json` — lifecycle and classification state;
- `books/jobs/<job-id>/work/` — intermediate material retained for diagnosis;
- `books/jobs/<job-id>/output/` — the job's PDF, EPUB and DOCX outputs;
- `books/jobs/<job-id>/manifest.json` — declared outputs and the status snapshot written by the pipeline version that built the job;
- `books/jobs/<job-id>/logs/` — per-job build and error logs;
- `books/jobs/<job-id>/events.jsonl` — lifecycle and retry history when the source job has it;
- repository-level `logs/`;
- `config/env.keys` — configuration key names only;
- `backup-metadata.json` — backup format, timestamp and source commit.

The archive deliberately excludes:

- `config/env`, `.env` and all runtime configuration values;
- job `.lock` files, which are transient worker ownership markers;
- repository-level `books/cache/` and `books/outputs/` paths;
- virtual environments and application source;
- any configured secret value detected in copied manuscripts, outputs or logs.

Job-level `output/` directories are persistent and are included. The excluded repository-level `books/outputs/` path is not the same directory.

## Legacy event-history compatibility

Per-job `events.jsonl` history was introduced on 21 June 2026. Jobs created before the cutover may legitimately have no event-history file.

The validator therefore applies these rules:

- an existing `events.jsonl` is always preserved and validated as non-empty UTF-8 JSON Lines;
- a missing file is accepted only when `metadata.json.created_at` is before `2026-06-21T10:33:09Z`;
- a job at or after that cutover fails validation when its event history is missing;
- a legacy absence is preserved as absence during restore; the procedure never fabricates historical events;
- the validation summary reports `legacy_jobs_without_events`.

This compatibility rule does not weaken modern-job validation.

## Legacy successful-manifest compatibility

Before 19 July 2026, the successful pipeline wrote `manifest.json` before changing the authoritative `status.json` record from `running` to `done`. Those completed jobs can therefore have:

- authoritative `status.json` equal to `done`;
- all declared output files present and non-empty;
- a pre-cutover `manifest.json.completed_at`;
- an embedded manifest status snapshot equal to `running` at `pandoc-export` with message `Building PDF/EPUB/DOCX outputs`.

Commit `49fb72d1eb790c835540614cc9b8d4f022028b30` changed the ordering at `2026-07-19T18:56:19Z`, so newer completed manifests must contain an embedded final status of `done`.

The validator accepts only the exact historical pre-cutover shape above. It still verifies every output, rejects unexplained state disagreement, rejects any other incomplete status snapshot and reports accepted records as `legacy_manifests_without_final_status`. Restore preserves the original manifest bytes; it does not rewrite history to resemble the current format.

## Archived Test-state compatibility

Cleanup happens after a job has completed. It may therefore change the authoritative `status.json.state` of an eligible Test job from `test` to `archived` while the immutable manifest continues to record the original Test classification.

### Evidential cleanup transition

The validator accepts a current cleanup mismatch only when all of the following evidence is present:

- authoritative `status.json.status` is still `done`;
- the manifest's embedded state is exactly `test`;
- authoritative state is exactly `archived`;
- `archived_at` and `updated_at` are valid and equal;
- `archive_reason` exactly matches `Archived by cleanup helper; older than <positive integer> days`;
- `events.jsonl` contains a matching `archived` event with the same reason and age threshold;
- the matching event timestamp is no earlier than `archived_at` and no more than one minute later.

Production-to-archived transitions, missing archive events, altered reasons, inconsistent timestamps and arbitrary state changes fail validation.

### Legacy generic-setter transition

The first generic lifecycle setter was introduced by commit `68618f44300ab307789fd46387d150cc38141229` at `2026-06-21T08:08:10Z`. It changed only `state` and `updated_at`; it did not record an archive reason, archive timestamp or archive event. The evidential cleanup helper became available when PR #23 merged at `2026-06-21T13:52:38Z`.

A completed Test job changed to `archived` inside that historical interval may therefore have no cleanup fields. The validator accepts that older shape only when all of these conditions hold:

- metadata creation, manifest completion and authoritative update all fall in chronological order inside the exact historical interval;
- the authoritative update occurs less than five minutes after manifest completion;
- authoritative status is exactly `done`, `complete`, `Build complete`;
- the manifest is the exact accepted pre-cutover successful snapshot: `running`, `pandoc-export`, `Building PDF/EPUB/DOCX outputs`;
- embedded state is exactly `test` and authoritative state is exactly `archived`;
- `archived_at` and `archive_reason` are absent and no `archived` event exists;
- status and manifest contain the same positive `retry_count` and identical `last_retry_at`;
- `events.jsonl` contains a matching retry event at that exact timestamp and count;
- every declared output exists and is non-empty.

The summary reports accepted records as `legacy_manual_archived_state_transitions`. Jobs outside the historical window, jobs without exact retry evidence, production-origin jobs and later unexplained state changes remain invalid.

Both accepted transition types are preservation rules only. Restore keeps the original status, manifest and event bytes without normalising or fabricating history.

## Consistency rule

A trustworthy backup requires a quiescent job store. The utility refuses to continue when any job is `queued` or `running`, when a job `.lock` exists, when required status JSON is malformed, or when a symbolic link exists inside the copied data boundary.

For a production backup, prevent new submissions and worker writes for the short backup window. The simplest controlled procedure is:

1. record the current exact commit and service state;
2. stop the API and worker services;
3. run the backup command;
4. validate the finished archive;
5. restart both services and repeat local/public health checks.

Stopping or restarting production services remains a protected production action and needs the normal deployment authority.

## Create a backup

Choose a destination outside `/opt/book-system`. The destination must not already exist.

```bash
set -euo pipefail

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE="/var/backups/book-system/book-system-${STAMP}.tar.gz"

mkdir -p /var/backups/book-system
chmod 0700 /var/backups/book-system

cd /opt/book-system
bash scripts/backup_job_store.sh \
  --root /opt/book-system \
  "$ARCHIVE"
```

The utility:

1. checks that the store is quiescent;
2. copies the allowed persistent boundary into a private temporary directory;
3. excludes transient locks and configuration values;
4. scans staged files for configured key/password/secret/token values;
5. writes the archive to a partial path in the destination filesystem;
6. validates its structure and records;
7. atomically renames the validated archive to the requested path;
8. prints its path, byte size and SHA-256 digest.

A failed or partial archive is removed and is never reported as successful.

## Validate without restoring

```bash
python3 scripts/validate_backup.py \
  /var/backups/book-system/book-system-YYYYMMDDTHHMMSSZ.tar.gz
```

Validation rejects:

- unsafe, duplicate, linked or device archive members;
- members outside the fixed `book-system-backup/` prefix;
- copied credentials, cache paths or `.lock` files;
- missing job directories or required records;
- malformed metadata, status, manifest or present event JSON;
- modern jobs without required event history;
- legacy jobs without a trustworthy pre-cutover creation timestamp;
- job identifiers that disagree with `metadata.json`;
- completed jobs without a manifest and non-empty declared outputs;
- modern completed manifests without embedded final status `done`;
- pre-cutover manifests that do not match the exact historical successful pipeline snapshot;
- unexplained manifest/status state disagreement;
- current archived Test jobs without exact cleanup fields and a matching archive event;
- alleged legacy manual transitions outside the exact historical window or without exact retry evidence;
- any production-to-archived manifest/status mismatch.

## Clean-system restore rehearsal

Restore only into an absent or empty isolated destination. The validator refuses to overwrite any existing content.

```bash
set -euo pipefail

RESTORE_ROOT="/srv/book-system-restore-rehearsal"
rm -rf -- "$RESTORE_ROOT"   # rehearsal cleanup requires explicit operator authority

python3 scripts/validate_backup.py \
  /var/backups/book-system/book-system-YYYYMMDDTHHMMSSZ.tar.gz \
  --restore-root "$RESTORE_ROOT"
```

The restored layout is:

```text
$RESTORE_ROOT/
├── backup-metadata.json
├── books/jobs/<original-job-id>/...
├── config/env.keys
└── logs/...
```

The restore process writes files with exclusive creation, verifies each restored SHA-256 digest, and cleans only its newly created partial destination if restoration fails.

Verify representative test and production jobs:

```bash
find "$RESTORE_ROOT/books/jobs" -maxdepth 2 -type f | sort
python3 -m json.tool "$RESTORE_ROOT/books/jobs/<job-id>/metadata.json" >/dev/null
python3 -m json.tool "$RESTORE_ROOT/books/jobs/<job-id>/status.json" >/dev/null
python3 -m json.tool "$RESTORE_ROOT/books/jobs/<job-id>/manifest.json" >/dev/null
```

For jobs with event history, validate every populated line as JSON. For an accepted pre-cutover legacy job, confirm that `events.jsonl` remains absent in both the source and restored copies.

For an accepted pre-cutover successful manifest, confirm that the source and restored `manifest.json` hashes are identical and that the authoritative restored `status.json` remains `done`.

For an archived Test job, confirm that source and restored `status.json`, `manifest.json` and `events.jsonl` hashes are identical. The manifest should still record `test`; authoritative status should still record `archived`. Current cleanup records retain their cleanup evidence. Accepted legacy generic-setter records retain the deliberate absence of archive evidence and their exact retry history.

Compare selected source and restored records without modifying either copy:

```bash
sha256sum \
  /opt/book-system/books/jobs/<job-id>/input/book.md \
  "$RESTORE_ROOT/books/jobs/<job-id>/input/book.md"
```

## Recover onto a replacement installation

1. Install the application from the exact accepted Git tag or commit into a clean application directory.
2. Keep the new services stopped.
3. Validate and restore the archive into an empty staging root.
4. Recreate `config/env` manually from the protected credential source, using `config/env.keys` only as a shape checklist.
5. Confirm the intended destination job store is empty. Do not overwrite an existing store.
6. Copy the restored `books/jobs/` and repository `logs/` into the new installation.
7. Set ownership for the deployed service account and restrictive permissions:

   ```bash
   chown -R www-data:www-data /opt/book-system/books/jobs /opt/book-system/logs
   find /opt/book-system/books/jobs /opt/book-system/logs -type d -exec chmod 0750 {} +
   find /opt/book-system/books/jobs /opt/book-system/logs -type f -exec chmod 0640 {} +
   chmod 0600 /opt/book-system/config/env
   ```

8. Start the API and worker.
9. Check local and public health.
10. Open representative completed jobs and confirm downloads, manifest state, logs and event history where present. Confirm accepted legacy and archived records remain unchanged rather than being fabricated or normalised.

Moving restored data into a production path is a protected production-data action. It must not be automated over an existing store.

## Retention and off-host storage

For the current single-server service, use this baseline unless a later approved policy replaces it:

- retain seven daily backups;
- retain four weekly backups;
- retain six monthly backups;
- keep at least one encrypted copy off the application server;
- verify a stored SHA-256 digest after transfer;
- run a clean restore rehearsal at least quarterly and before risky storage changes.

This repository does not provision, purchase or select a remote storage provider. Access control, encryption keys and storage spending remain owner decisions.

## Operational evidence to record

For each controlled rehearsal, record without credentials:

- UTC timestamp;
- exact deployed commit and accepted release tag;
- archive filename, size and SHA-256 digest;
- backup and validation duration;
- number and identifiers of representative test and production jobs;
- count of accepted `legacy_jobs_without_events`;
- count of accepted `legacy_manifests_without_final_status`;
- count of accepted `legacy_manual_archived_state_transitions`;
- restore destination;
- validation output;
- source/restored hash comparison results;
- service health after the procedure;
- authorised cleanup result for the isolated rehearsal copy.

Do not include `config/env`, passwords, API keys, authentication headers or manuscript content in the evidence record.
