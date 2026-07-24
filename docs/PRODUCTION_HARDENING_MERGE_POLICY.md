# Production hardening merge policy

Hardening pull requests remain draft while implementation or evidence is incomplete.

Promotion to ready for review requires:

- exact scope confirmed;
- exact-head CI passing;
- required operational acceptance prepared or completed as specified;
- no dependency violation;
- no excluded feature work.

Merge remains an explicit owner action. After merge, safe preparation for the next dependency-satisfied lane may continue without creating artificial permission gates.

Production deployment remains separate from repository merge.
