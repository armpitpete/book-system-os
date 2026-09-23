# Phase 0 — Baseline Preservation

## Status

**PHASE 0 CANDIDATE — IMPLEMENTATION BEHAVIOUR UNCHANGED**

Phase 0 establishes the exact Book System OS baseline before Publication Composition System v0.1 introduces new semantic and design contracts.

It is deliberately non-feature work.

## 1. Exact starting point

Phase 0 starts from protected-main lineage:

- repository baseline: `12a4d269e60048b4d42f8ab57c40916e8c7fd172`
- authority merge: PR #207, Publication Composition Direction v0.1
- programme authority: issue #206
- Phase 0 execution issue: #208

The accepted production deployment remains a separate fact from repository `main`.

The production baseline recorded by Current Product Contract v1 remains:

`34a470546770dd4c4d211966e2f5660f36cbc22a`

A newer repository commit is not thereby deployed or live-accepted.

## 2. Authority hierarchy preserved

Phase 0 does not rewrite or reopen:

1. historical v0.1 authority in `docs/PRODUCT_CONTRACT.md`, `docs/COMPLETION_CONTRACT.md`, `docs/RELEASE_ACCEPTANCE.md` and `docs/completion-authority.json`;
2. `docs/CURRENT_PRODUCT_CONTRACT_V1.md` and its fixed 12/12 current-engine denominator;
3. `docs/BOS_RDY_001_READINESS_CONTRACT.md`;
4. Story Validation as narrative authority;
5. Book System OS as retained-source, production, artifact, readiness and evidence authority;
6. human artifact acceptance as a separate exact-artifact gate;
7. protected deployment as a separate exact-state operation.

`docs/PUBLICATION_COMPOSITION_DIRECTION_V0_1.md` is future-direction authority only until each capability is implemented and accepted.

## 3. Current architecture inventory

The implemented journey at the Phase 0 baseline is:

```text
optional Author Asset Workspace
-> Markdown manuscript + publishing metadata
-> side-effect-free validation / dry-run
-> retained production job
-> worker
-> source verification
-> structural cleanup
-> local image / holder validation
-> Pandoc + Lua holder filter
-> XeLaTeX for PDFs / Pandoc writers for EPUB and DOCX
-> four retained artifacts
-> derivation manifest + hashes
-> BOS-RDY-001 evidence
-> explicit human acceptance where required
```

### Input and API

Primary implemented entry points are under `app/api/`.

Relevant current responsibilities include:

- authenticated dashboard/API behaviour;
- manuscript validation;
- publish dry-run;
- established production job submission;
- Author Asset Workspace;
- Revision Studio;
- readiness/status surfaces.

The executable future `POST /api/v1/publish*` gateway remains outside Current Product Contract v1.

### Manuscript validation

Current structural validation authority is primarily:

- `app/services/manuscript_validation.py`;
- `app/pipeline/input_validation.py`;
- `app/pipeline/structural.py`.

The current contract version is `0.2`.

Pandoc currently supplies a parsed document AST used to inspect headings, metadata, links, images, tables, notes, lists and raw-format content.

This is a current implementation fact, not a future semantic-authority decision.

### Jobs and workers

Current persistent execution is centred on:

- `app/services/job_queue.py`;
- `app/services/worker.py`;
- `app/pipeline/run_pipeline.py`.

A retained job stores the exact source under `input/book.md`, publishing metadata, copied referenced assets, status/event state, work/output/log directories and provenance.

### Current output authority

`app/services/publish_plan.py` defines the fixed current output set:

- `pdf_standard` -> `book-standard.pdf`;
- `pdf_nd` -> `book-nd.pdf`;
- `epub` -> `book.epub`;
- `docx` -> `book.docx`.

`app/pipeline/exporters.py` consumes that same output authority.

### Rendering implementation

Current rendering implementation consists of:

- Pandoc;
- `filters/image_holder_render.lua`;
- `templates/book-template-standard.tex`;
- `templates/book-template-nd.tex`;
- XeLaTeX for the two PDFs;
- Pandoc EPUB and DOCX writers.

These are implementation mechanisms for Current Product Contract v1.

They are not the intended permanent Publication Composition architecture.

### Provenance and readiness

Current provenance is centred on `app/services/provenance.py`.

It binds retained source identity and derivation evidence.

BOS-RDY-001 is centred on `app/services/artifact_readiness.py` and related evidence services.

It independently derives current source, artifact, production-configuration and relevant-asset identities.

Human acceptance remains bound to exact artifact hashes and is not implied by successful generation.

### Persistent state and deployment

Persistent state includes job, revision and author-asset state under the configured Book System root.

Production release remains exact-state and separately authorised through the repository-owned preflight/release controls.

Phase 0 does not deploy anything.

## 4. Current manuscript assumptions

The existing engine accepts Markdown with YAML metadata support and Pandoc extensions required by the current pipeline.

Current observed assumptions include:

