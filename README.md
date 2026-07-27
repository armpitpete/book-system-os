# Book System OS

Usability-first publishing service for `publish.toiletrage.co.uk`.

The v0.1 product is a deterministic publishing core:

```text
Authenticated dashboard/API
-> file-based job queue
-> background worker
-> conservative Markdown normalisation
-> Pandoc/XeLaTeX export
-> downloadable outputs
```

AI Semantic Architect mode is intentionally excluded. The wider Book System OS remains incomplete and has no authoritative percentage.

## Completion authority

The fixed v0.1 scope and completion rules are defined in:

- `docs/PRODUCT_CONTRACT.md`
- `docs/COMPLETION_CONTRACT.md`
- `docs/RELEASE_ACCEPTANCE.md`
- `docs/completion-authority.json`

The fixed v0.1 deterministic publishing core is **10 of 10 gates — 100% complete**. PR #27 passed exact-head CI run #47 and merged as `a4589d7e99223cf8a875f372136f09b057de1ddf`. The pre-stabilisation baseline was 7 of 10 gates — 70%.

Completion of the v0.1 core does not mean that the planned publish gateway, print-production system or Semantic Architect is complete.

## Current implemented scope

- FastAPI dashboard
- Markdown submission form
- explicit test/production selection for dashboard jobs
- production-classified API submissions
- file-based persistent jobs
- background worker with lock files
- conservative structural normalisation
- standard PDF
- ND-readable PDF
- EPUB
- DOCX
- authenticated output download links
- readable log viewer
- lifecycle state: test, production, archived
- retry count and event history
- failed-job retry
- preview-before-archive cleanup for old test jobs
- systemd service files
- Apache reverse-proxy example
- safe deploy script
- unit/API tests and real four-format export test
- authenticated side-effect-free manuscript validation

## Implemented HTTP routes

- `GET /health`
- `GET /ready`
- `GET /api/v1/status`
- `POST /api/v1/validate`
- `POST /api/submit`
- `GET /api/jobs/{job_id}`

The `/api/v1/status` response also lists planned routes. Routes under `not_yet_implemented` are not live behaviour.

The v0.2 validation request, response, findings and failure behaviour are documented in `docs/V0_2_VALIDATION_API.md`.

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

## Safe deployment

```bash
sudo /opt/book-system/scripts/deploy_server.sh
```

The script pulls `main` with fast-forward only, compiles the application, restarts both services, waits for local readiness and then checks the public health endpoint.

## Local checks

```bash
python3 scripts/check_env.py
python3 -m compileall app scripts tests
python3 -m pytest -q
```

The real export integration test requires `pandoc` and `xelatex`. CI installs both and must generate non-empty standard PDF, ND PDF, EPUB and DOCX outputs.

## Operator manual

See `docs/operator-admin-manual.md` for deployment, retry, cleanup and stop rules.

<!-- AUTO:PROJECT-COMPLETION:START -->
## Completion

_Generated from validated project authority by `project-status-engine`. Repository activity is not completion._

| Stage | Progress |
|---|---:|
| v0.1 deterministic publishing core | `10/10` — **100.0%** |

Authority: `README.md`

Overall completion is not enabled for this project.
<!-- AUTO:PROJECT-COMPLETION:END -->
