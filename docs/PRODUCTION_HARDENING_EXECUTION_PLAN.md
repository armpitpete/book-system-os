# Book System OS v0.1 Production Hardening execution plan

## Authority

This plan implements the governing decision recorded in issue #31.

The **v0.1 deterministic publishing core remains 10/10 gates — 100% complete**. Its fixed completion denominator is closed and must not be reopened.

Production deployment and authenticated acceptance under issue #28 remain the final v0.1.8 release operation. Production hardening is a separate milestone after that release, not unfinished deterministic-core work.

## Baseline rule

Planning and documentation may be prepared before production acceptance.

Runtime implementation must begin only after all of the following are true:

1. issue #28 has passed without waiver;
2. exact commit `86e0227734686c94c186a2a453cbb0fcd65cbb50` has been accepted in production;
3. tag and GitHub release `v0.1.8` point to that exact commit;
4. the deployment evidence and operational acceptance results are recorded;
5. issue #28 is closed as completed.

The accepted `v0.1.8` tag is the immutable comparison baseline for every hardening lane.

## Execution policy

Safe work continues through inspection, implementation, automated testing, repair, commit, push and draft pull request without stopping at routine intermediate gates.

Stop only when:

- a merge or production deployment requires owner authority;
- the accepted baseline, authorised file scope or dependency state changes;
- an operation would delete or irreversibly alter production data;
- acceptance evidence is missing or contradictory;
- work would enter a feature or product boundary excluded by issue #31.

Each hardening lane must remain independently reviewable. Do not combine unrelated gates merely to reduce the number of pull requests.

## Required order

### Phase 0 — v0.1.8 release closure

Tracked by issue #28.

Required evidence:

- exact deployment commit;
- active API and worker services;
- successful local and public health checks;
- authenticated dashboard and API acceptance;
- successful four-format production-like job;
- retry and cleanup acceptance;
- release tag and GitHub release;
- recorded rollback point.

No hardening runtime pull request may merge before this phase is complete.

### Phase 1 — protect persistent data

#### Lane H-01 — Backup and restore

Deliverables:

- persistent-data inventory;
- backup command or script;
- retention and storage guidance;
- restore procedure for a clean installation;
- automated structural checks for backup contents;
- controlled restore rehearsal evidence.

Persistent data must include, where present:

- source manuscripts;
- job metadata and status;
- work products needed for diagnosis;
- published outputs;
- manifests;
- logs;
- event history;
- configuration shape, but never committed or copied secrets.

Exit condition: a representative production-like job store is restored onto a clean installation and verified without changing job identifiers or losing history.

#### Lane H-03 — Atomic persistent writes

Deliverables:

- one shared atomic text/JSON write primitive;
- atomic writes for `status.json`, `metadata.json` and `manifest.json`;
- safe event-history append behaviour or a documented durability boundary;
- interruption and malformed-write regression tests.

Exit condition: simulated failure before replacement cannot corrupt the previously valid final file.

### Phase 2 — recover interrupted work

#### Lane H-02 — Interrupted-job recovery

This lane depends on H-03 so recovery decisions can rely on durable state.

Deliverables:

- worker heartbeat or equivalent freshness evidence;
- stale-lock classification;
- abandoned-`running` classification;
- operator-visible recovery preview;
- explicit recovery action to `queued` or `failed`;
- recovery event history;
- controlled worker-termination test.

The system must never silently remove a lock or requeue a running job merely because time elapsed. Recovery requires evidence that the owning worker is no longer valid and must be auditable.

Exit condition: a deliberately interrupted job is detected and safely recovered without manual filesystem editing or source loss.

### Phase 3 — bound failure and capacity

#### Lane H-04 — Resource limits

Deliverables:

- configurable request/manuscript size limit;
- configurable queue limit;
- Pandoc and XeLaTeX subprocess timeouts;
- per-job and total-storage thresholds;
- controlled error states and readable logs;
- regression tests for every enforced limit.

Defaults must suit the existing single-server deployment and must not unexpectedly reject the existing accepted test manuscript.

Exit condition: oversized, over-capacity and stalled work fails predictably without wedging the worker or damaging existing jobs.

#### Lane H-05 — Readiness and observability

This lane depends on H-02 and H-04 because readiness must understand worker freshness and bounded capacity.

Deliverables:

- basic liveness endpoint for the API process;
- separate readiness endpoint;
- writable-storage check;
- worker-heartbeat freshness check;
- Pandoc and XeLaTeX availability checks;
- free-space threshold check;
- old queued/running job warning state;
- log rotation and retention guidance;
- operator-facing diagnostic output that does not expose secrets.

Exit condition: each missing dependency can be simulated and causes the documented readiness result while liveness continues to describe only the API process.

### Phase 4 — secure and simplify administration

