# Book System OS v0.1 Production Hardening acceptance template

Use this template in each hardening pull request or its linked issue.

## Lane

```text
Gate: H-0X
Title:
Tracking issue:
```

## Exact baseline

```text
Accepted production tag: v0.1.8
Base commit:
Head commit:
```

Stop if the base is not the accepted tag or the previously authorised merged hardening commit.

## Authorised scope

### Files allowed

```text
- path/to/file
```

### Behaviour allowed

- 

### Explicit exclusions

- no v0.2 validation or publish routes;
- no print-production expansion;
- no Semantic Architect or generative editing;
- no unrelated refactoring;
- no production deployment from the implementation pull request.

## Automated validation

```text
python3 scripts/check_env.py
python3 -m compileall app scripts tests
python3 -m pytest -q
```

Additional lane-specific checks:

```text

```

### Result

```text
PASS / FAIL
```

## Controlled operational acceptance

Procedure:

1. 

Evidence recorded:

- timestamp:
- exact deployed commit:
- non-secret command output location:
- job IDs or fixture identifiers:
- observed result:

### Result

```text
PASS / FAIL / NOT YET RUN
```

## Data-integrity check

- [ ] Existing source manuscripts remain readable.
- [ ] Existing job metadata and status remain readable.
- [ ] Existing outputs and manifests remain available.
- [ ] Existing logs and event history remain available.
- [ ] No secret values are committed or included in evidence.

## Rollback

Rollback target:

```text

```

Rollback procedure validated:

- [ ] yes
- [ ] not required for this docs-only change
- [ ] not yet validated — do not merge/deploy

## Completion decision

A hardening gate may be marked complete only when:

- [ ] exact-head CI passes;
- [ ] controlled operational evidence passes where required;
- [ ] changed files match the authorised allowlist;
- [ ] no acceptance criterion is waived;
- [ ] excluded product work is absent;
- [ ] the gate matrix and authority record are updated in a separate closure change when appropriate.

Decision:

```text
ACCEPT / REJECT / RETURN FOR REPAIR
```
