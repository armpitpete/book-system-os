# Administrative security and credential rotation

This document defines H-06 protection for the current authenticated, single-operator Book System OS service.

It does not add user accounts, OAuth, a database, billing, public SaaS authentication or v0.2 routes.

## Security boundary

The current service keeps its accepted authentication methods:

- HTTP Basic Auth for the dashboard;
- `X-API-Key` for programmatic API routes.

Production remains fail-closed when either credential set is missing, incomplete or still uses a placeholder value.

H-06 adds:

- CSRF protection for dashboard mutations;
- protected-request rate limiting;
- failed-authentication rate limiting;
- the existing H-04 request-body limit before form or JSON parsing;
- a sanitised administrative/security event log;
- a controlled credential-rotation procedure.

H-07 remains responsible for consolidating dashboard routes and templates.

## Production configuration

Recommended single-operator defaults:

```text
BOOK_SECURITY_CSRF_ENABLED=true
BOOK_SECURITY_RATE_LIMIT_ENABLED=true
BOOK_SECURITY_AUDIT_ENABLED=true
BOOK_SECURITY_REQUEST_LIMIT=120
BOOK_SECURITY_REQUEST_WINDOW_SECONDS=60
BOOK_SECURITY_AUTH_FAILURE_LIMIT=5
BOOK_SECURITY_AUTH_FAILURE_WINDOW_SECONDS=300
BOOK_SECURITY_CSRF_COOKIE_SECONDS=28800
BOOK_SECURITY_RATE_LIMIT_MAX_KEYS=2048
```

The protected-request limit allows 120 non-health requests per client address in 60 seconds.

The failed-authentication limit blocks the fifth failed Basic Auth or API-key attempt for the rest of a five-minute sliding window. A successful authentication clears that authentication-failure bucket.

Limiter state is deliberately process-local and bounded to 2,048 client keys by default. Restarting the API clears the process-local windows. This is proportionate for the accepted single-server, single-operator service; it is not a distributed rate-limit product.

Invalid security configuration returns HTTP 503 on protected routes. Health and readiness operation must still be checked independently after deployment.

## Client address handling

The limiter uses the direct peer address.

When the direct peer is loopback, as with the local reverse proxy, the first syntactically valid address in `X-Forwarded-For` is used. Forwarded client addresses are not trusted from a non-loopback peer.

This prevents an internet client from choosing an arbitrary rate-limit identity while preserving individual client tracking behind the accepted local proxy.

## CSRF protection

Dashboard pages receive a random `book_csrf` cookie with:

- `HttpOnly`;
- `SameSite=Strict`;
- `Secure` in production;
- path `/`;
- an eight-hour default lifetime.

The same token is inserted into every POST form as:

```html
<input type="hidden" name="csrf_token" value="...">
```

A dashboard mutation is refused with HTTP 403 when:

- the CSRF cookie is missing;
- the submitted token is missing;
- the submitted token is malformed;
- the submitted token does not match the cookie;
- an `Origin` or `Referer` header identifies another host.

The programmatic API does not use CSRF because browsers do not attach the custom API-key header automatically. API routes remain protected by API-key authentication, request limits and H-04 body limits.

Local, development and test modes default CSRF, rate limiting and security audit logging off so existing direct unit tests and offline development remain usable. Focused security tests enable each control explicitly. Production defaults all three controls on.

## Request-body enforcement

`BOOK_MAX_REQUEST_BYTES` remains the authoritative H-04 maximum request body.

The request-body middleware stays outside the H-06 security middleware. An oversized POST is therefore refused before:

- form parsing;
- JSON parsing;
- CSRF inspection;
- authentication work that depends on the body;
- job-directory creation.

Do not duplicate or weaken this limit inside dashboard routes.

## Administrative and security audit log

H-06 writes:

```text
/opt/book-system/logs/security-events.jsonl
```

The file is created mode `0600`. Each line is a bounded JSON object containing:

- UTC creation time;
- event name;
- outcome;
- request method;
- request path;
- validated client address;
- an allowlisted details object.

Recorded security events include:

- failed Basic Auth and API-key authentication;
- authentication rate-limit refusal;
- protected-request rate-limit refusal;
- CSRF refusal;
- authorised dashboard submission;
- authorised lifecycle-state change;
- authorised retry;
- cleanup preview and archive authorisation.

The log does not accept arbitrary detail fields. It must never contain:

- a password;
- API key;
- Authorization header;
- cookie;
- CSRF token;
- manuscript content;
- book title;
- other request-body text.

