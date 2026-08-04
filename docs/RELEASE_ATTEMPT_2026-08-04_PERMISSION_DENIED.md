# Corpus Runtime Release Attempt — Permission Boundary

## Attempt

- attempted target: `81208b7ee6aa6379defe3a39ad70383e54ecda84`;
- expected production baseline: `97b27e367779c17f5248f8b4fdd4bbff965fe90b`;
- result: stopped before deployment;
- failure: `production_v2_01_acceptance.sh: Permission denied`.

## Classification

The corpus release launcher executed the tracked baseline acceptance shell file directly even though its Git-authoritative mode is non-executable. The failure occurred after private evidence snapshots and before the guarded deployment path began.

No production commit, service, persistent job, protected configuration or installed unit was changed.

## Correction

Invoke the baseline acceptance file explicitly through `bash` and retain its non-executable tracked mode. Require this form in regression coverage.

This record does not authorise deployment or close any deployment-gated issue.
