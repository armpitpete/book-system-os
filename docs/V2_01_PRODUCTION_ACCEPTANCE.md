# V2-01 production deployment acceptance

## Status

This document prepares the production Pandoc upgrade and V2-01 deployment acceptance operation.

It does not authorise:

- merge;
- production execution;
- issue closure;
- another v0.2 route;
- print-production work; or
- Semantic Architect work.

## Human outcome

An authenticated author or publishing client can check whether manuscript Markdown is structurally acceptable before a job or publication output is created.

The production proof must show that this capability works without weakening the existing deterministic four-format publishing service or changing retained books.

## Candidate boundary

The implementation lane starts from exact repository commit:

```text
9dcfa92923ffe8a0cfac6918617d83f37aa577d9
```

After this lane is reviewed and merged, production acceptance must use the new exact accepted merge candidate containing the reviewed launcher. The base commit above must not be reused as the deployment candidate because it does not contain the operation prepared by this lane.

## One reviewed operation

Production execution uses:

```text
scripts/production_v2_01_acceptance.sh
```

The launcher is designed to be extracted from the exact accepted Git commit before the production checkout changes. This resolves the bootstrap problem: the current server checkout does not need to contain the new launcher, but the launcher being executed must match the exact Git object that will be deployed.

### Invocation shape

Replace `<accepted-40-char-commit>` only after exact-candidate review and merge authority have established the production candidate.

```bash
sudo bash -c '
set -Eeuo pipefail
cd /opt/book-system
EXPECTED_COMMIT="<accepted-40-char-commit>"
git fetch --prune origin
LAUNCHER="$(mktemp)"
trap '\''rm -f "$LAUNCHER"'\'' EXIT
git show "$EXPECTED_COMMIT:scripts/production_v2_01_acceptance.sh" > "$LAUNCHER"
chmod 0700 "$LAUNCHER"
"$LAUNCHER" \
  --repo-root /opt/book-system \
  --expected-commit "$EXPECTED_COMMIT" \
  --execute
'
```

This is one launcher invocation. The launcher performs and logs the internal mechanical steps. Merrin must not be asked to relay each command separately.

The launcher keeps retained-storage manifests in a root-only working directory.
It stages the exact accepted candidate tree separately under `/run` before the
production checkout moves. Every script or Python module used before the
guarded fast-forward comes from that staged candidate tree, including:

- `scripts/install_pinned_pandoc.sh`;
- `scripts/check_runtime_compatibility.py`; and
- `scripts/deploy_server.sh`.

The staged candidate tree is owned as `root:www-data` and made readable and
traversable by the service account, but not writable by it. The launcher verifies
that `www-data` can read the staged compatibility code and cannot write to the
staged tree or its parent path. Logs and retained-storage manifests remain
root-only.

The candidate deployment script is then executed from the staged tree with an
explicit `--repo-root /opt/book-system` target. This keeps script authority in
the reviewed candidate while all repository mutation remains bounded to the
production checkout. The temporary candidate tree is removed by the launcher
cleanup trap when the operation exits.

## Exact Pandoc authority

The reviewed release is:

```text
Pandoc 3.9.0.2
```

Official archive SHA-256 digests:

```text
linux-amd64  a69abfababda8a56969a254b09f9553a7be89ddec00d4e0fe9fd585d71a67508
linux-arm64  b6d21e8f9c3b15744f5a7ab40248019157ed7793875dbe0383d4c82ff572b528
```

Architecture is detected at execution. Any architecture outside amd64 or arm64 fails closed.

The runtime is installed outside the repository at:

```text
/opt/book-system-runtime/pandoc/<version>
```

The active version is exposed through:

```text
/opt/book-system-runtime/pandoc/current/bin/pandoc
```

The service units use that explicit path. A successful package-manager installation or version string alone is not acceptance evidence.

## Preflight protections

Before mutation, the launcher must prove:

1. it is running as root;
2. `--execute` was explicitly supplied;
3. the candidate is a full lowercase 40-character commit;
4. the production checkout is on `main` and clean;
5. `origin/main` equals the exact candidate;
6. the running launcher digest equals the launcher stored at that candidate;
7. `config/env` remains root-owned mode `0600`;
8. no second acceptance operation is running; and
9. retained book storage has been recorded before mutation.

A failed preflight makes no application deployment.

## Required operation

The launcher must then:

1. download the official architecture-specific Pandoc archive over HTTPS;
2. verify its pinned SHA-256 digest before extraction;
3. verify the exact release and functional `--sandbox` behaviour;
4. install or reuse the matching versioned runtime without overwriting differing content;
5. prove sandbox capability as `root` and `www-data`;
6. run the exact guarded deployment script from the staged candidate tree while
   explicitly targeting `/opt/book-system`;
7. verify both services use the pinned runtime path;
8. prove public health, readiness and route status;
9. prove missing and incorrect API keys return HTTP `403`;
10. prove a valid manuscript returns HTTP `200` and `valid: true`;
11. prove an invalid manuscript returns HTTP `200` and `valid: false`;
12. build temporary standard PDF, ND PDF, EPUB and DOCX files;
13. verify both PDF signatures and both ZIP-based archive structures;
14. remove temporary acceptance outputs;
15. prove retained book storage is unchanged from the pre-deployment manifest;
16. prove the final checkout is clean at the exact candidate; and
17. leave one root-readable acceptance log under `/var/log/book-system`.

## Accepted evidence

A passing log must end with:

```text
v2-01-production-acceptance=pass
```

It must also contain:

```text
root-and-www-data-pandoc-capability=pass
service-runtime-path=pass
retained-books-unchanged=pass
```

The live helper prints structured evidence for:

- health;
- readiness;
- status;
- authentication failures;
- valid validation;
- invalid validation;
- four output filenames, sizes and SHA-256 digests; and
- unchanged persistent book storage.

The API key itself must never appear in the log.

## Failure rule

Any failed check stops the operation and withholds V2-01 production acceptance.

A failed operation must not be described as complete merely because:

- the Pandoc archive installed;
- the repository deployed;
- services restarted;
- health passed; or
- one validation request succeeded.

The highest evidenced completion state must be reported accurately.

## Work still blocked after preparation

Until the exact implementation candidate is reviewed, accepted, merged, explicitly authorised for deployment and produces a passing production log:

- issues #64, #65 and #67 remain open;
- V2-01 remains incomplete in production;
- no later v0.2 route is authorised;
- no print-production work is authorised; and
- no Semantic Architect work is authorised.
