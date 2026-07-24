# Production hardening stop rules

Stop only when:

- merge authority is required;
- production deployment authority is required;
- persistent data would be destroyed or irreversibly transformed;
- exact base, head, scope or evidence changes;
- dependencies are not satisfied;
- work crosses an explicit product exclusion;
- safety, privacy or credential exposure is at risk.

Do not stop merely because a routine implementation step completed.