#### Lane H-06 — Web and administrative security

Deliverables:

- CSRF protection for mutating dashboard requests;
- body-size enforcement before job creation;
- proportionate request and authentication rate limiting;
- administrative event logging for lifecycle changes, retries, cleanup and recovery;
- credential-rotation procedure;
- automated abuse-path tests.

Do not introduce a user-account system, billing or general public SaaS authentication in this lane.

Exit condition: unauthorised, cross-site, oversized and excessive requests fail with controlled responses while ordinary authenticated operation remains intact.

#### Lane H-07 — Dashboard consolidation

This lane should follow the security boundary so the consolidated forms and routes are built around the final mutation protections.

Deliverables:

- one authoritative dashboard submission route;
- proper templates or an equivalently maintainable rendering structure;
- removal of route deletion and HTML string injection;
- preserved test/production selection;
- preserved lifecycle, retry, history, download, cleanup and recovery controls;
- behavioural tests independent of brittle string insertion.

Exit condition: all existing and hardening-era dashboard behaviours pass through one maintainable route and template structure.

### Phase 5 — prove real manuscript behaviour

#### Lane H-08 — Manuscript regression corpus

Deliverables:

- small deterministic fixtures for individual Markdown features;
- representative combined manuscripts;
- large but accepted manuscript fixture or generator;
- controlled malformed-input fixtures;
- basic PDF, EPUB and DOCX validity checks;
- bounded CI execution time;
- documented distinction between unsupported input, invalid input and export-tool failure.

Required coverage:

- long chapters;
- Unicode and punctuation;
- images;
- tables;
- footnotes;
- nested lists;
- page breaks;
- YAML metadata;
- unusual heading structures;
- large accepted manuscripts.

Exit condition: valid fixtures build all four outputs and invalid fixtures fail in documented, reproducible ways.

### Phase 6 — prove release reversibility

#### Lane H-09 — Deployment rollback

This lane consumes the completed behaviour of all earlier hardening lanes.

Deliverables:

- exact-tag rollback procedure;
- separation of application checkout from persistent data and secrets;
- service restart and verification sequence;
- post-rollback access check for an existing completed job;
- controlled rollback rehearsal from a deliberately unsuitable candidate release;
- recorded recovery-time and data-integrity evidence.

Exit condition: the previous accepted tag is restored, services recover, and existing job data remains available and unchanged.

## Pull-request structure

The preferred pull-request sequence is:

1. backup and restore;
2. atomic persistent writes;
3. interrupted-job recovery;
4. resource limits;
5. readiness and observability;
6. web and administrative security;
7. dashboard consolidation;
8. manuscript regression corpus;
9. deployment rollback;
10. hardening completion authority and closure record.

A lane may be divided further when required for reviewability. It must not be merged with a later lane if doing so obscures acceptance evidence or makes rollback harder.

## Validation minimum

Every implementation pull request must run:

```text
python3 scripts/check_env.py
python3 -m compileall app scripts tests
python3 -m pytest -q
```

Where the lane changes real export behaviour, CI must also install Pandoc and XeLaTeX and run the real four-format integration tests.

Each pull request must include:

- exact accepted baseline or previous merged hardening commit;
- changed-file allowlist;
- tests added or updated;
- operational acceptance required after merge;
- rollback notes;
- confirmation that excluded product features were not introduced.

## Hardening completion authority

Hardening completion must use a separate fixed authority. It must not edit the v0.1 deterministic-core gate count or percentage.

The production-hardening authority should record nine binary gates:

| Gate | Requirement |
|---|---|
| H-01 | Backup and restore proven |
| H-02 | Interrupted-job recovery proven |
| H-03 | Atomic persistent writes proven |
| H-04 | Resource limits proven |
| H-05 | Readiness and observability proven |
| H-06 | Web and administrative security proven |
| H-07 | Dashboard consolidation complete |
| H-08 | Manuscript regression corpus passing |
| H-09 | Deployment rollback proven |

No partial percentage should be presented as overall Book System OS completion. Progress may be reported only as completed hardening gates out of nine.

## Excluded work

This execution plan does not authorise:

- `POST /api/v1/validate`;
- `/api/v1/publish*` routes;
- print imposition or printer-production workflows;
- physical-proof approval;
- Semantic Architect behaviour;
- editorial rewriting or content generation;
- multi-user accounts, billing or public SaaS operation;
- database-backed or distributed orchestration.

## Completion statement

After all nine gates pass and the hardened production deployment is accepted, the allowed statement is:

> Book System OS v0.1 Production Hardening is complete. The deterministic publishing core remains 100% complete. The wider Book System OS remains incomplete.

Only then may a separately reviewed v0.2 product contract authorise implementation beginning with `POST /api/v1/validate`.
