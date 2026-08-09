# Book System OS — Current Product Contract v1

## Authority

This document is the authoritative contract for the **Book System OS that exists now**.

It does **not** rewrite, reopen or invalidate the historical v0.1 product contract in `docs/PRODUCT_CONTRACT.md`. The v0.1 deterministic publishing core keeps its fixed historical denominator of **10/10 gates — 100% complete**.

This contract creates a separate denominator for the current implemented publishing engine. It deliberately does not claim that the wider author-facing Book System OS, any individual book, or any commercial product model is complete.

## Current product purpose

Book System OS is a deterministic publishing engine and controlled revision/production service. It accepts structured manuscript input, validates and plans publication work without side effects, preserves exact source and evidence identity, produces four deterministic output formats, supports controlled revisions and image-holder semantics, and keeps story quality, production validity, digital-publication readiness and print readiness as separate claims.

The system must preserve author meaning. It may perform only authorised structural normalisation and rendering transformations. It must not silently invent, rewrite or editorially reinterpret manuscript content.

## Implemented user journey

The implemented journey is:

```text
Author/operator manuscript
-> authenticated validation
-> authenticated publish dry-run
-> optional deterministic production submission
-> retained source + persistent job
-> background worker
-> conservative structural normalisation
-> validated image-holder transformation when present
-> Pandoc/XeLaTeX four-format export
-> retained provenance, manifests, logs and evidence
-> Revision Studio proposal/review workflow when revision work is used
-> BOS-RDY-001 exact-source / exact-artifact readiness evaluation
-> required human acceptance for readiness classes that need it
```

The side-effect-free validation and dry-run routes do not themselves create jobs or artifacts. Production submission through the established job path remains separate from the planned executable `/api/v1/publish*` gateway.

## Deterministic publishing authority

Book System OS is authoritative for deterministic production mechanics:

- retained source identity and provenance;
- conservative structural normalisation;
- supported export commands and templates;
- generated artifact identity;
- local production configuration identity;
- relevant retained asset identity;
- four-format output production;
- production-validation evidence;
- revision evidence retained by Revision Studio;
- BOS-RDY-001 publication/readiness evaluation.

Book System OS must fail closed when required production evidence is missing, stale, mismatched, unsupported or unverifiable.

It must not use deterministic-production authority as permission to make narrative or editorial judgements.

## Story Validation vs Book System OS authority

**Story Validation** is authoritative for narrative/story validation. Book System OS consumes versioned Story Validation evidence bound to the exact source manuscript SHA-256; it does not duplicate Story Validation's narrative rules.

**Book System OS** is authoritative for production mechanics, exact retained source identity, artifact generation, artifact identity, production validation, relevant assets, production configuration and readiness claims.

The boundary is mandatory:

- story quality/readiness is not inferred from successful export;
- successful export is not publication readiness;
- production validity is not human acceptance;
- digital-publication readiness is not print readiness;
- print readiness is not inferred from another readiness class.

Operational service readiness at `/ready` is also separate from actual-book readiness.

## Validation and publish dry-run

### `POST /api/v1/validate`

The implemented validation route is authenticated in production and side-effect-free. It reuses the authoritative manuscript parser/normaliser behaviour, returns stable errors/warnings and a bounded structural summary, and creates no persistent publishing job or artifact.

Its authority is structural manuscript acceptability under the implemented v0.2 validation contract. It is not Story Validation and it does not make a publication-readiness claim.

### `POST /api/v1/publish/dry-run`

The implemented dry-run route reuses manuscript validation and returns the authoritative four-output plan, source identity and explicit non-readiness state without creating a job or rendering output.

`publishable: true` means only that the manuscript passed the bounded structural validation contract. The dry run must continue to report BOS-RDY-001 as unevaluated and must not turn structural validity into publication or print readiness.

## BOS-RDY-001 readiness states

`docs/BOS_RDY_001_READINESS_CONTRACT.md` remains the machine-enforceable readiness authority.

The evaluator returns four independent states:

