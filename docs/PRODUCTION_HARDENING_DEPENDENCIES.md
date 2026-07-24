# Production hardening dependency graph

```text
Issue #28 production acceptance and v0.1.8 release
  |
  +--> H-01 Backup and restore -----------------------------+
  |                                                          |
  +--> H-03 Atomic writes --> H-02 Interrupted recovery -----+--> H-09 Rollback proof
                         \                                    |
                          +--> H-04 Resource limits ----------+
                                   |                          |
                                   +--> H-05 Readiness -------+
                                   |                          |
                                   +--> H-06 Security --> H-07 Dashboard --> H-08 Corpus
```

H-09 closes only after every earlier gate is accepted.

No dependency edge extends into v0.2 implementation.
