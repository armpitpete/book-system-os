# Paid External Book Production Proof v0.1

## Status

This protocol prepares issue #71 for one real external-author trial. It does not itself prove demand and must not be used to close #71 without the required external evidence.

## Question being tested

Will one external author pay a fixed fee for bounded, deterministic production of an existing manuscript into four usable book formats, without editorial rewriting or a wider publishing service?

## Pilot offer

**Offer:** one bounded manuscript-production job.

**Pilot price:** **£149 fixed fee**.

**Payment rule:** the author must agree to the price before intake. Payment is due before final unwatermarked delivery. A documented refusal to pay, including the author's stated reason where supplied, is valid evidence but is not a successful sale.

**Included outputs:**

- standard PDF;
- ND-readable PDF;
- EPUB;
- DOCX.

**Included support:**

- one intake review against the written boundary;
- deterministic structural preparation needed to enter the existing pipeline;
- one production run;
- one correction round limited to demonstrable production defects or incorrectly transferred source material;
- delivery of the four output files and a plain-language completion note.

## Eligible manuscript

The candidate manuscript must:

- belong to, or be lawfully controlled by, the external author;
- be supplied as Markdown, DOCX, ODT or plain text;
- contain no material the author lacks permission to reproduce;
- be small enough to remain within the existing accepted service limits;
- be sufficiently complete to produce without substantive editing;
- have one identifiable author or authorised representative able to approve the boundary and delivery.

Images may be included only when the author supplies the files and confirms the right to use them. Missing, inaccessible or externally linked image assets are intake defects and must be resolved before production.

## Excluded work

The pilot does not include:

- developmental editing, copy-editing or proofreading;
- fact-checking, legal review or permissions clearance;
- ghostwriting or AI rewriting;
- cover design, illustration or image sourcing;
- ISBN purchase, retailer upload or distribution;
- print imposition, bleed, physical proofing or printer liaison;
- new output formats;
- Semantic Architect work;
- public sales pages or a general customer gateway;
- indefinite revisions or support outside the recorded correction round.

Requests outside this boundary must be declined or separately recorded; they must not silently expand the proof.

## Intake decision

Before accepting the manuscript, complete `docs/paid-external-proof/intake-boundary-template.md`.

Acceptance requires:

1. author identity and contact route recorded privately;
2. ownership/permission confirmation;
3. source files received and inventoried;
4. manuscript size and asset paths checked;
5. exclusions acknowledged;
6. price and payment timing accepted;
7. permission to retain bounded process evidence without publishing private manuscript content;
8. explicit go/no-go decision.

A manuscript that fails the boundary may be rejected. Rejection reasons are evidence and must be recorded without altering the source to force acceptance.

## Production procedure

1. Preserve the received source unchanged.
2. Record source filenames, sizes and SHA-256 identities.
3. Create a working copy for necessary deterministic preparation.
4. Record every manual intervention in `support-work-ledger.csv`.
5. Submit through the existing production path without adding product features.
6. Retain job status, error evidence, cleaned Markdown identity, derivation manifest and four output identities.
7. Inspect all four formats for opening, completeness and obvious content loss.
8. Record any failed input, retry, correction and support exchange.
9. Obtain the author's delivery response.
10. Record payment or explicit refusal evidence.

## Timing ledger

Measure elapsed and hands-on time separately for:

- candidate screening;
- intake clarification;
- source preparation;
- failed-input diagnosis;
- production operation;
- output inspection;
- correction work;
- customer support;
- delivery and payment administration.

Do not estimate retrospectively when exact timestamps or durations can be recorded.

## Evidence required to close issue #71

Issue #71 may close only when the repository issue contains a privacy-safe completion record proving:

- one real external author participated;
- the written boundary was agreed before work;
- a real manuscript was processed;
- all four accepted formats were produced and delivered;
- preparation, failures, intervention, support and elapsed time were recorded;
- payment of £149 was received, or an explicit refusal and reason were recorded;
- the author accepted, rejected or qualified the delivery;
- the final decision record compares the fixed-fee result with the effort required.

Private manuscript content, personal contact details and payment credentials must not be committed to GitHub. Use opaque evidence identifiers and redacted summaries.

## Decision rule

Complete `decision-record-template.md` after the trial.

Default interpretation:

- **Continue per-book fixed fee** when payment is received, delivery is accepted, and total hands-on time is no more than 4 hours without unplanned product development.
- **Test a managed-production package** when payment is received or strongly supported, but support/preparation exceeds 4 hours or requires repeated coordination that customers appear willing to fund.
- **Correct and repeat once** when the main failure is a bounded, remediable production defect rather than weak demand.
- **Stop wider commercialisation** when the candidate refuses the price because the outcome lacks value, the work requires substantive editing/print services outside scope, or support burden makes either offer uneconomic.

One trial is directional evidence, not market validation. It authorises only the recorded next decision.

## Stop rules

Stop the trial and preserve evidence when:

- rights or consent are uncertain;
- private data cannot be handled safely;
- the author requests excluded work as a condition of participation;
- the source would require destructive or meaning-changing repair;
- the production system exposes a security or data-integrity concern;
- payment terms become disputed;
- the author withdraws.

## Repository and deployment boundary

This proof uses the accepted production service. It does not authorise runtime, API, template or deployment changes. Any defect requiring code changes must enter its own issue, review, CI and protected merge/deployment sequence.
