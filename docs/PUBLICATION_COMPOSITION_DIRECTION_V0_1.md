# Publication Composition Direction v0.1

## Status

**FROZEN DIRECTION / IMPLEMENTATION NOT YET ACCEPTED**

This document records the agreed future direction for Book System OS after the September 2026 composition, bookmaking and Affinity design discussion.

It does **not** rewrite or supersede `docs/CURRENT_PRODUCT_CONTRACT_V1.md`, the fixed 12/12 current-engine denominator, the current four-format production contract, any existing production baseline, or any existing readiness claim. Those remain authoritative for the product that exists now.

This document is authority for **future implementation direction**. Capabilities described here become implemented product authority only through their own exact-source implementation, regression, acceptance and protected release evidence.

## 1. Strategic direction

Book System OS should evolve from a renderer-centred book generator into a deterministic **publication composition system**.

The core system should own:

- publication content and semantic structure;
- publication type;
- feasibility;
- design recommendations and their explanations;
- resolved design choices;
- bookmaking mechanics;
- production constraints;
- exact provenance;
- validation and acceptance.

Specialist renderers should implement those resolved decisions. Renderers must not become hidden sources of publishing policy.

Books remain the first mature publication family, but the architecture must not assume that every future publication is a conventional trade book.

Future publication families may include:

- books;
- chapbooks;
- pamphlets;
- zines;
- magazines;
- journals;
- catalogues;
- programmes;
- miniature/A-series publications;
- workbooks;
- photobooks;
- other structured print/digital publications justified by real use.

## 2. Canonical authoring path

The normal user should interact with a **guided publication input page**, not raw YAML, LaTeX or specialist publishing syntax.

For books, the guided page should include at minimum:

- title;
- subtitle where applicable;
- author / display name;
- language and edition information where applicable;
- guided front-of-book matter;
- body structure;
- parts;
- chapters;
- sections;
- guided end-of-book matter;
- semantic assets;
- publication/design choices only when relevant.

The page should generate correctly formatted, versioned canonical Markdown that the engine can read deterministically.

Markdown remains the canonical human-readable manuscript/content form. The system must not require a second author-facing proprietary manuscript language merely to represent book structure.

## 3. Book Input Contract v0.1

The next contract should define **correctly formatted Book System Markdown**.

It should provide explicit semantics for:

- contract version;
- title, author and publishing metadata;
- front matter;
- body;
- back matter;
- parts;
- chapters;
- sections;
- stable component identifiers;
- supplied versus generated matter;
- semantic asset references;
- explicit ordering;
- UTF-8 input;
- strict validation;
- no silent invention.

Front/body/back identity must not be inferred from arbitrary heading text such as `# Acknowledgements`. The canonical representation must preserve the fact that an item is front matter, a chapter, back matter, etc.

Input order is authoritative unless a separately accepted rule explicitly permits generated ordering behaviour.

## 4. Guided front and back matter

The input UI should guide users through common matter rather than requiring them to know publishing conventions or write boilerplate unaided.

Potential front-matter components include:

- half-title;
- title page;
- copyright / publication page;
- edition notice;
- dedication;
- epigraph;
- contents;
- foreword;
- preface;
- introduction;
- reader/accessibility notes.

Potential back-matter components include:

- afterword;
- acknowledgements;
- appendices;
- notes;
- references;
- bibliography;
- glossary;
- resources;
- further reading;
- index;
- about the author;
- also by the author;
- credits;
- permissions;
- colophon.

The v0.1 controlled vocabulary should remain deliberately small and expand only when real publications demonstrate a need.

Generated matter must be deterministic from supplied facts. The system must not invent copyright ownership, ISBNs, dates, biographies, licence wording or similar publishing facts.

## 5. Explanation-first choice model

Meaningful user choices must be presented as:

1. a recommended option;
2. a plain-language explanation;
3. the practical consequence of choosing differently;
4. a default already selected where safe.

The user should normally be able to continue without mastering publishing jargon.

Example:

> **First chapter on a right-hand page; later chapters on the next available page — Recommended**
>
> Gives the opening of the book a traditional right-hand start without creating unnecessary blank pages throughout the book.

Options irrelevant to the publication type or actual content should be hidden.

Control levels should be:

- **Simple** — common meaningful choices;
- **Advanced** — less common professional choices;
- **Expert/read-only diagnostics** — resolved geometry and production numbers, normally calculated rather than manually edited.

## 6. Book Design Profile

Bookmaking mechanics, genre conventions, typography and production geometry should resolve into one versioned **Book Design Profile**.

The profile should be derived from:

- publication/book type;
- genre;
- design family;
- accessibility profile;
- manuscript/content characteristics;
- target production route;
- explicit user choices.

Genre must influence design strongly enough to produce recognisably appropriate interiors, but genre must not be treated as a crude font switch or stereotype.

Book type controls structural/layout capabilities. Genre contributes conventions. Design family supplies an aesthetic system. Accessibility modifies readability without discarding publication identity.

## 7. Evidence-backed geometry

