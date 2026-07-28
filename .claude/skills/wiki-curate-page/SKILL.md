---
name: wiki-curate-page
description: Use when the user asks to curate, refresh, clean up, or make one canonical Wiki page more accurate using raw evidence and freshness/drift signals.
---

# Knowledge Base - One-Page Curation

Use this skill for targeted canonical-page cleanup. Do not bulk rewrite `wiki/`. Work one page at a time.

## Inputs

The user may provide:

- a page path such as `wiki/concepts/Some Concept.md`;
- a WikiLink such as `[[wiki/concepts/Some Concept]]`;
- a title from a drift report.

If the target is ambiguous, ask for the exact page before editing.

## Read-only preparation

1. Run provenance validation:
   ```bash
   python3 scripts/system/wiki-provenance-lint.py --format text --root .
   ```
2. Build the inventory:
   ```bash
   python3 scripts/system/wiki-freshness-inventory.py --format json --root .
   ```
3. Run drift detection if no page was supplied:
   ```bash
   python3 scripts/system/wiki-drift-detect.py --format text --root . --limit 25
   ```
4. Read the selected canonical page and its likely raw sources. Prefer raw sources that explicitly link to the page, appear in the page's `## Sources`, or are shown by the drift report.

For a supplied page, get the read-only curation packet first:

```bash
python3 scripts/system/wiki-curate-page.py --page "<wiki/page.md>" --format json
```

The packet includes current block inventory, provenance validation, drift reasons, related raw notes, and suggested actions.

## Curation rules

- Preserve useful human-written prose.
- Preserve stable block IDs when the meaning remains continuous.
- Add new block IDs only to meaningful claims, decisions, open questions, tables, or historical notes.
- Add one compact `> [!provenance]- Provenance` callout if the page lacks one.
- Use `provenance_quality: inferred` when source lineage is reconstructed during migration.
- `migration_status: legacy-inferred-minimal` is only for classifier-reviewed status/caution stamps; it reduces query-time risk but does not count as full block-level curation.
- Prefer local edits: confirm, revise, split, supersede, move to history, or delete stale text that has no audit value.
- Keep old material only if it explains history, rationale, or past assumptions.
- Durable `status: superseded` requires clear evidence and a `superseded_by` target.
- If evidence conflicts but is unresolved, mark the block `status: disputed` instead of forcing a single answer.

## Recommended page shape

Use the existing page structure when it is already clear. When a page needs restructuring, prefer:

```markdown
# Page Title

## Current Understanding

Current best synthesis. ^claim-current-01

## Practical Implications

What this means operationally. ^claim-implication-01

## Open Questions

- Unresolved question. ^claim-open-01

## Historical Context

Past framing that remains useful. ^claim-history-01

> [!provenance]- Provenance
> schema: kb-prov-v1
> migration_status: legacy-inferred
> blocks:
>   claim-current-01:
>     sources: [raw:example#b1]
>     observed: YYYY-MM-DD
>     checked: YYYY-MM-DD
>     status: current
>     confidence: medium
>     provenance_quality: inferred
```

## Verification

After editing one page:

```bash
python3 scripts/system/wiki-provenance-lint.py --format text --root .
python3 -m unittest discover -s scripts/tests -v
```

If tests are too broad for a tiny prose-only edit, at minimum run the provenance lint and explain that the broader test suite was not run.

## Wikilink format

When linking a note, the wikilink target is the note's **exact filename, with spaces** — never slugified. Write `[[Real-Time Map]]`, not `[[Real-Time-Map]]`; `[[1-N Device Association]]`, not `[[1-N-Device-Association]]`. Keep hyphens only where the real filename has them. Slugified links do not resolve in Obsidian.