Dashboard mutation authorisation is recorded before the mutation runs. If the security log is unavailable, the mutation returns HTTP 503 and does not proceed.

## Job-local audit history

Job creation, state, retry, cleanup and interrupted-job recovery also retain job-local evidence.

H-02 recovery records the operator identity, concrete reason, previous state, target state and recovery count in `status.json` and `events.jsonl`. Those records remain the authoritative job-specific recovery trail. H-06 does not remove or replace them.

Production recovery must still use:

```bash
python scripts/recover_jobs.py preview
python scripts/recover_jobs.py recover JOB_ID --to queued --operator NAME --reason "CONCRETE REASON"
```

Never edit recovery status or lock files manually.

## Operator checks

Inspect current service state:

```bash
systemctl is-active book-system-api.service
systemctl is-active book-system-worker.service
curl -i http://127.0.0.1:8080/health
curl -i http://127.0.0.1:8080/ready
```

Inspect recent security events without printing configured credentials:

```bash
stat -c '%a %U:%G %n' /opt/book-system/logs/security-events.jsonl
tail -n 50 /opt/book-system/logs/security-events.jsonl | python -m json.tool --json-lines
```

A normal administrative action should create one authorisation record with a recognised event name and no secret or manuscript value.

## Credential generation

Generate independent values. Do not reuse one secret for the dashboard and API.

Example commands:

```bash
ADMIN_PASSWORD="$(openssl rand -base64 36 | tr -d '\n')"
API_KEY="$(openssl rand -hex 32)"
```

Do not paste generated values into issue comments, pull requests, shell history, screenshots or acceptance output.

## Controlled credential rotation

Live credential rotation is a protected production action. It requires explicit owner authority and a maintenance window.

### 1. Capture non-secret preconditions

Confirm:

```bash
cd /opt/book-system
git status --short
git rev-parse HEAD
stat -c '%a %U:%G %n' config/env
sha256sum config/env
systemctl is-active book-system-api.service
systemctl is-active book-system-worker.service
curl -fsS http://127.0.0.1:8080/health
curl -fsS http://127.0.0.1:8080/ready
```

Do not print `config/env`.

### 2. Prepare a mode-0600 replacement

Copy the current file into a root-only temporary path, edit only the authorised credential fields, and preserve every non-credential value.

Credential fields are:

```text
BOOK_ADMIN_USERNAME
BOOK_ADMIN_PASSWORD
BOOK_API_KEY
```

The username may remain unchanged when rotating only secrets.

### 3. Validate without printing values

Validate that:

- each credential is configured;
- no value begins with a placeholder prefix;
- the new dashboard password differs from the previous password;
- the new API key differs from the previous API key;
- the temporary file remains mode `0600`;
- unrelated configuration keys and values are unchanged.

Compare secret values only inside a non-echoing script. Report hashes or boolean results, never the values.

### 4. Replace atomically

Stop the API briefly, atomically replace `config/env`, restore owner and mode, then restart both services:

```bash
systemctl stop book-system-api.service
install -o root -g root -m 0600 NEW_ENV config/env.new
mv -f config/env.new config/env
systemctl restart book-system-api.service
systemctl restart book-system-worker.service
```

The exact production acceptance script must provide the real temporary path and verify the complete file before replacement.

### 5. Verify old and new credentials

Without printing either secret:

- old dashboard credentials must return HTTP 401;
- new dashboard credentials must load the dashboard;
- old API key must return HTTP 403;
- new API key must access an authenticated API route;
- a dashboard GET must issue a CSRF cookie and hidden token;
- a dashboard mutation with the new credentials and valid CSRF token must succeed;
- the corresponding audit record must exist;
- local and public health/readiness must pass.

### 6. Preserve rollback authority

Retain the previous mode-0600 environment file only in a root-only, time-bounded rollback location during the acceptance window. Delete that rollback copy only after the new credentials and service state are accepted.

Do not commit either environment file.

## Stop rules

Stop and investigate when:

- a protected route works with placeholder or incomplete credentials;
- a dashboard mutation works without a valid CSRF token;
- a cross-site Origin or Referer is accepted;
- repeated failed authentication never reaches HTTP 429;
- legitimate access does not recover after the configured window;
- an oversized request creates or changes a job;
- a mutation proceeds while the security audit log is unavailable;
- the security log contains a credential, token, cookie, manuscript fragment or title;
- the audit file is not mode `0600`;
- old credentials remain valid after an authorised rotation;
- new credentials fail after rotation;
- health or readiness fails after rotation.