- UTF-8 manuscript content;
- Markdown headings provide structural hierarchy;
- level-one headings are treated as book chapters for PDF output;
- title/language may come from request/publishing metadata or manuscript metadata;
- internal fragments may be repaired only under narrowly deterministic chapter-anchor conditions;
- image holders are controlled through explicit Markdown/Pandoc attributes;
- plain images retain compatibility behaviour;
- raw format-specific content is warned about rather than treated as portable semantics;
- front matter, body and back matter do not yet have a complete explicit semantic Book Input Contract.

Phase 1 must not infer new front/body/back semantics from heading text.

## 5. Hidden renderer policy inventory

Phase 0 identified publishing/design policy currently embedded in implementation rather than a resolved design model.

### Pandoc command policy

`app/pipeline/exporters.py` currently fixes, among other things:

- `--toc`;
- `--toc-depth=1`;
- `--top-level-division=chapter` for PDF;
- `--pdf-engine=xelatex`;
- specific Standard/ND template selection;
- image-holder Lua filter execution.

### Standard PDF template policy

`templates/book-template-standard.tex` currently contains:

- `book` class;
- 11pt;
- one-sided layout;
- A4 paper;
- 1 inch margins;
- line stretch 1.18;
- paragraph spacing 0.65em;
- no paragraph indentation;
- forced-here figure placement;
- template-owned title and TOC treatment.

### ND PDF template policy

`templates/book-template-nd.tex` currently contains:

- `book` class;
- 11pt;
- one-sided layout;
- A4 paper;
- 1.2 inch margins;
- line stretch 1.4;
- paragraph spacing 1em;
- no paragraph indentation;
- the same broad title/TOC framework.

These are precisely the kinds of hidden decisions that the future Book Design Profile must pull into explicit, versioned authority.

### Image rendering policy

`filters/image_holder_render.lua` maps semantic holders to writer-specific layout.

The future architecture should retain semantic holder intent while allowing the compositor implementation to change.

## 6. Source-of-authority map

| Concern | Current authority | Future authority |
|---|---|---|
| Canonical manuscript bytes | retained `input/book.md` + provenance | canonical BOS Markdown + provenance |
| Story/narrative quality | external Story Validation | unchanged |
| Basic manuscript validation | BOS validation contract + Pandoc parser | Book Input Contract parser/validator |
| Publishing metadata | `publishing_metadata.py` | Publication/Book semantic model |
| Output list | `publish_plan.PUBLISH_OUTPUTS` | publication output contract |
| Structural cleanup | `pipeline/structural.py` | bounded canonical transformations |
| Image semantics | image-holder contract | semantic asset/component model |
| Page geometry | hidden in LaTeX templates | resolved Book Design Profile |
| TOC depth | Pandoc command/template | resolved Book Design Profile |
| Typography/spacing | LaTeX templates | resolved Book Design Profile |
| Composition | Pandoc/Lua/XeLaTeX | Affinity bridge/compositor |
| Artifact identity | derivation manifest | retained exact-artifact provenance |
| Readiness | BOS-RDY-001 | versioned successor retaining same separation |
| Human visual decision | exact-artifact acceptance | unchanged principle |
| Deployment | exact-state release controls | unchanged principle |

## 7. Duplication and coupling to remove later

The future implementation should eliminate, rather than preserve:

- semantic dependence on a Pandoc AST;
- design rules split between Python, Pandoc command flags and LaTeX templates;
- duplicate Standard/ND layout implementations where a single resolved profile can drive composition;
- renderer-specific assumptions embedded in semantic validation;
- permanent parallel Affinity and Pandoc/XeLaTeX production stacks.

No such removal occurs in Phase 0.

## 8. Compatibility rules

During migration:

1. existing Current Product Contract v1 manuscripts must continue to work under their existing contract;
2. existing API behaviour must not silently change;
3. current four-format production remains available until replacement evidence passes;
4. image-holder semantics remain readable and supported during migration;
5. retained historical jobs/evidence remain interpretable;
6. BOS-RDY-001 evidence is never silently reinterpreted;
7. current production can remain on its accepted baseline independently of development;
8. new semantic contracts use explicit versions rather than changing old interpretation in place.

## 9. Version boundaries reserved

The future programme reserves explicit version namespaces for:

- `publication-model/v0.1`;
- `book-input/v0.1`;
- `book-design-profile/v0.1`;
- `publication-feasibility/v0.1`;
- `affinity-bridge/v0.1`;
- a later imposition contract.

Exact schemas are Phase 1+ work.

These identifiers must not be treated as implemented simply because the names are reserved.

## 10. Migration doctrine

Existing source remains governed by its existing contract.

New Book System Markdown must declare its semantic contract version explicitly.

The system must never silently reinterpret an old manuscript as a new semantic publication.

Any future migration/importer must:

- identify source contract/version;
- preserve or hash-link the original;
- produce deterministic converted output;
- report unsupported/ambiguous material;
- never invent content or publishing facts;
- create new provenance for the converted representation.

## 11. Renderer independence and simplification

The intended steady-state architecture is:

