# Protected Corpus Runtime Release

## Purpose

This procedure deploys and live-accepts the remaining Book System OS runtime corrections under one exact commit and rollback boundary:

- missing local Markdown images fail before export;
- Greek and Cyrillic text remains visible and Unicode-extractable in both PDF templates;
- the public validation API exposes unresolved internal-link warnings and occurrence counts.

Test-only corpus additions require no separate production action.

## Authority boundary

Release is permitted only after the release-tooling pull request is merged and its exact merge SHA is known. Production must still equal the authorised expected-before SHA. Both production and the detached candidate worktree must be clean, and `origin/main` must equal the exact target SHA.

The launcher does not auto-rollback. Failure preserves evidence and the timestamped backup created by the established deployment path.

## Prepare a new detached worktree

Use a new path. Do not delete or reuse an existing worktree or evidence directory.

```bash
git -C /opt/book-system fetch --prune origin
RELEASE_WORKTREE="/run/book-system-corpus-release-$(date -u +%Y%m%dT%H%M%SZ)"
sudo git -C /opt/book-system worktree add --detach "$RELEASE_WORKTREE" <TARGET_COMMIT>
```

Run the exact committed launcher through `bash`:

```bash
sudo bash "$RELEASE_WORKTREE/scripts/production_corpus_runtime_release.sh" \
  --repo-root /opt/book-system \
  --expected-before <EXPECTED_PRODUCTION_COMMIT> \
  --target-commit <TARGET_COMMIT> \
  --confirm "DEPLOY <TARGET_COMMIT>"
```

A custom new evidence directory may be supplied with:

```text
--evidence-root /var/log/book-system/<new-private-directory>
```

## Pre-mutation proof

The launcher requires:

- root authority;
- full lowercase 40-character SHAs;
- different expected-before and target SHAs;
- exact typed confirmation;
- launcher bytes matching the target commit;
- clean candidate worktree at the target SHA;
- clean production `main` at the expected-before SHA;
- `origin/main` at the target SHA;
- target descending from expected-before;
- the protected environment file;
- a new private evidence directory.

## Deployment path

The launcher reuses `scripts/production_v2_01_acceptance.sh`. That accepted path stages the exact target, verifies the pinned runtime, runs `deploy_server.sh`, restarts and checks services, and performs baseline four-format acceptance. The corpus launcher does not introduce a competing deployment mechanism.

## Corpus-specific live acceptance

The deployed virtual environment runs `scripts/corpus_runtime_live_acceptance.py`.

### Service and authentication

It proves public and local health, readiness and status. It also proves missing and incorrect API keys return `403`, while the valid key returns `200`. The key is never printed or written to evidence.

### Internal links

An authenticated request with one valid internal link and two references to one unresolved target must return:

- `valid: true`;
- no errors;
- contract version `0.2`;
- `internal_link_count: 3`;
- `broken_internal_link_count: 2`;
- exactly one `broken-internal-link` warning.

No persistent job may be created.

### Missing local image

A synthetic private job referring to `assets/missing-image.png` must produce:

- pipeline result `1`;
- status `failed`;
- step `input-validation`;
- failure code `missing-image-file`;
- no outputs, manifest or build log.

### Greek and Cyrillic

A synthetic private job must create all four authoritative outputs and retain exact Greek and Cyrillic text in EPUB, DOCX, standard PDF and ND PDF. The build log must contain no missing-character, fontspec or fatal error.

## Protected evidence

The default directory is:

```text
/var/log/book-system/corpus-runtime-<UTC>-<target-prefix>
```

The directory is mode `0700`; files are mode `0600`. Evidence includes:

- expected-before and target SHAs;
- launcher hash;
- baseline deployment/acceptance log;
- corpus acceptance summary and log;
- synthetic job evidence and four outputs;
- job-storage snapshots before and after;
- repository-configuration snapshots before and after;
- installed-systemd-unit snapshots before and after;
- final `PASS` or `FAIL` result.

## Pass condition

Release passes only when:

- baseline deployment and acceptance pass;
- corpus-specific acceptance passes;
- production ends cleanly on exact target `main`;
- persistent job storage is unchanged;
- protected repository configuration is unchanged;
- installed systemd unit content and permissions are unchanged;
- API and worker services remain active.

Only then may issues #90, #94, #96, #100, #101 and parent #62 close. Issue #71 remains open until a real external author, manuscript and payment-or-refusal outcome exist.

## Failure and rollback

On failure:

1. do not rerun blindly;
2. preserve the private evidence directory;
3. identify whether failure occurred before deployment, during baseline deployment, or during corpus acceptance;
4. inspect the timestamped backup and previous commit recorded by the established deployment path;
5. use `docs/DEPLOYMENT_ROLLBACK.md` only after confirming the rollback target and service state.

The launcher never performs `git reset --hard`, `git clean`, force-push, persistent-job deletion or automatic rollback.
