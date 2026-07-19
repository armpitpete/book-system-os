# Book System OS product contract

## Authority

This document fixes the scope of the **Book System OS v0.1 stable deterministic publishing core**.

It prevents later ideas from silently expanding the completion denominator. Changes to this scope require a separately reviewed contract change.

## Product purpose

The v0.1 core accepts a Markdown manuscript, records it as a persistent job, processes it without inventing or rewriting meaning, and produces downloadable book files through a recoverable operator-facing service.

## Required user journey

```text
Authenticated dashboard or API submission
-> persistent job record
-> background worker
-> conservative structural normalisation
-> Pandoc/XeLaTeX export
-> standard PDF, ND-readable PDF, EPUB and DOCX
-> status, logs and downloadable outputs
```

## Required operator capabilities

The stable core must provide:

1. authenticated dashboard access in production;
2. authenticated API submission in production;
3. explicit local-development mode for intentionally unauthenticated use;
4. test and production selection for dashboard submissions;
5. production classification for API submissions;
6. job lifecycle classification: test, production and archived;
7. readable job status, logs, outputs and event history;
8. failed-job retry using the preserved source manuscript;
9. conservative preview-before-archive cleanup for old test jobs;
10. a safe deployment procedure with local and public health checks;
11. one authoritative application version;
12. automated unit/API regression tests;
13. a real Pandoc/XeLaTeX export test covering all four output formats;
14. a final manifest whose recorded status is `done` for a successful build.

## Non-invention rule

The v0.1 core may normalise line endings, trailing whitespace and excessive blank lines. It must not invent, rewrite, summarise or semantically alter manuscript content.

## Fixed exclusions

The following are **not part of v0.1 core completion**:

- the planned `/api/v1/validate` and `/api/v1/publish*` gateway routes;
- printer-specific imposition, cover, spine, bleed or colour workflows;
- publication release approval and physical proof handling;
- AI Semantic Architect behaviour;
- editorial rewriting or content generation;
- multi-user accounts, billing or public SaaS operation;
- distributed workers or database-backed orchestration.

These exclusions may become later products or milestones, but they do not reduce the completion percentage of the fixed v0.1 core.

## Completion boundary

The v0.1 stable deterministic publishing core is complete only when every gate in `docs/COMPLETION_CONTRACT.md` is verified at the exact merged commit.

Completion of this contract does **not** mean that the full aspirational Book System OS is complete.