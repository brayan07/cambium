# Memory Directory

This is the system's long-term memory, maintained by Cambium routines and versioned with git as its own repository (separate from the Cambium source).

## Structure

```
memory/
  _index.md                    # Master MOC (map of content)
  sessions/YYYY-MM-DD/         # Session digests, partitioned by date
  digests/{daily,weekly,monthly}/  # Periodic rollups
  knowledge/                   # System's beliefs (wiki)
  library/                     # Digested external content (reference)
  .consolidator-state.md       # Processing checkpoints
```

## Key Principles

### Knowledge = Beliefs

Every knowledge entry must include:
- **Confidence** (0-1): How certain the system is
- **Evidence trail**: What supports this belief (session references, user confirmation, observations)
- **Last confirmed date**: When the system last verified this belief

Beliefs not confirmed within 30 days should be flagged for review. Contradicted beliefs should be updated or removed immediately.

### Library = References

External content the system has read. Not endorsed as truth. The system may cite library entries but should not treat them as established beliefs without independent verification.

Do not internalize library content directly. Extract claims, verify through experience, then add to knowledge with citation.

### Organization

- **Flat within domains.** Max depth: `knowledge/{domain}/{topic}.md`. Split into a new domain before nesting deeper.
- **Indices are curated.** `_index.md` files are MOCs with annotations, not auto-generated listings.

### Concurrent Writes

Work on a session branch if updating shared files. Resolve merge conflicts intelligently. The consolidator handles periodic maintenance and index updates.

### Confidence Maintenance

- Beliefs confirmed by the user or repeated observation: raise confidence
- Beliefs contradicted by evidence: lower confidence or remove
- Beliefs stale (>30 days without confirmation): flag for review
- Never assert high confidence without evidence
