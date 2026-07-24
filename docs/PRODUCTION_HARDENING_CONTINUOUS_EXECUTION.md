# Continuous execution rule

Within a dependency-satisfied and authorised hardening lane, work continues through safe reversible steps without stopping for routine approval.

The execution sequence is:

```text
inspect -> implement -> test -> repair -> commit -> push -> draft PR -> CI repair
```

Stop only at an owner-protected boundary or when the authority becomes invalid.
