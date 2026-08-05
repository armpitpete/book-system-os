# Visual Revision Studio v0.1

## Access

Open `/revisions` through the authenticated Book System OS dashboard service.

The surface uses the shared language:

**Current · Proposed · Compare · Accept · Keep for later · Reject · History**

## Workflow

1. Create a revision document and record the initial Current manuscript.
2. Create Proposed alternatives without changing Current.
3. Open Compare to inspect Current and Proposed side by side.
4. Review the deterministic difference, evidence, validation, consequences and risks.
5. Record one explicit human decision:
   - accept all;
   - accept selected parts and provide the actual merged manuscript;
   - keep for later;
   - reject.
6. Inspect History for the retained proposal and decision record.

## Safety behaviour

- Every form uses the existing dashboard authentication and CSRF system.
- Manuscript, title, rationale and metadata are HTML escaped before display.
- Touch-sized buttons are used; no action depends on hover, right-click or precision dragging.
- A stale proposal remains visible but its acceptance controls are removed.
- Accepting all or part creates a new Current version.
- Keeping or rejecting does not change Current.
- Rejected and deferred manuscript content remains inspectable.
- Every final decision requires a human name and authority reference.

## Boundary

This interface does not publish, export or deploy a book. It does not infer acceptance, delete rejected proposals, provide collaborative accounts or allow AI to make final decisions.
