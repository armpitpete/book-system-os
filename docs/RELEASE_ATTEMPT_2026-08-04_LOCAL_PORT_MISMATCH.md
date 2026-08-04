# Corpus Runtime Release Attempt — Local Port Mismatch

## Attempt

- deployed target: `e5f92ec8ec1e1bd7090fa5db6435e6c0d36f917d`;
- prior production baseline: `97b27e367779c17f5248f8b4fdd4bbff965fe90b`;
- guarded deployment: pass;
- baseline V2-01 production acceptance: pass;
- corpus-specific acceptance: stopped at local health request.

## Classification

Production listens on the protected `BOOK_BIND_PORT`, currently `8080`. The corpus release launcher and standalone corpus acceptance program defaulted to `http://127.0.0.1:8088`, a port not used by the production API. Public health, readiness, status, authentication and four-format acceptance had already passed. Persistent storage remained unchanged.

This was an acceptance-address defect, not a runtime or deployment defect. Production remained deployed at the exact target commit.

## Correction

The local acceptance URL must be derived from the protected runtime configuration, not held as an unrelated hard-coded port. Regression coverage must prove that an omitted override resolves `BOOK_BIND_PORT` from the protected environment file.

This record does not close the deployment-gated issues until the corrected corpus-specific acceptance passes and the complete release evidence is recorded.
