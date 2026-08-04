# Protected Corpus Runtime Release

## Purpose

This procedure deploys and live-accepts the remaining Book System OS corpus runtime corrections under one exact commit and one rollback boundary:

- missing local Markdown images fail before export;
- Greek and Cyrillic text remains visible and Unicode-extractable in both PDF templates;
- the public validation API exposes unresolved internal-link warnings and occurrence counts.

Test-only corpus additions require no separate production action.

## Authority boundary

The release is permitted only after:

1. the release-tooling pull request is merged;
2. its exact merge commit is known;
3. production still equals the accepted expected-before commit;
4. `origin/main` equals the exact target commit;
5. the repository and detached candidate worktree are clean;
6. the operator enters the exact typed confirmation.

The launcher does not auto-rollback. A failure preserves its evidence and the timestamped backup created by the existing V2-01 deployment path for deliberate recovery.

## One protected launcher

The target commit contains:

```text
scripts/production_corpus_runtime_release.sh
```

Run that exact file from a clean detached worktree at the target commit. Do not copy its contents into an ad-hoc script.

Example preparation, replacing both SHAs with the authorised values:

```bash
git -C /opt/book-system fetch --prune origin
sudo rm -rf /run/book-system-corpus-release
sudo git -C /opt/book-system worktree add --detach /run/book-system-corpus-release <TARGET_COMMIT>
```

The `rm -rf` line is not part of the protected launcher and must not be used when the path contains evidence or an existing worktree. Prefer a new timestamped path instead of deleting an old one.

Run the release:

```bash
sudo bash /run/book-system-corpus-release/scripts/production_corpus_runtime_release.sh \
  --repo-root /opt/book-system \
  --expected-before <EXPECTED_PRODUCTION_COMMIT> \
  --target-commit <TARGET_COMMIT> \
  --confirm "DEPLOY <TARGET_COMMIT>"
```

A custom new evidence directory may be supplied with:

```text
--evidence-root /var/log/book-system/<new-private-directory>
```

The directory must not already exist.

## What the launcher proves before mutation

- root authority;
- full lowercase 40-character SHAs;
- expected-before and target are different;
- exact typed confirmation;
- launcher bytes match the file committed at the target SHA;
- candidate worktree equals the target SHA and is clean;
- production is on clean `main` at the expected-before SHA;
- `origin/main` equals the target SHA;
- target is a descendant of expected-before;
- protected environment file exists;
- private evidence directory can be created with mode `0700`.

## Deployment path

The launcher reuses:

```text
scripts/production_v2_01_acceptance.sh
```

That existing protected path stages the exact commit, installs/verifies the pinned runtime, executes `deploy_server.sh`, restarts and checks services, and runs the established baseline four-format acceptance.

The new launcher does not create a competing deployment mechanism.

## Corpus-specific live acceptance

After the baseline acceptance passes, the deployed virtual environment runs:

```text
scripts/corpus_runtime_live_acceptance.py
```

It proves:

### Service and authentication baseline

- public and local health pass;
- public and local readiness pass;
- public and local status pass;
- missing API key returns `403`;
- incorrect API key returns `403`;
- valid API key returns `200` without printing or storing the key in evidence.

### Internal links

An authenticated validation request containing one valid internal link and two references to one unresolved target returns:

- `valid: true`;
- no errors;
- contract version `0.2`;
- `internal_link_count: 3`;
- `broken_internal_link_count: 2`;
- exactly one `broken-internal-link` warning.

No persistent job is created.

### Missing local image

A synthetic private job referring to `assets/missing-image.png` proves:

- pipeline result `1`;
- status `failed`;
- step `input-validation`;
- failure code `missing-image-file`;
- no outputs;
- no derivation manifest;
- no build log, proving export did not start.

### Greek and Cyrillic

A synthetic private job proves all four authoritative outputs and exact Greek/Cyrillic text in:

- EPUB reader content;
- DOCX main-document XML;
- standard PDF text extraction;
- ND PDF text extraction.

The build log must contain no missing-character, fontspec or fatal error.

## Protected evidence

The default evidence directory is:

```text
/var/log/book-system/corpus-runtime-<UTC>-<target-prefix>
```

It is mode `0700`; files are mode `0600`.

Evidence includes:

- expected-before and target SHAs;
- launcher hash;
- baseline deployment/acceptance log;
- corpus acceptance summary and log;
- synthetic missing-image status/error evidence;
- synthetic four-format Greek/Cyrillic outputs and manifest;
- persistent job-storage snapshots before and after;
- repository configuration snapshots before and after;
- installed systemd-unit snapshots before and after;
- final `PASS` or `FAIL` result.

Private API-key content is never written to evidence.

## Pass condition

The release passes only when:

- baseline deployment and acceptance pass;
- corpus-specific acceptance passes;
- production ends cleanly on exact target `main`;
- persistent job storage is unchanged;
- protected repository configuration is unchanged;
- installed systemd unit content/permissions are unchanged;
- API and worker services remain active.

Only then may issues #90, #94, #96, #100, #101 and parent #62 close as completed.

Issue #71 remains open until a real external author, manuscript and payment-or-refusal outcome exist.

## Failure and rollback

On failure:

1. do not rerun blindly;
2. preserve the private evidence directory;
3. identify whether the failure occurred before deployment, during baseline deployment, or during corpus acceptance;
4. inspect the timestamped backup and exact previous commit recorded by the established deployment path;
5. perform a deliberate rollback using `docs/DEPLOYMENT_ROLLBACK.md` only after confirming the rollback target and service state.

The launcher never performs `git reset --hard`, `git clean`, force-push, deletion of persistent jobs or automatic rollback.
