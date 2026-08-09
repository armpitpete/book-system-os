# Book System OS

Usability-first deterministic publishing and controlled revision service for `publish.toiletrage.co.uk`.

Book System OS has three deliberately separate scope statements:

1. **Historical v0.1 deterministic core** — fixed historical contract, **10/10 gates — 100% complete**.
2. **Current implemented publishing engine** — defined by `docs/CURRENT_PRODUCT_CONTRACT_V1.md`, **12/12 current-engine gates — 100% of that fixed contract**.
3. **Wider Book System OS product** — later product extensions and evidence lanes are tracked separately; no overall completion percentage is authorised.

These percentages are not interchangeable. Completion of a fixed implementation contract does not mean that a real book is publication-ready or print-ready, or that the wider product is complete.

## Historical v0.1 authority

The original v0.1 deterministic publishing core remains governed by:

- `docs/PRODUCT_CONTRACT.md`
- `docs/COMPLETION_CONTRACT.md`
- `docs/RELEASE_ACCEPTANCE.md`
- `docs/completion-authority.json`

Its fixed denominator remains **10 of 10 gates — 100% complete**. Later capabilities do not rewrite that historical claim.

## Current Product Contract v1

The Book System OS that exists now is governed by:

- `docs/CURRENT_PRODUCT_CONTRACT_V1.md`
- `docs/BOS_RDY_001_READINESS_CONTRACT.md`
- `docs/V0_2_VALIDATION_API.md`
- `docs/V0_2_PUBLISH_DRY_RUN_API.md`
- `docs/IMAGE_HOLDERS_V0_1.md`
- `docs/IMAGE_HOLDERS_V0_2.md`
- `docs/AUTHOR_ASSET_WORKSPACE_V0_1.md`

The fixed Current Product Contract v1 denominator is **12/12 current-engine gates**. Capabilities added after that fixed denominator, such as Author Asset Workspace v0.1, keep their own implementation/acceptance evidence rather than turning the denominator into a moving target.

The current architecture keeps these claims separate:

- Story Validation / story readiness;
- production validity;
- digital-publication readiness;
- print readiness;
- human artifact acceptance.

A successful build does not collapse those into one vague `complete` or `ready` state.

## Current implemented journey

```text
Optional Author Asset Workspace
-> upload / inspect image
-> holder suitability + DPI/aspect feedback
-> canonical holder Markdown
-> authenticated manuscript
-> side-effect-free validation
-> side-effect-free publish dry-run
-> optional persistent production submission
-> referenced workspace assets copied into retained job input
-> file-based job queue + background worker
-> conservative structural normalisation
-> validated image-holder rendering when present
-> Pandoc/XeLaTeX export
-> standard PDF + ND PDF + EPUB + DOCX
-> retained provenance, manifests, logs and evidence
-> Revision Studio proposal/review flow when used
-> BOS-RDY-001 exact-source / exact-artifact readiness evaluation
-> explicit human acceptance where the readiness class requires it
```

## Current implemented scope

- FastAPI dashboard and authenticated API
- explicit local-development mode and production fail-closed authentication
- persistent file-based jobs and background worker
- test, production and archived lifecycle states
- job status, logs, event history, retry and controlled cleanup
- conservative non-inventive Markdown normalisation
- authenticated side-effect-free manuscript validation
- authenticated side-effect-free publish dry-run planning
- authenticated Author Asset Workspace v0.1 for JPEG/PNG/WebP upload and preview
- holder suitability, aspect and effective-DPI feedback driven by the production validator
- canonical holder Markdown generation with alt/caption/decorative semantics
- SHA-verified copying of referenced workspace assets into retained job input with provenance
- standard PDF
- ND-readable PDF
- EPUB
- DOCX
- exact source/artifact provenance and output evidence
- BOS-RDY-001 independent readiness states
- Revision Studio document/proposal/decision/history/package workflow
- image-holder validation and controlled v0.2 rendering
- relative local image-resource resolution
- hardened production service, backup/recovery and exact-state release controls
- live current-main and feature-specific production acceptance

## Implemented HTTP routes

- `GET /health`
- `GET /ready`
- `GET /api/v1/status`
- `POST /api/v1/validate`
- `POST /api/v1/publish/dry-run`
- `POST /api/submit`
- `GET /api/jobs/{job_id}`
- `GET /assets`
- `POST /assets`
- `GET /assets/{asset_id}`
- `POST /assets/{asset_id}/configure`
- `GET /assets/{asset_id}/preview`
- Revision Studio API and read-only UI routes reported by `/api/v1/status`

The `/api/v1/status` response is authoritative for the live route inventory. Routes under `not_yet_implemented` are not live behaviour.

In particular, the executable `/api/v1/publish`, publish-status/list and publish-retry gateway routes remain future work. The existing production submission path and the dry-run API must not be confused with those planned routes.

## Readiness authority

`docs/BOS_RDY_001_READINESS_CONTRACT.md` defines four independent states:

- `story-ready`
- `production-valid`
- `digital-publication-ready`
- `print-ready`

Story Validation remains authoritative for narrative validation. Book System OS consumes Story Validation evidence but is authoritative for retained source identity, artifact generation, production validation, asset/configuration identity and publication/readiness evaluation.

Machine tests and four-format generation do **not** substitute for required human inspection of the exact artifact.

## Author Asset Workspace

`GET /assets` is the authenticated author-facing image workflow.

It lets an author upload JPEG, PNG or WebP, preview the source, inspect dimensions/aspect ratio, see effective DPI and compatibility for all five named holders, enter alt/caption/decorative semantics, and receive canonical holder Markdown.

Workspace originals are persistent state under `books/assets`. Runtime contents are Git-ignored, included in persistent backup/restore, protected by release/preflight state invariants, and identified by SHA-256.