Trim size, margins, text block, type size, leading and related geometry must be reasoned and measurable.

The system must distinguish:

- printer/manufacturer minimums;
- binding requirements;
- typography/readability requirements;
- optical design requirements.

Printer minimums are not automatically good design targets.

A size recommendation should explain why it fits the publication, for example:

- content volume;
- genre/book-type convention;
- line measure;
- page-count effect;
- figures/tables;
- binding;
- production platform compatibility;
- portability and physical character.

Exact geometry must be resolved and frozen for a production candidate.

## 8. Bookmaking mechanics

The resolved design profile must explicitly control relevant physical-book mechanics, including:

- recto/verso policy;
- first-chapter and later-chapter start policy;
- part-opening policy;
- semantic blank pages;
- folios;
- running heads;
- chapter opening position;
- first-paragraph treatment;
- paragraph indentation/spacing;
- scene breaks;
- front-matter numbering;
- contents behaviour;
- heading keep rules;
- widow/orphan policy;
- hyphenation;
- footnote/endnote behaviour;
- references;
- figure/caption rules;
- table rules;
- back-matter starts;
- spread-aware behaviour where supported;
- print/digital divergence.

A right-hand page is a recto/odd page for left-to-right publications, but not every chapter must universally start recto. That is a profile choice, not a hidden renderer assumption.

Blank pages required for physical pagination must be semantic blanks: no accidental running head, ornament or visible folio unless a profile explicitly requires it.

## 9. Publication Feasibility Engine

Before composition, the system should determine whether the requested physical publication is feasible.

Inputs may include:

- publication size;
- requested page count/extent;
- content volume;
- required front/back matter;
- typography constraints;
- images/tables;
- binding;
- bleed;
- production platform.

Outcomes:

- **PASS** — comfortably feasible;
- **CAUTION** — feasible only with a meaningful design compromise;
- **REJECT** — cannot satisfy the request without violating readability, production or accepted design rules.

The engine must not “solve” impossible requests by silently shrinking type, crushing margins or reducing leading below the accepted profile.

Example: a 16-page A7 chapbook containing 90,000 words should be rejected before layout.

## 10. Publication sizes and unusual formats

The system should support ordinary trade sizes and later smaller/larger formats where appropriate, including A-series formats such as A6/A7.

Small formats must be treated as distinct physical design problems, not normal books scaled down.

The system should explain consequences such as:

- short line measures;
- page-count increase;
- relative margin consumption;
- image/caption pressure;
- heading treatment;
- binding thickness;
- suitability for the proposed publication type.

## 11. Imposition

Page design and print-sheet imposition must remain separate concepts.

The publication is composed in reading order first.

A later imposition stage may arrange publication pages onto larger sheets for printing/folding/cutting, including:

- booklet order;
- multi-up layouts;
- cut/fold marks;
- sheet signatures;
- required 180-degree rotation of panels for particular fold patterns.

Imposition must never be achieved by corrupting canonical reading-order content. Rotation is distinct from mirroring.

A7-on-A4 folded publications are a representative acceptance case for this future subsystem.

## 12. Affinity strategic integration

Affinity is the preferred future **advanced-composition target**, subject to a bounded SDK/scripting feasibility spike.

Book System OS remains authoritative for:

- source content;
- semantic structure;
- feasibility;
- design reasoning;
- resolved Book Design Profile;
- provenance;
- acceptance.

Affinity may provide:

- master pages;
- linked text frames;
- paragraph/character styles;
- sophisticated typography;
- graphical chapter openings;
- image-led layouts;
- complex grids;
- spreads;
- bleed;
- vector/pixel integration;
- preflight;
- professional visual proofing;
- final print composition.

The intended direction is:

```text
Guided input
-> canonical Book System Markdown
-> resolved Publication/Book Design Profile
-> Affinity bridge
-> controlled Affinity document
-> Affinity export / professional graphical finishing
```

The exact bridge mechanism and native-document workflow must be proven against the official Affinity scripting/SDK surface before it becomes mandatory architecture.

Affinity scripting is currently treated as an emerging/beta dependency. Book System OS must not become unable to produce accepted text-led publications merely because Affinity automation is unavailable.

## 13. Renderer responsibility

Long-term, Book System OS should own **design and assurance**, while specialist engines own final rendering where that reduces duplicated engineering.

Potential target state:

- Affinity for advanced print composition and, if proven, PDF/EPUB export;
- existing/Pandoc path retained where it remains stronger or necessary;
- DOCX retained through an appropriate semantic conversion path unless Affinity later proves a suitable equivalent;
- canonical Markdown retained regardless of output renderer.

Existing PDF/ND-PDF/EPUB/DOCX production must not be deleted merely because Affinity can export some of those formats.

A renderer may be retired only after controlled same-source comparison demonstrates equal or better:

- structural fidelity;
- accessibility;
- navigation;
- deterministic/reproducible behaviour;
- metadata;
- asset handling;
- production quality;
- validation;
- operational reliability.

## 14. Anti-drift and provenance

Every accepted production candidate must bind, as applicable:

