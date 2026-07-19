# Book System OS v0.1 completion contract

## Scope authority

This contract measures only the stable deterministic publishing core defined in `docs/PRODUCT_CONTRACT.md`.

The denominator is fixed at ten principal gates. Each gate is worth 10 percentage points. A gate scores either 0 or 10; partial implementation does not score.

Later features cannot be added to this denominator without a reviewed contract revision.

## Principal gates

| Gate | Requirement | Evidence required | Main baseline before stabilisation |
|---|---|---|---:|
| C-01 | Dashboard and API accept Markdown submissions and create persistent jobs | automated submission tests and repository code | 10 |
| C-02 | Background worker safely claims and processes queued jobs | worker code and locking regression test | 10 |
| C-03 | Structural stage is deterministic and non-semantic | unit test proving exact allowed normalisation | 10 |
| C-04 | Successful jobs produce standard PDF, ND PDF, EPUB and DOCX | real Pandoc/XeLaTeX integration test | 10 |
| C-05 | Outputs are authenticated and path-contained | API/download tests | 10 |
| C-06 | Dashboard exposes status, logs, lifecycle state and history | API/UI tests and repository code | 10 |
| C-07 | Retry and conservative old-test cleanup are operational | retry and cleanup regression tests | 10 |
| C-08 | Runtime configuration, authentication, version and deployment documentation agree and production fails closed | configuration/auth/version/deploy tests and reviewed assets | 0 |
| C-09 | Dashboard submissions explicitly select test or production, defaulting to test; API submissions remain production | regression tests closing issue #24 | 0 |
| C-10 | CI runs unit/API tests and a real four-format export build; successful manifests record final `done` state | passing exact-head GitHub Actions run | 0 |

## Authoritative baseline

Before the stabilisation PR, the fixed v0.1 core is:

```text
7 of 10 gates complete — 70%
```

This baseline does not change when later products are proposed.

## Promotion rule

The v0.1 stable deterministic publishing core becomes:

```text
10 of 10 gates complete — 100%
```

only when all of the following are true:

1. the stabilisation PR is reviewed and merged;
2. the exact PR head passes the complete CI workflow;
3. issue #24 is closed by that PR;
4. no acceptance criterion in `docs/RELEASE_ACCEPTANCE.md` is waived;
5. the merged README records the stable-core status without claiming the full Book System OS is complete.

## Full-system status

The wider aspirational Book System OS has no authoritative percentage in this repository. It includes later gateway, print-production and semantic architecture work that has not yet been contracted into a fixed completion denominator.

Report it as:

```text
Full Book System OS: not baselined; incomplete.
```

Do not derive or infer a full-system percentage from this v0.1 core contract.