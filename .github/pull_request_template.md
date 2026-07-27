## Authority

- [ ] Exact base commit is recorded.
- [ ] Exact reviewed head commit is recorded.
- [ ] Changed-file scope is listed and bounded.
- [ ] Required CI run passed at the exact head.
- [ ] Merge, deployment and destructive actions remain separately authorised.

## Issue linkage

- [ ] Use `Relates to #<issue>` when deployment, live rehearsal, physical review or other post-merge evidence remains.
- [ ] Use `Closes`, `Fixes` or `Resolves` only when merging this pull request itself satisfies every acceptance criterion.
- [ ] Operational issues will be closed explicitly after their final evidence is recorded.

## Production boundary

- [ ] Persistent jobs, logs and `config/env` are preserved.
- [ ] Fixtures are created as the service account or pass the committed service-account access audit.
- [ ] Any live acceptance uses a committed reviewed script, not a pasted ad hoc programme.
- [ ] Failure and signal paths leave private evidence and do not improvise recovery.

## Exclusions

- [ ] No unauthorised v0.2, print-production, Semantic Architect, account, billing or database work is included.