When a queued manuscript references a generated `assets/<asset-id>/source.<ext>` path, Book System OS verifies the workspace asset and copies it into the job's retained `input/assets/...` tree. The job records inspectable asset provenance and accounts for the copied bytes before admission.

The workspace does **not** provide freeform page coordinates, unrestricted resizing, floating text/images, destructive automatic crops, cover/spine/bleed design or printer-specific DTP controls.

## Image holders

The canonical internal representation remains controlled holder metadata in Markdown. Supported holders are:

- Inline
- Feature
- Portrait
- Full page
- Ornament

The renderer owns bounded layout geometry across both PDFs, DOCX and EPUB and sanitises author-supplied positioning/size controls that would bypass the holder contract.

The Author Asset Workspace reuses the same holder validator for its suitability feedback. It does not maintain a separate looser rule set.

Arbitrary page coordinates, free-floating desktop-publishing controls, unrestricted resizing and destructive automatic raster cropping are intentionally excluded.

## Current production baseline

Image-holder rendering v0.2 was accepted in production on 2026-08-09 at:

```text
34a470546770dd4c4d211966e2f5660f36cbc22a
```

That production acceptance proved the exact deployment target, current-main live acceptance, four-format image-holder rendering, relative resource resolution, author-positioning sanitisation, stable API/worker state and unchanged retained job/Revision Studio state while retaining:

```text
actual_book_readiness_claimed=false
```

Later merged implementation is not automatically deployed. Production remains at the last exact live-accepted target until another exact predecessor -> target deployment is separately authorised and accepted.

This is a production-engine acceptance statement, not a claim that a substantial real book has passed human publication/print acceptance.

## Future priority

Book System OS remains a stronger **publishing engine** than **author-facing product**. Repository-owned production preflight and Author Asset Workspace v0.1 close two previously identified gaps; the next evidence lanes are:

1. substantial real-book acceptance with genuine human artifact inspection;
2. Paid External Book Production Proof (#71).

Billing, SaaS infrastructure and a wider public gateway remain deferred until external production evidence justifies them.

## Server target

```text
/opt/book-system
```

## Install

Clone the repository to `/opt/book-system`, then run:

```bash
cd /opt/book-system
sudo bash scripts/install.sh
```

## Environment

Create the runtime configuration:

```bash
cp config/env.example config/env
```

Production requires all three authentication values:

```text
BOOK_SYSTEM_ENV=production
BOOK_API_KEY=replace-with-a-long-random-secret
BOOK_ADMIN_USERNAME=replace-with-an-admin-name
BOOK_ADMIN_PASSWORD=replace-with-a-long-random-password
```

Production fails closed if the API key or dashboard credentials are missing or incomplete.

For intentional unauthenticated local development only:

```text
BOOK_SYSTEM_ENV=local
```

Do not expose local mode publicly.

## Services

```bash
sudo cp deploy/systemd/book-system-api.service /etc/systemd/system/book-system-api.service
sudo cp deploy/systemd/book-system-worker.service /etc/systemd/system/book-system-worker.service
sudo systemctl daemon-reload
sudo systemctl enable --now book-system-api.service book-system-worker.service
```

## Apache reverse proxy

Review and install the committed example:

```bash
sudo cp deploy/apache/publish.toiletrage.co.uk.conf /etc/apache2/sites-available/publish.toiletrage.co.uk.conf
sudo a2enmod proxy proxy_http headers ssl
sudo a2ensite publish.toiletrage.co.uk.conf
sudo apachectl configtest
sudo systemctl reload apache2
```

TLS certificate paths in the example must be replaced with the server's real certificate paths.

## Protected production release

Production release is an exact-state operation, not an instruction to pull whatever is newest.

Before deployment authorisation, run the repository-owned read-only preflight from a clean candidate worktree at the exact target:

```text
scripts/production_current_main_preflight.sh
```

It requires exact full-SHA `--expected-before` and `--target-commit` arguments, generates protected evidence, verifies the Author Asset Workspace persistent-state invariant/capacity where present, and always leaves `deployment-authorized=false`. See `docs/PRODUCTION_CURRENT_MAIN_PREFLIGHT.md` for its complete evidence and non-mutation contract.

After a successful preflight and separate explicit authorisation for that exact SHA pair, the protected release wrapper is:

```text
scripts/production_current_main_release.sh
```

The release wrapper is also run from a clean detached worktree at the exact reviewed target and requires:

- `--expected-before`
- `--target-commit`
- `--confirm "DEPLOY <target>"`

Do not silently substitute another predecessor or target. Preflight, authorisation, deployment, live acceptance and human artifact acceptance remain separate gates.

## Local checks

```bash
python3 scripts/check_env.py
python3 -m compileall app scripts tests
python3 -m pytest -q
```

The real export integration test requires `pandoc` and `xelatex`. CI installs both and must generate non-empty standard PDF, ND PDF, EPUB and DOCX outputs.

## Operator guidance

See `docs/PRODUCTION_CURRENT_MAIN_PREFLIGHT.md` for protected preflight/release entrypoints, `docs/AUTHOR_ASSET_WORKSPACE_V0_1.md` for the author image workflow, and `docs/operator-admin-manual.md` for job retry, cleanup, recovery, resource limits and general service checks.

<!-- AUTO:PROJECT-COMPLETION:START -->
## Completion

_Generated from validated project authority by `project-status-engine`. Repository activity is not completion._

| Stage | Progress |
|---|---:|
| v0.1 deterministic publishing core | `10/10` — **100.0%** |

Authority: `README.md`

Overall completion is not enabled for this project.
<!-- AUTO:PROJECT-COMPLETION:END -->