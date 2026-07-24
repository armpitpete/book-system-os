# Book System OS v0.1 Production Hardening change control

## Fixed completion boundary

The completed v0.1 deterministic publishing core remains 10/10 gates — 100% complete.

Production hardening is measured separately as H-01 through H-09. Hardening work must not alter the deterministic-core gate count, percentage or accepted completion evidence.

## Authorised progression

Within an authorised hardening lane, routine safe work may continue through:

```text
inspect -> design -> edit -> test -> repair -> commit -> push -> draft pull request
```

Routine progress reports are not approval gates.

## Protected boundaries

Stop before:

- merging a pull request;
- deploying to production;
- deleting or irreversibly transforming persistent job data;
- changing the fixed lane scope or file allowlist;
- entering v0.2, print-production or Semantic Architect work;
- proceeding after the base, head, CI evidence or production dependency changes materially.

## Evidence preservation

Every hardening lane must preserve:

- exact starting commit;
- exact reviewed head;
- changed-file list;
- CI run and result;
- controlled operational acceptance where required;
- rollback target;
- non-secret evidence location.

## Scope-change rule

Unexpected work discovered during implementation must be handled in one of three ways:

1. repair it within the current lane when it is necessary to satisfy an existing acceptance criterion and remains inside the allowlist;
2. record it as a separately bounded follow-up when it is useful but not required;
3. stop when it changes product direction, crosses an explicit exclusion or requires irreversible production action.

Do not manufacture approval gates for normal implementation choices inside an already authorised lane.
