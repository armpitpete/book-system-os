# Real-book acceptance

## Purpose

A successful four-format build is not the end of Book System OS acceptance.

The real-book acceptance workflow connects the existing retained job, exact artifact hashes and BOS-RDY-001 evaluator to three kinds of evidence that must remain distinct:

1. external Story Validation for the exact manuscript;
2. Book System OS production-validation evidence for the exact generated artifact;
3. an explicit human accept/reject decision for the exact artifact where the requested readiness class requires it.

The operator command is:

```bash
python -m scripts.real_book_acceptance --help
```

It does not perform Story Validation, invent a production pass or infer human acceptance. It records an explicit result only after the corresponding evidence exists.

## Fixed evidence profiles v1

The operator workflow uses the versioned requirements in `app.services.real_book_acceptance.READINESS_REQUIREMENTS_V1`.

| Evidence | Profile | Version |
|---|---|---:|
| Story Validation | `story-validation/external` | `1` |
| production-valid | `book-system-os/production-valid` | `1` |
| digital-publication-ready production validation | `book-system-os/digital-publication` | `1` |
| print-ready production validation | `book-system-os/print` | `1` |
| digital human acceptance | `human/digital-artifact` | `1` |
| print human acceptance | `human/print-artifact` | `1` |

Changing these requirements is a contract change. Do not silently reinterpret old evidence under a new profile.

## Start with a retained real-book job

The job must contain the exact manuscript used for production. A completed production job will also contain the four normal outputs and the derivation manifest.

Show the current state with:

```bash
python -m scripts.real_book_acceptance show <job-id>
```

Missing evidence is reported as not ready. It is not guessed.

## Record Story Validation

Only record a pass when an inspectable external Story Validation decision exists for the exact retained manuscript and genuinely satisfies the `story-validation/external` v1 profile.

```bash
python -m scripts.real_book_acceptance story <job-id> \
  --state pass \
  --evidence-id '<stable external decision or evidence reference>'
```

Book System OS derives the manuscript SHA-256 from the retained source. The operator does not type or copy the hash into the evidence record.

An editorial review, automated build or old acceptance record is not automatically Story Validation merely because it concerns the same book. The evidence reference must identify the actual authority being relied on.

## Record production validation

Production validation is an explicit result under one of the versioned Book System OS profiles. The command derives the current source, artifact, production-configuration and asset hashes itself.

Example:

```bash
python -m scripts.real_book_acceptance production <job-id> \
  --artifact pdf_standard \
  --readiness-class production-valid \
  --state pass \
  --evidence-id '<production validation record>'
```

The `production-valid` profile requires an inspectable production-validation record for the exact artifact after the ordinary build/manifest integrity checks have passed.

The `digital-publication-ready` production profile additionally requires the applicable digital-format checks for that exact artifact. The `print-ready` production profile additionally requires the applicable print-production/preflight checks for the exact PDF. These records must exist before a pass is entered; the command is not the validation itself.

Unsupported combinations fail closed. EPUB and DOCX cannot be marked print-ready under artifact contract v1.

## Record human acceptance

Human acceptance is a separate decision and is only recorded after the person has inspected the exact generated artifact for the requested readiness class.

```bash
python -m scripts.real_book_acceptance accept <job-id> \
  --artifact pdf_standard \
  --readiness-class digital-publication-ready \
  --state accepted \
  --evidence-id '<human decision record>'
```

Use `rejected` when the artifact was inspected and rejected. Do not use `accepted` to mean "the build passed".

The artifact SHA-256 is derived from the retained file and checked against the derivation manifest before the decision can be persisted.

## Re-evaluate

After every evidence record, the command prints the current BOS-RDY-001 result. You can also rerun:

```bash
python -m scripts.real_book_acceptance show <job-id>
```

The four states remain independent:

- `story-ready`;
- `production-valid`;
- `digital-publication-ready`;
- `print-ready`.

A digital pass does not create a print pass. A print decision does not silently establish an unsupported state.

## Staleness and regeneration

Evidence is bound to actual retained state. If manuscript bytes, relevant assets, production configuration or artifact bytes change, stale evidence fails closed.

Do not edit a generated artifact in place and then reuse its previous acceptance. Regenerate the book and run a new evidence cycle. Preserve old evidence as history rather than pretending it applies to new bytes.

## Books without images

A real book does not need artificial artwork to prove Book System OS.

If the intended publication is genuinely text-only, zero image assets is a valid real-book input. Do not invent decorative artwork merely to exercise Author Asset Workspace.

Author Asset Workspace should be proved with a real book that genuinely uses intended images. That is a separate product-evidence question from whether a substantial manuscript can complete the publishing and exact-artifact acceptance chain.
