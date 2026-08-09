# Production current-main preflight

## Purpose

`scripts/production_current_main_preflight.sh` is the repository-owned, read-only evidence gate that must run before authorising a protected current-main production release.

It replaces bespoke conversational preflight shell blocks. The command does not deploy anything and always records:

```text
deployment-authorized=false
```

A passing preflight is evidence that one exact observed production predecessor can safely proceed to the explicit deployment-authorisation boundary for one exact GitHub `main` target. It is not deployment authorisation.

## Required execution surface

Run the command from a **clean candidate worktree at the exact target commit**. For production release work, create that candidate under `/var/tmp` so the same exact reviewed target can later supply the protected release wrapper if deployment is separately authorised.

The command independently verifies that `/var/tmp` is writable, traversable, executable and not mounted `ro`/`noexec`.

The production checkout remains `/opt/book-system` and must stay on clean `main` at the exact predecessor throughout preflight.

## Invocation

```bash
sudo bash scripts/production_current_main_preflight.sh \
  --repo-root /opt/book-system \
  --expected-before <40-character-production-sha> \
  --target-commit <40-character-main-sha>
```

Optional controls:

```text
--env-file /opt/book-system/config/env
--public-base-url https://publish.toiletrage.co.uk
--release-worktree-parent /var/tmp
--evidence-dir /var/log/book-system/<new-preflight-directory>
--stability-seconds 5
```

`--stability-seconds` is bounded to `1..60` and defaults to 5 seconds.

If no evidence directory is supplied, the command creates a new private directory under `/var/log/book-system` containing the UTC timestamp and target prefix.

## Evidence checks

The preflight fails closed unless all of these pass:

1. production HEAD exactly equals `--expected-before`;
2. production checkout is clean and on `main`;
3. the candidate command is running from a clean checkout at exactly `--target-commit`;
4. the production remote's live `refs/heads/main`, read with `git ls-remote`, exactly equals the target;
5. the predecessor is an ancestor of the target;
6. `config/env` remains a root-owned mode-`600` regular file and only its SHA-256 plus non-secret capacity settings are recorded;
7. API and worker services are active;
8. local and public `/health` and `/ready` pass;
9. worker PID and `NRestarts` remain unchanged across the stability window;
10. candidate requirements are checked against production requirements with the existing additive-only requirement planner, without installing anything;
11. production virtualenv `pip check` passes for root and `www-data`;
12. Pillow imports for root and `www-data`, with the installed version matching the candidate pin;
13. pinned Pandoc and XeLaTeX execute for root and `www-data`;
14. retained job count, active/locked counts, retained-state digest and Revision Studio digest are captured;
15. no active or locked publishing jobs exist;
16. configured disk/storage capacity is healthy;
17. `/var/tmp` is suitable for the release worktree;
18. the exact target `production_current_main_release.sh` exists, is hashed and contains the required protected invocation/readiness markers;
19. final production HEAD/clean state, protected config hash, retained jobs, Revision Studio state, API/worker state, worker PID/restarts and `pip check` remain unchanged.

## Non-mutation boundary

The preflight must not:

- fetch into the production checkout;
- switch, merge, reset or update production Git state;
- install or reconcile runtime packages;
- stop, start or restart services;
- change `config/env`;
- change retained jobs or Revision Studio state;
- delete production data;
- deploy code.

Remote `main` is observed with `git ls-remote`, so target binding does not require a production `git fetch`.

The only intentional writes are:

- private evidence files under the chosen evidence directory;
- a short executable suitability probe under the release-worktree parent, removed immediately after the check.

## Output

A pass prints:

```text
FRESH-PRODUCTION-PREFLIGHT=PASS
expected-before=<sha>
target-commit=<sha>
evidence=<path>
deployment-authorized=false
```

The evidence directory contains:

- `preflight.json` — structured evidence;
- `result.txt` — concise protected result and key digests.

Files are mode `600`; the evidence directory is mode `700`.

## Deployment boundary

After a pass, stop at the explicit owner-authorisation gate for the exact pair:

```text
<expected-before> -> <target-commit>
```

Do not silently replace either SHA with a newer value.

If deployment is authorised, the separate protected release wrapper remains authoritative:

```text
scripts/production_current_main_release.sh
```

Implementation, merge, production preflight, deployment, live acceptance and human artifact acceptance remain separate facts.
