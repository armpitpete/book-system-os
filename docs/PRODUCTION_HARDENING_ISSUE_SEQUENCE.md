# Book System OS v0.1 Production Hardening issue sequence

This file provides the bounded issue order under issue #31.

Do not implement these lanes before issue #28 has completed and `v0.1.8` has been accepted and tagged at exact commit `86e0227734686c94c186a2a453cbb0fcd65cbb50`.

| Order | Gate | Proposed issue title | Blocking dependency |
|---:|---|---|---|
| 1 | H-01 | Prove Book System OS backup and clean-system restore | #28 |
| 2 | H-03 | Make persistent JSON writes atomic | #28 |
| 3 | H-02 | Recover interrupted and stale-locked jobs safely | H-03 |
| 4 | H-04 | Bound manuscript, queue, export and storage resources | H-03 |
| 5 | H-05 | Add worker-aware readiness and operational observability | H-02, H-04 |
| 6 | H-06 | Harden dashboard mutations and administrative security | H-04 |
| 7 | H-07 | Consolidate dashboard routing and templates | H-06 |
| 8 | H-08 | Add representative manuscript regression corpus | H-04, H-07 |
| 9 | H-09 | Prove exact-tag production rollback without data loss | H-01 through H-08 |
| 10 | Closure | Record v0.1 Production Hardening completion authority | H-01 through H-09 |

## Issue creation rule

Create each implementation issue only when its dependencies are satisfied or when advance design work is clearly marked as non-runtime planning.

Each issue must contain:

- exact starting commit;
- changed-file allowlist;
- fixed behaviour scope;
- automated validation;
- controlled operational acceptance;
- rollback expectations;
- explicit exclusions;
- stop conditions.

The execution agent may continue through safe implementation and draft-PR actions without requesting approval at every intermediate step. Merge and production deployment remain protected actions.
