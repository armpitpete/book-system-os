# Book System OS v0.1 release acceptance

## Release candidate

This checklist applies to the exact head of the stabilisation pull request and then to the resulting merge commit.

## Automated acceptance

All checks must pass without waiver:

- Python compilation succeeds for `app`, `scripts` and `tests`.
- Unit and API tests pass.
- Production dashboard access fails closed when credentials are absent.
- Production API submission fails closed when the API key is absent.
- Explicit local mode permits intentionally unauthenticated development access.
- Dashboard Basic Auth accepts configured credentials and rejects missing or incorrect credentials.
- API key authentication accepts the configured key and rejects missing or incorrect keys.
- Dashboard submissions default to `test`.
- Dashboard submissions may explicitly use `production`.
- Invalid dashboard lifecycle submissions return a controlled client error.
- API submissions remain `production`.
- The dashboard and `/api/v1/status` report the same version.
- Successful builds generate non-empty standard PDF, ND PDF, EPUB and DOCX files.
- A successful build manifest records status `done` and step `complete`.
- Output path traversal is rejected.
- Retry preserves source input and records retry history.
- Cleanup never archives production, queued or running jobs.

## Repository acceptance

- README environment variables exactly match the application.
- README service names exactly match the committed systemd units and deploy script.
- Both systemd unit files are committed.
- The Apache reverse-proxy example is committed.
- `config/env.example` defaults to production mode and contains no usable secret.
- `docs/PRODUCT_CONTRACT.md` and `docs/COMPLETION_CONTRACT.md` are present.
- No planned `/api/v1/publish*` route is represented as implemented.
- No AI or Semantic Architect feature is added.

## Review stop conditions

Do not promote or merge if:

- any automated check is skipped unexpectedly;
- the real export test does not run in CI;
- production can become unauthenticated merely because a secret is absent;
- dashboard submissions still silently default to production;
- the manifest records a pre-completion status;
- deployment files or documentation disagree;
- the diff adds work outside the fixed stabilisation scope.

## Completion statement after acceptance

After exact-head checks pass and the PR is merged, the allowed statement is:

> Book System OS v0.1 is a stable deterministic publishing core. The wider Book System OS remains incomplete and is not yet baselined.