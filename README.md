# Book System OS

Usability-first publishing dashboard for `publish.toiletrage.co.uk`.

This starter system is deliberately limited to the core loop:

```text
Dashboard/API -> file-based job queue -> worker -> Pandoc export -> downloadable outputs
```

AI Semantic Architect mode is intentionally not included yet. Add it only after the button-to-output loop is confirmed working.

## Current scope

- FastAPI dashboard
- Markdown submission form
- file-based persistent jobs
- background worker
- Pandoc exports
- standard PDF
- ND-readable PDF
- EPUB
- DOCX
- output download links
- log viewer
- systemd service files
- Apache reverse proxy example for `publish.toiletrage.co.uk`

## Server target

```text
/opt/book-system
```

## Install

```bash
sudo bash scripts/install.sh
```

## Services

```bash
sudo cp deploy/systemd/book-api.service /etc/systemd/system/book-api.service
sudo cp deploy/systemd/book-worker.service /etc/systemd/system/book-worker.service
sudo systemctl daemon-reload
sudo systemctl enable --now book-api book-worker
```

## Local/dev check

```bash
python3 scripts/check_env.py
python3 -m compileall app scripts
```

## Environment

Copy:

```bash
cp config/env.example config/env
```

Set:

```text
BOOK_SYSTEM_ADMIN_TOKEN=change-me
BOOK_SYSTEM_API_KEY=change-me
BOOK_SYSTEM_REQUIRE_AUTH=false
```

For first private testing you can leave auth off. Turn it on before exposing the dashboard publicly.
