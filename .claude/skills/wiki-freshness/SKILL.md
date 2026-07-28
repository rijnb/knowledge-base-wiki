---
name: wiki-freshness
description: Use when the user asks for a freshness check, provenance check, drift queue, coverage backlog, or asks whether the knowledge base has outdated canonical pages.
---

# Knowledge Base - Freshness Check

Use this skill when the user asks for freshness, provenance, drift, or coverage status. This is the easy front door for the freshness tooling.

Run:

```bash
scripts/wiki-freshness.sh --root .
```

This command:

- validates `kb-prov-v1` provenance blocks;
- builds a freshness inventory;
- writes `.wiki-scratch/freshness-curation-candidates.md`;
- writes `.wiki-scratch/provenance-coverage-backlog.md`.

It is read-only for `wiki/` content. It may write queue/backlog files under `.wiki-scratch/`.

Report:

- provenance lint issue count;
- drift candidate count;
- coverage counts (`covered`, `minimal-stamp`, legacy backlog);
- the first few highest-priority next pages when useful.

If the user asks to make a page more accurate, switch to `wiki-curate-page` for exactly one page.
