# Production hardening decisions

## D-01 — Preserve deterministic-core completion

The v0.1 deterministic publishing core remains 10/10 gates — 100% complete. Production hardening is separate and does not reopen that denominator.

## D-02 — Release before runtime hardening

Issue #28 must accept and release exact commit `86e0227734686c94c186a2a453cbb0fcd65cbb50` as `v0.1.8` before runtime hardening begins.

## D-03 — Recoverability before feature growth

Backup, atomic persistence and interrupted-job recovery precede v0.2 features.

## D-04 — Readiness is not liveness

API process liveness and end-to-end publishing readiness must be reported separately.

## D-05 — Routine safe work is continuous

Within an authorised lane, implementation continues through test, repair, commit, push and draft pull request without pausing at artificial intermediate gates.

## D-06 — Merge and production remain protected

Pull-request merge, production deployment and irreversible data operations require explicit owner authority.