- `story-ready`;
- `production-valid`;
- `digital-publication-ready`;
- `print-ready`.

Readiness is bound to authoritative current state rather than caller-supplied matching hashes. It derives and checks the exact retained manuscript, exact artifact bytes, production configuration, relevant assets, versioned evidence profiles and required human acceptance.

Any relevant change invalidates the affected claim. Regenerated artifacts invalidate human acceptance unless the artifact bytes remain identical.

## Revision Studio

Revision Studio is an implemented controlled revision system, not an unrestricted editor.

Its current authority includes:

- retained revision documents;
- proposed revisions;
- proposal inspection and comparison;
- explicit proposal decisions;
- revision history;
- exportable/verifiable revision packages;
- persistent revision state that must survive deployment unchanged unless revision work itself intentionally changes it.

Revision Studio does not silently promote a proposal into accepted authority. Human decision remains explicit.

Revision Studio is separate from Story Validation and from deterministic book export. A revision proposal, an accepted revision, a generated artifact and a readiness claim are different objects and must remain distinguishable.

## Image-holder validation and rendering

Image holders provide bounded layout semantics while keeping Markdown as the canonical internal representation.

Supported holder classes are:

- `inline`;
- `feature`;
- `portrait`;
- `full-page`;
- `ornament`.

The image-holder contract validates source suitability, local-file availability, effective resolution/DPI, permitted aspect/crop-loss bounds, caption requirements, decorative semantics and holder declarations.

The v0.2 renderer maps validated holders into controlled writer-specific layout semantics across both PDFs, DOCX and EPUB. It owns holder geometry and sanitises author-supplied positioning/size controls that would bypass the holder contract.

Relative local image assets must resolve from the retained manuscript input. Unsupported, remote or unsuitable holder inputs fail closed where the contract requires it.

The system does not provide arbitrary page coordinates, unrestricted resizing, free-floating desktop-publishing controls or destructive automatic raster cropping.

## Four-format output

The authoritative current production output set is:

| Output key | Artifact |
|---|---|
| `pdf_standard` | standard PDF |
| `pdf_nd` | ND-readable PDF |
| `epub` | EPUB |
| `docx` | DOCX |

The output set is shared by dry-run planning, deterministic production and readiness evidence.

Four-format generation proves that the production engine produced and structurally validated its expected artifacts. It does **not** by itself prove publication-ready or print-ready status for a real book.

## Provenance and evidence

The current system preserves an inspectable proof trail around production work. Evidence includes, where applicable:

- exact source manuscript SHA-256;
- retained source verification;
- job state and event history;
- build logs;
- output manifests and output-evidence hashes;
- production-configuration identity;
- relevant-asset identity;
- Story Validation evidence identity;
- production-validation evidence identity;
- human-acceptance evidence identity;
- BOS-RDY-001 evidence bundles;
- Revision Studio history/packages;
- protected deployment and live-acceptance evidence.

Evidence must be bound to the real object being claimed. A proxy, label, planned state or matching caller-supplied string must never substitute for the exact manuscript, exact artifact, actual production state or required human acceptance.

## Human acceptance

Human acceptance is a first-class evidence gate.

Where a readiness class requires human acceptance, the evidence must identify the exact artifact SHA-256, artifact type, readiness class, acceptance profile/version, decision state and evidence identity.

Machine tests may establish structural validity, deterministic output and production-validation facts. They must not claim that a real artifact has been visually or physically accepted by a human when that inspection has not occurred.

A real book therefore remains unaccepted until the required person has inspected the exact generated artifacts and explicitly accepted or rejected the applicable readiness classes.

## Current production and deployment model

The current production service runs from `/opt/book-system` behind the configured public gateway and uses separate API and worker services.

Production release is an exact-state operation, not a generic "pull latest" action. The protected current-main release model requires:

1. an exact observed production predecessor SHA;
2. an exact reviewed target SHA;
3. a clean production checkout;
4. target/main binding and ancestry checks;
5. runtime/toolchain and service-account compatibility checks;
6. retained-state and protected-config baselines;
7. a fresh detached release worktree at the exact target;
8. explicit deployment authorisation for the exact predecessor -> target transition;
9. guarded deployment using the reviewed release wrapper;
10. current-main live acceptance;
11. applicable feature-specific live acceptance;
12. final clean exact-target, service-health and retained-state checks.