```text
Guided input
-> canonical BOS Markdown
-> BOS semantic model
-> feasibility
-> frozen design profile
-> Affinity bridge
-> Affinity document
-> required publication outputs
-> assurance
```

Pandoc, Lua rendering filters and XeLaTeX are transitional dependencies of the current accepted engine.

Future contracts must not make them permanent requirements.

They are removed once the Affinity replacement gate proves all still-required duties have replacement implementations and accepted evidence.

A duplicate legacy stack is not retained merely as a precaution.

## 12. Components protected from premature rewrite

Do not rewrite these merely to accommodate the new direction:

- authentication;
- persistent job lifecycle;
- retained-source identity/provenance;
- evidence hashing;
- readiness separation;
- human acceptance model;
- author-asset persistence;
- Revision Studio;
- backup/recovery controls;
- exact-state deployment controls.

Change them only when a later accepted contract demonstrates a real incompatibility.

## 13. Current real-book evidence inventory

Primary current substantial-real-book work is tracked by:

- #146 — complete substantial real-book acceptance with human artifact inspection;
- #153 — use *A Book for Neurodivergent Minds* as the substantial acceptance case;
- #71 — paid external book-production proof after the real-product evidence lane.

The existing real-book work demonstrates an important doctrine:

- machine generation is not human artifact acceptance;
- source/artifact evidence must be exact;
- defects found by real manuscripts justify bounded engine repairs;
- historical proof must not be silently treated as current-head proof after relevant changes.

Phase 0 does not claim those human gates are complete.

## 14. Regression baseline

Exact repository baseline:

`12a4d269e60048b4d42f8ab57c40916e8c7fd172`

Observed environment evidence:

- GitHub Linux CI for the baseline: PASS;
- local Windows clone: clean exact baseline before evidence work;
- local Python: 3.13.5;
- local Pandoc: 3.10;
- local XeLaTeX: unavailable;
- local WSL/bash: broken/unavailable for POSIX test execution.

A local Windows pytest attempt therefore produced environment-driven failures/errors and is **not** accepted as repository regression evidence.

Fresh Phase 0 acceptance must use the repository's Linux CI and the full export-regression workflow, which provisions the supported Pandoc/XeLaTeX toolchain.

## 15. No-regression boundary

Phase 0 must leave these facts unchanged:

- historical v0.1 completion authority;
- Current Product Contract v1 12/12 completion;
- currently accepted production deployment state;
- four current output keys;
- existing API/runtime behaviour;
- readiness-state separation;
- human-acceptance requirement.

Phase 0 creates no new publication-readiness claim.

## 16. Current and future architecture diagrams

### Current

```text
Markdown/request
      |
      v
validation/dry-run
      |
      v
retained job -> worker
      |
      v
structural cleanup + image validation
      |
      v
Pandoc + Lua
  |          |
XeLaTeX   EPUB/DOCX writer
  |
PDFs
      |
      v
manifest/provenance
      |
      v
BOS-RDY-001 + human gate
```

### Future

```text
Guided publication input
      |
      v
canonical BOS Markdown
      |
      v
semantic Publication/Book model
      |
      v
feasibility
      |
      v
resolved + frozen Design Profile
      |
      v
renderer/compositor contract
      |
      v
Affinity bridge -> Affinity document
      |
      v
publication outputs
      |
      v
machine assurance + exact human proof
```

Imposition is downstream of composed reading-order pages.

## 17. Phase 0 acceptance checklist

Phase 0 is accepted only when:

- [x] exact starting baseline is recorded;
- [x] authority hierarchy is explicit;
- [x] production baseline is separately recorded;
- [x] current architecture is inventoried;
- [x] current manuscript assumptions are inventoried;
- [x] hidden renderer policy is catalogued;
- [x] current output contract is recorded;
- [x] real-book evidence lanes are recorded;
- [x] compatibility rules are frozen;
- [x] version boundaries are reserved;
- [x] migration doctrine is frozen;
- [x] renderer independence is frozen;
- [x] Pandoc/Lua/XeLaTeX are explicitly transitional, not future architecture;
- [x] protected components are named;
- [x] current/future architecture diagrams exist;
- [x] local environment limitation is recorded honestly;
- [ ] fresh Linux core CI passes at exact Phase 0 PR head;
- [ ] fresh full export regression passes at exact Phase 0 PR head;
- [ ] changed paths are bounded to Phase 0 authority/test material;
- [ ] hostile review finds no unsupported completion/readiness claim;
- [ ] exact PR head is recorded;
- [ ] work stops before protected-main merge.

## 18. Phase 0 completion statement

Once the remaining machine and hostile-review gates pass, Phase 0 may be declared:

> The existing Book System OS baseline is mapped and preserved; current authority remains intact; hidden renderer policy and migration risks are explicit; the new Publication Composition architecture has a clean introduction boundary; and legacy Pandoc/Lua/XeLaTeX dependencies have a defined evidence-gated removal path.

Phase 1 may then begin from the accepted Phase 0 authority without treating any future capability as already implemented.
