# Production hardening review checklist

Use before promoting any hardening pull request.

- [ ] Base matches the authorised accepted baseline or previous hardening merge.
- [ ] Head matches the reviewed exact commit.
- [ ] Changed files match the lane allowlist.
- [ ] Required compilation and tests passed.
- [ ] Real export tests ran when export behaviour changed.
- [ ] Controlled operational evidence passed where required.
- [ ] Persistent data remains readable.
- [ ] Rollback target is recorded.
- [ ] No secrets appear in code, logs or evidence.
- [ ] No v0.2, print-production or Semantic Architect work is present.
- [ ] The deterministic-core 10/10 completion authority is unchanged.