Deployment, implementation, merge, machine acceptance and human artifact acceptance remain separate facts.

The image-holder rendering v0.2 production release at `34a470546770dd4c4d211966e2f5660f36cbc22a` established the baseline for this contract: guarded deployment, current-main live acceptance and four-format image-holder live acceptance passed while `actual_book_readiness_claimed=false` remained enforced.

## Current exclusions

The following are outside this current implemented-product contract:

- executable `POST /api/v1/publish` and publish status/list/retry gateway routes;
- an author-facing asset/image workspace;
- arbitrary page coordinates or desktop-publishing layout controls;
- automated destructive image cropping;
- printer-specific imposition, covers, spine, bleed or colour-management workflows;
- a claim that any substantial real book has passed full human artifact acceptance;
- public multi-user SaaS operation;
- billing and subscription infrastructure;
- a proven external-author commercial model;
- AI Semantic Architect behaviour;
- generative editorial rewriting;
- database-backed or distributed orchestration unless separately authorised.

These exclusions do not reduce completion of the fixed current-engine denominator below. They are future product lanes with their own evidence requirements.

## Future product lanes

Priority follows the strategic rule that Book System OS is currently a stronger **publishing engine** than **author-facing product**.

The next authorised lanes are, in order:

1. **Production preflight command** — commit the current production preflight as a tested, read-only repository command instead of relying on bespoke conversational shell blocks.
2. **Author Asset Workspace v0.1** — author-facing image upload, preview, suitability/DPI/aspect feedback, controlled holder selection, alt text, caption/decorative semantics and intended-layout preview while retaining holder Markdown as canonical internal representation.
3. **Real-book acceptance** — run a substantial real manuscript with real images through exact-source, four-format, BOS-RDY-001 and genuine human artifact inspection gates.
4. **Paid External Book Production Proof (#71)** — use one real external author/manuscript to measure preparation, failures, manual intervention, support, production/delivery time, four-format outcome and payment/refusal evidence before choosing a business model.

No billing/SaaS build or wider public gateway is authorised by this contract.

## Current Product Contract v1 completion denominator

This contract has a fixed **12-gate current-engine denominator**. It measures implementation and accepted system capability, not the readiness of any individual book and not the completeness of the wider aspirational product.

| Gate | Required current capability |
|---|---|
| CP-01 | Authenticated persistent publishing service and job/worker orchestration |
| CP-02 | Deterministic non-inventive normalisation and production authority |
| CP-03 | Side-effect-free authenticated manuscript validation |
| CP-04 | Side-effect-free authenticated publish dry-run with explicit non-readiness boundary |
| CP-05 | Deterministic standard PDF, ND PDF, EPUB and DOCX production |
| CP-06 | Exact source/artifact provenance, manifests, logs and evidence identity |
| CP-07 | Revision Studio controlled proposal/decision/history/package workflow |
| CP-08 | BOS-RDY-001 independent readiness evaluator and stale-evidence protection |
| CP-09 | Exact-artifact human-acceptance evidence model |
| CP-10 | Image-holder validation plus controlled four-format v0.2 rendering |
| CP-11 | Hardened exact-state production/deployment model with retained-state protection |
| CP-12 | Exact-target live production acceptance proving current-main and applicable feature-specific gates |

At the production baseline established on 2026-08-09, these twelve current-engine gates are implemented and accepted: **12/12 — 100% of Current Product Contract v1**.

That statement is deliberately scoped. It means:

> The current implemented Book System OS publishing-engine contract is complete.

It does **not** mean:

- the historical v0.1 denominator changed;
- the wider Book System OS is complete;
- the author-facing product gap is closed;
- a real book is publication-ready or print-ready;
- the external commercial model is proven.

No overall percentage for the wider Book System OS is authorised by this contract.
