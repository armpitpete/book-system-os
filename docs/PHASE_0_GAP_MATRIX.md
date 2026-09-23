# Phase 0 — Publication Composition Gap Matrix

This matrix maps the accepted current system to the frozen future direction. It is a planning boundary, not a completion claim.

| Area | Current state | Future state | Action | Phase |
|---|---|---|---|---|
| Publication abstraction | book-specific engine | generic Publication with Book first | new contract | 1 |
| Canonical semantics | Markdown + current structural conventions | versioned Book System Markdown | new contract/parser | 2 |
| Front/body/back matter | incomplete/implicit | explicit ordered semantic components | new contract | 2 |
| Author input | manuscript/dashboard forms | guided publication builder | build | 3 |
| User design choices | limited | explanation-first recommended choices | build | 4 |
| Classification | no unified type/genre/design/accessibility model | explicit independent dimensions | new model | 5 |
| Design knowledge | hidden/distributed | evidence-backed rules with rationale | extract/build | 6 |
| Feasibility | no physical publication capacity gate | PASS/CAUTION/REJECT | new engine | 7 |
| Trim/geometry | hard-coded renderer/template decisions | resolved physical geometry | refactor/build | 8-9 |
| Typography | template-owned | design-profile authority | refactor | 8-9 |
| Chapter/part mechanics | renderer assumptions | explicit mechanics contract | build | 10 |
| Recto/verso/blanks | not comprehensive | explicit semantic rules | build | 10 |
| Folios/running heads | not full semantic authority | profile-driven | build | 10 |
| TOC | Pandoc command/template | semantic + profile-driven | refactor | 10 |
| Notes/references | renderer capability | semantic/profile contract | build | 10 |
| Image holders | implemented controlled semantics | migrate into semantic asset model | adapt, preserve compatibility | 2/10 |
| Standard PDF | Pandoc/XeLaTeX | Affinity-composed output | replace after proof | 13-16 |
| ND PDF | separate LaTeX template | accessibility design profile through Affinity | replace after proof | 13-16 |
| EPUB | Pandoc | Affinity/export route if accepted | replace after proof | 16 |
| DOCX | Pandoc | explicit replacement/interchange path only if still required | decide/prove | 16 |
| Pandoc AST validation | current dependency | BOS-native semantic parser | replace | 2 |
| Lua holder renderer | current dependency | Affinity bridge implementation | replace | 14-16 |
| XeLaTeX | current dependency | Affinity composition | replace | 14-16 |
| Provenance | strong exact-source/artifact system | extend to semantic/design/Affinity identities | evolve | 8/14 |
| Readiness | BOS-RDY-001 | preserve independent state principle | evolve only when required | 17 |
| Human proof | exact artifact gate | targeted proof packs + exact artifact gate | extend | 17 |
| Imposition | excluded | separate downstream subsystem | new | 18 |
| A6/A7 | no dedicated design/feasibility model | first-class small-format cases | build/test | 7-10/18 |
| Graphical composition | bounded image holders only | Affinity advanced composition | later build | 19 |
| Magazines/zines/etc. | outside current model | additional publication families | real-case expansion | 20 |
| Deployment | exact-state protected model | retain | no rewrite without need | ongoing |

## Removal rule

Once the Affinity replacement gate has passed for the duties currently provided by Pandoc/Lua/XeLaTeX, the superseded dependencies, templates, filters, commands and tests are removed in a bounded cleanup.

They are not retained as a second permanent publishing architecture without a demonstrated requirement.
