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

## Installation consequence

Some operating-system package repositories provide Pandoc versions older than 2.15. Installing the package successfully is not enough. If the capability probe fails, install a supported Pandoc build through a separately reviewed system-administration procedure and rerun the compatibility check.

The repository does not silently download or replace production binaries.

## Acceptance evidence

Continuous integration must prove:

- Pandoc 2.9-style `Unknown option --sandbox` behaviour is rejected;
- timeout and invalid-response paths fail closed;
- readiness becomes not-ready when the capability is absent;
- the installed continuous-integration Pandoc performs a real sandboxed validation;
- manuscript validation makes exactly one sandboxed Pandoc call and has no unsandboxed fallback;
- the complete existing test and four-format export suite remains passing.

## Replacement boundary

Pandoc remains an adapter behind Book System OS rather than product authority. If it becomes unsuitable, a replacement must preserve the accepted manuscript contract, deterministic structure model, four output formats, security boundary and regression corpus before it can replace Pandoc in production.
