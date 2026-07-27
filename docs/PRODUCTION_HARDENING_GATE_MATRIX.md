# Book System OS v0.1 Production Hardening gate matrix

This matrix is subordinate to issue #31 and `docs/PRODUCTION_HARDENING_EXECUTION_PLAN.md`.

It is a planning and evidence index. It does not alter the completed v0.1 deterministic-core denominator.

| Gate | Depends on | Primary deliverable | Automated evidence | Controlled operational evidence | Status |
|---|---|---|---|---|---|
| H-01 Backup and restore | Accepted `v0.1.8` baseline | Persistent-data inventory, backup and restore procedure | Backup-content validation tests | Restore production-like jobs onto a clean installation | Complete — #34 |
| H-03 Atomic persistent writes | Accepted `v0.1.8` baseline | Shared atomic write primitive and migrated JSON writes | Fault-injection and malformed-write tests | Confirm existing production-like jobs remain readable after upgrade | Complete — #35 |
| H-02 Interrupted-job recovery | H-03 | Heartbeat, stale classification and audited recovery action | Stale lock/running-state regression tests | Kill a controlled worker and recover its job without filesystem edits | Complete — #36 |
| H-04 Resource limits | H-03 | Request, queue, timeout and storage limits | Limit and timeout tests | Confirm ordinary accepted manuscripts still build | Complete — #37 |
| H-05 Readiness and observability | H-02, H-04 | Readiness endpoint, heartbeat, dependency and capacity checks | Dependency-failure readiness tests | Demonstrate stopped publishing is visible to an operator | Complete — #38 |
| H-06 Web and administrative security | H-04 | CSRF, rate limiting, body limits and audit events | CSRF, abuse, limit and authentication tests | Rotate credentials and verify administrative events | Complete — #39 |
| H-07 Dashboard consolidation | H-06 | One authoritative route and maintainable templates | Full dashboard behavioural regression suite | Confirm all dashboard operations through authenticated production-like use | Complete — #40 |
| H-08 Manuscript regression corpus | H-04, H-07 | Valid and malformed manuscript fixtures with format checks | Four-format corpus CI | Review representative outputs for usable structure | Complete — #41 |
| H-09 Deployment rollback | H-01 through H-08 | Exact-tag rollback procedure and rehearsal | Script/static validation where applicable | Roll back a deliberately unsuitable candidate without data loss | Next — #42 |

## Current progress

```text
v0.1 Production Hardening: 8/9 gates complete
```

The next bounded lane is H-09 deployment rollback under issue #42. The live rollback rehearsal, merge and production deployment remain protected gates.

## Progress reporting

Hardening progress may be reported only as completed gates out of nine, for example:

```text
v0.1 Production Hardening: 8/9 gates complete
```

Do not present the hardening result as overall Book System OS completion.

## Evidence rule

A gate becomes complete only when:

1. its implementation pull request is merged from the expected baseline;
2. required CI passes at the exact reviewed head;
3. controlled operational evidence is recorded where required;
4. no acceptance criterion is waived;
5. excluded v0.2, print-production or Semantic Architect work is absent.
