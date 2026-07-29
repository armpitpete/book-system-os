# V0.2 production toolchain compatibility

## Authority

This correction supports the first v0.2 capability:

```text
POST /api/v1/validate
```

It does not authorise a publish route, print-production work or Semantic Architect behaviour.

## Pandoc requirement

The documented minimum Pandoc version is:

```text
2.15
```

Pandoc 2.15 introduced the `--sandbox` option used by manuscript validation. Version text is not accepted as operational proof. Installation, readiness, deployment and continuous integration must run the shared bounded capability probe and accept Pandoc only when the executable successfully parses fixed Markdown into a Pandoc JSON abstract syntax tree with:

```text
pandoc --sandbox --from=markdown+yaml_metadata_block --to=json
```

The probe:

- uses fixed non-user input;
- supplies input through standard input;
- captures bounded output;
- has a hard maximum timeout;
- requires a valid document-shaped JSON response;
- fails closed if Pandoc is absent, incompatible, times out, exits unsuccessfully or returns invalid JSON.

## No fallback

Book System OS must not retry manuscript validation without `--sandbox`.

An incompatible Pandoc therefore causes:

- installation to stop;
- `/ready` to return not-ready;
- exact deployment to stop before the service is accepted as ready;
- manuscript validation to retain its controlled HTTP 503 tool failure.

This is preferable to processing an untrusted manuscript with a weakened command.

## Production metadata readability

The dashboard commit label is part of deployment evidence. Exact deployment therefore:

1. confirms the checked-out commit;
2. makes only `.git/HEAD` readable as mode `0644` while preserving root ownership;
3. verifies the relevant Git metadata is not group/world writable;
4. verifies the `www-data` service account can resolve the expected short commit;
5. leaves Git metadata non-writable by the service account.

No repository ref is made writable by `www-data`.

## Exact production release

The reviewed production and continuous-integration release is:

```text
Pandoc 3.9.0.2
```

Official Linux release archives are pinned by architecture:

```text
amd64  a69abfababda8a56969a254b09f9553a7be89ddec00d4e0fe9fd585d71a67508
arm64  b6d21e8f9c3b15744f5a7ab40248019157ed7793875dbe0383d4c82ff572b528
```

`scripts/install_pinned_pandoc.sh`:

- accepts only the reviewed amd64 or arm64 asset;
- downloads from the official `jgm/pandoc` GitHub release;
- requires HTTPS and verifies the full SHA-256 digest before extraction;
- verifies the reported release and functional sandbox behaviour;
- installs into a versioned external runtime directory;
- refuses to overwrite a differing existing version directory; and
- atomically updates the `current` runtime link.

The service units use the explicit runtime path:

```text
/opt/book-system-runtime/pandoc/current/bin
```

The operating-system Pandoc package is no longer accepted as the production authority.

## Production acceptance operation

`scripts/production_v2_01_acceptance.sh` is the single reviewed operation for the production upgrade and V2-01 acceptance gate. It requires:

- root execution;
- an explicit `--execute` flag;
- a full accepted commit;
- `origin/main` at that exact commit;
- a clean production checkout;
- a running launcher whose digest matches the launcher stored at the exact commit; and
- protected production configuration.

It then installs the pinned runtime, proves compatibility as `root` and `www-data`, invokes the existing exact guarded deployment, runs authenticated live validation, runs a temporary four-format export proof and verifies that retained book storage is byte-for-byte unchanged.

Merge and production execution remain separate owner-authority actions.

## Acceptance evidence

Continuous integration must prove:

- Pandoc 2.9-style `Unknown option --sandbox` behaviour is rejected;
- timeout and invalid-response paths fail closed;
- readiness becomes not-ready when the capability is absent;
- the exact pinned continuous-integration Pandoc performs a real sandboxed validation;
- manuscript validation makes exactly one sandboxed Pandoc call and has no unsandboxed fallback;
- the complete existing test and four-format export suite remains passing;
- the production launcher requires exact-candidate and explicit-execution guards;
- the live acceptance helper verifies missing and wrong authentication;
- valid and invalid manuscripts return the accepted results; and
- temporary acceptance work cannot alter retained book storage.

## Replacement boundary

Pandoc remains an adapter behind Book System OS rather than product authority. If it becomes unsuitable, a replacement must preserve the accepted manuscript contract, deterministic structure model, four output formats, security boundary and regression corpus before it can replace Pandoc in production.