- canonical source identity;
- Book Input Contract version;
- resolved design-profile identity;
- user choices;
- calculated geometry;
- template/Affinity-profile identity;
- assets;
- renderer identity/version;
- output artifact hashes;
- human acceptance evidence.

Meaningful changes to trim, font, type size, leading, margins, chapter-opening rules, paragraph geometry, page-number placement, Affinity template/profile, or equivalent design authority invalidate earlier visual/print acceptance unless the resulting artifact bytes are demonstrably identical.

No renderer may silently change publishing policy.

## 15. Graphical integration

Advanced graphical integration is a later subsystem.

It may eventually support:

- illustrated chapter openers;
- maps;
- diagrams;
- pull quotes;
- sidebars;
- ornamental systems;
- background textures;
- full-page art;
- spread-aware layouts;
- photographic sections;
- text/image composition;
- bleed;
- magazine/zine-style grids.

Graphics must enhance a semantic publication rather than redefine canonical content behind the engine's back.

Content edits made during graphical finishing must return to canonical source authority rather than creating an untracked divergent manuscript inside Affinity.

## 16. Publication-family extensibility

The architecture should use a generic publication model where practical, with Book as the first mature specialised family.

Examples:

```text
Publication
├── Book
│   ├── front matter
│   ├── parts
│   ├── chapters
│   └── back matter
├── Magazine
│   ├── cover
│   ├── departments
│   ├── features
│   ├── sidebars
│   └── back cover
├── Zine
├── Pamphlet
└── Catalogue
```

Do not generalise so aggressively that Book v0.1 becomes harder to finish. Generic abstractions should be introduced only where they preserve the already-agreed future direction without speculative complexity.

## 17. Technology direction

Keep the implementation stack small:

- **Python** — authoritative application logic, contracts, feasibility, design-profile resolution, provenance and validation;
- **Markdown** — canonical publication content;
- **HTML/CSS** — guided UI and digital presentation;
- **JavaScript** — bounded interactive UI and Affinity scripting/bridge where justified;
- **Lua/Pandoc** — bounded semantic transformations where still useful;
- **LaTeX/XeLaTeX** — existing deterministic text-led PDF path until a replacement is proven;
- **JSON/YAML** — machine configuration/evidence where appropriate, not a second author-facing manuscript language.

Do not introduce additional backend languages without a demonstrated problem the existing stack cannot solve.

## 18. Human acceptance

Machine validity is not aesthetic acceptance.

The system should eventually produce proof packs targeting:

- title/front matter;
- representative recto/verso spreads;
- first and later chapter openings;
- shortest/longest chapters;
- dense pages;
- images/tables;
- blank-page behaviour;
- back matter;
- output hashes.

Human visual and, where required, physical proof remains an explicit gate bound to exact artifacts.

## 19. Implementation order

The next bounded programme is:

1. freeze this direction;
2. specify Book Input Contract v0.1;
3. build guided Book Input UI v0.1;
4. specify explanation-first choice behaviour;
5. define Book Design Profile v0.1;
6. build evidence-backed design knowledge/rules;
7. build Publication Feasibility Engine v0.1;
8. implement bookmaking mechanics in the resolved profile;
9. prove current renderer implementation against real books;
10. run a bounded Affinity SDK feasibility spike;
11. build Affinity bridge only for demonstrated supported operations;
12. compare Affinity PDF/EPUB with current accepted routes before retiring any renderer;
13. add imposition as a separate later layer;
14. add advanced graphical integration only after text-led composition is stable;
15. expand into additional publication families only through real acceptance cases.

## 20. Acceptance doctrine

Development should remain evidence-driven:

```text
contract
-> implementation
-> real publication
-> independent inspection
-> demonstrated defect
-> smallest repair
-> regression
-> exact-source evidence
-> human proof where required
-> freeze
```

Do not attempt to catalogue every possible publishing convention in advance.

Use real publications to expose real missing rules.

## 21. Initial acceptance cases

The v0.1 composition system should be proven against deliberately different real cases, including:

- a straightforward prose novel;
- a literary/gothic novel;
- narrative non-fiction;
- referenced/research-heavy non-fiction;
- poetry;
- an A6/A7 short publication;
- later, a graphically rich publication through Affinity.

Each new capability must be traceable to a real demonstrated requirement or an explicit foundational contract requirement.

## 22. Non-goals for the first implementation

The first implementation should not attempt to deliver:

- a complete InDesign/Affinity replacement;
- arbitrary page-coordinate editing in the BOS web UI;
- sophisticated magazine/grid composition before the Affinity bridge is proven;
- automated cover design;
- printer imposition before canonical page composition is stable;
- every possible genre template;
- every possible trim size;
- automatic aesthetic judgement;
- removal of the current four-format path before replacement evidence exists.

## Final principle

The long-term system should be able to answer three questions before it makes a publication:

1. **What is this publication?**
2. **Is the requested physical/digital object feasible and appropriate?**
3. **Why is it being designed this way?**

Only then should a renderer make the artifact.
