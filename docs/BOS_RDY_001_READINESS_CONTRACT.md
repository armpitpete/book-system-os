# BOS-RDY-001 — Readiness Claims

## Authority

Book System OS must never label an output `publication-ready` or `print-ready`
unless both the exact manuscript has the required Story Validation state and
the generated artifact itself has passed Book System OS production validation
and required human acceptance.

This is the machine-enforceable implementation contract for that rule. It does
not alter the historical v0.1 completion denominator.

## Boundary

Story Validation remains authoritative for narrative validation. Book System OS
consumes Story Validation evidence but does not duplicate its narrative rules.
Book System OS remains authoritative for retained source identity, generated
artifact identity, production validation and publication/print readiness claims.

Operational service readiness (`/ready`) is separate from book readiness.

## Authoritative evaluator

`app.services.artifact_readiness.evaluate_readiness` is the BOS-RDY-001
readiness evaluator.

The evaluator does **not** accept caller-supplied artifact, production-config or
asset digests as current truth. For a retained job and requested artifact type it:

1. verifies the retained manuscript through the existing provenance authority;
2. resolves the artifact from the authoritative publish-output contract;
3. hashes the actual retained output file;
4. verifies those bytes against the pipeline derivation manifest;
5. derives the current production-configuration identity from the real export
   command, applicable template bytes and structural-transformation contract;
6. derives the current asset identity from retained job input assets plus exact
   referenced local image bytes;
7. compares those independently derived identities with Story Validation,
   production-validation and human-acceptance evidence.

This prevents a matching set of supplied hash strings from substituting for the
real manuscript, artifact, configuration or assets.

Story readiness remains independent. A missing or stale artifact may make
production/publication states false without erasing a still-current
`story-ready` result.

## Independent states

The evaluator returns four independent states:

- `story-ready`
- `production-valid`
- `digital-publication-ready`
- `print-ready`

Passing one state never silently implies another.

`digital-publication-ready` and `print-ready` require all three of:

1. current Story Validation evidence for the exact manuscript SHA-256;
2. production validation for the exact artifact bytes, source manuscript,
   production configuration, relevant assets and applicable profile;
3. required human acceptance for the exact artifact SHA-256 and readiness class.

## Artifact contract v1

Supported artifact/readiness combinations are explicit and versioned as
`artifact_contract_version: "1"`.

| Artifact type | production-valid | digital-publication-ready | print-ready |
|---|---:|---:|---:|
| `pdf_standard` | yes | yes | yes |
| `pdf_nd` | yes | yes | yes |
| `epub` | yes | yes | no |
| `docx` | yes | no | no |

Artifact types are the authoritative output keys, not generic media labels. An
EPUB can therefore never become `print-ready` merely because matching synthetic
evidence is supplied. Unsupported artifact types or artifact/readiness
combinations fail closed.

The artifact contract is also checked against `PUBLISH_OUTPUTS`; drift between
the two authorities fails closed.

## Evidence bindings

Story Validation evidence records schema/profile versions, exact source
SHA-256, pass/fail state, evidence identity and decision time.

Production evidence records readiness class, artifact type, source SHA-256,
artifact SHA-256, production-configuration SHA-256, relevant-assets SHA-256,
validation profile/version, pass/fail state and evidence identity.

Human acceptance records readiness class, artifact type, artifact SHA-256,
acceptance profile/version, accepted/rejected state, evidence identity and
decision time.

Unknown schemas or profiles fail closed. Ambiguous duplicate evidence for the
same binding also fails closed rather than allowing record order to decide the
result.

## Exact artifact verification

The current artifact SHA-256 is always calculated from the real file under the
retained job's `output/` directory. The file must be a retained regular file,
not a symlink, and its size and SHA-256 must exactly match the pipeline's
`manifest.json` `output_evidence` record.

A replaced, edited, truncated, missing or otherwise changed artifact fails with
a stable integrity reason before production/publication readiness can pass.

## Production-configuration identity

Book System OS derives `production_config_sha256`; callers do not provide the
current value.

The canonical identity includes:

- artifact output key, filename and media type;
- the actual Pandoc command contract used for that artifact;
- the applicable template filename and exact template bytes when a template is
  active;
- the structural transformation identifier and version.

A later relevant template/export configuration change therefore makes previous
production evidence stale even when the old artifact file still exists.

## Relevant-assets identity

Book System OS derives `assets_sha256`; callers do not provide the current value.
The canonical asset set includes all retained non-manuscript files under the
job's `input/` directory and any referenced local image file outside that
retained directory, hashed from the actual current bytes.

Embedded `data:` image content is source-bound and also represented in the asset
identity. Non-retained HTTP(S) or otherwise unverifiable external image assets
cannot support BOS-RDY-001 publication/print readiness and fail closed rather
than being represented only by their URL.

## Persistence and integrity

Job-scoped evidence is stored at:

```text
<job>/evidence/bos-rdy-001.json
```

The record is atomically written, reuses the existing retained-source
provenance authority, records artifact-contract version `1`, and carries a
canonical SHA-256 over the complete evidence bundle.

Persistence and load both re-check evidence against authoritative current job
state. Evidence cannot be persisted or reloaded as current if its manuscript,
artifact, production configuration, assets or supported artifact/readiness
binding no longer match.

## Invalidation

A changed bound input invalidates the affected readiness claim, including:

- manuscript bytes/SHA-256;
- Story Validation evidence/profile/version;
- production configuration;
- relevant assets;
- artifact bytes/SHA-256;
- production-validation profile/version;
- required human-acceptance evidence/profile.

Regeneration invalidates human acceptance unless the resulting artifact is
byte-identical.

## v0.2 dry-run boundary

The v0.2 publish dry-run remains structural validation and output planning only.
`publishable: true` does not mean BOS-RDY-001 readiness passed.

Dry-run responses explicitly return BOS-RDY-001 as `evaluated: false`, identify
artifact contract version `1`, and return all four readiness states false with
reason:

```text
dry-run-structural-validation-only
```

See `docs/V0_2_PUBLISH_DRY_RUN_API.md`.
