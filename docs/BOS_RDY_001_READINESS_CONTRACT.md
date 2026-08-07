# BOS-RDY-001 — Readiness Claims

## Authority

Book System OS must never label an output `publication-ready` or `print-ready`
unless both the exact manuscript has the required Story Validation state and
the generated artifact itself has passed Book System OS production validation
and required human acceptance.

This is the machine-enforceable implementation contract for that rule. It does
not alter the historical v0.1 completion denominator.

## Boundary

Story Validation remains authoritative for narrative validation. Book System OS
consumes Story Validation evidence but does not duplicate its narrative rules.
Book System OS remains authoritative for artifact identity, production
validation and publication/print readiness claims.

Operational service readiness (`/ready`) is separate from book readiness.

## Independent states

The evaluator returns four independent states:

- `story-ready`
- `production-valid`
- `digital-publication-ready`
- `print-ready`

Passing one state never silently implies another.

`digital-publication-ready` and `print-ready` require all three of:

1. current Story Validation evidence for the exact manuscript SHA-256;
2. production validation for the exact artifact bytes, source manuscript,
   production configuration, relevant assets and applicable profile;
3. required human acceptance for the exact artifact SHA-256 and readiness class.

## Evidence bindings

Story Validation evidence records schema/profile versions, exact source
SHA-256, pass/fail state, evidence identity and decision time.

Production evidence records readiness class, artifact type, source SHA-256,
artifact SHA-256, production-configuration SHA-256, relevant-assets SHA-256,
validation profile/version, pass/fail state and evidence identity.

Human acceptance records readiness class, artifact type, artifact SHA-256,
acceptance profile/version, accepted/rejected state, evidence identity and
decision time.

Unknown schemas or profiles fail closed. Ambiguous duplicate evidence for the
same binding also fails closed rather than allowing record order to decide the
result.

## Persistence and integrity

Job-scoped evidence is stored at:

```text
<job>/evidence/bos-rdy-001.json
```

The record is atomically written, reuses the existing retained-source
provenance authority, and carries a canonical SHA-256 over the complete evidence
bundle. A source mismatch or evidence tamper is rejected.

## Invalidation

A changed bound input invalidates the affected readiness claim, including:

- manuscript bytes/SHA-256;
- Story Validation evidence/profile/version;
- production configuration;
- relevant assets;
- artifact bytes/SHA-256;
- production-validation profile/version;
- required human-acceptance evidence/profile.

Regeneration invalidates human acceptance unless the resulting artifact is
byte-identical.

## v0.2 dry-run boundary

The v0.2 publish dry-run remains structural validation and output planning only.
`publishable: true` does not mean BOS-RDY-001 readiness passed.

Dry-run responses explicitly return BOS-RDY-001 as `evaluated: false`, with all
four readiness states false and reason:

```text
dry-run-structural-validation-only
```

See `docs/V0_2_PUBLISH_DRY_RUN_API.md`.
