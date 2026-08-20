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
- Ensure the page has OKF v0.2 provenance frontmatter (`sources:`, `generated:`, `verified:`); add it if the page lacks it. The legacy provenance callouts are abolished — if one remains, fold its source lineage into the `sources:` list and delete the callout.
- Ensure a one-line `description:` frontmatter field exists (plain text, wikilinks allowed, ~160 chars max, YAML double-quoted); write or refresh it as part of curation.
- Add the raw notes you used as `sources:` entries (`- id: s<N>` / `resource: "raw/..."`).
- **Per-claim source footnotes:** cite each claim with `[^s<N>]` refs placed before its `^block-id` anchor (anchor stays last), and keep the footnote-definitions block at the end of the page in sync — one `[^s<N>]: [[<resource>]]` line per referenced id.
- **When the human curates/confirms the page, APPEND a `verified:` entry with `by: "human:rijn.buve"` and `at: <today, YYYY-MM-DD>`.** Never remove existing `verified:` entries; `human:*` actors are the human-reviewed tier, `agent:*` ids the machine tier.
- Prefer local edits: confirm, revise, split, supersede, move to history, or delete stale text that has no audit value.
- Keep old material only if it explains history, rationale, or past assumptions.
- Durable `state: superseded` requires clear evidence and a `superseded_by` target.
- If evidence conflicts but is unresolved, mark the contradiction in prose and set frontmatter `contradiction: true` instead of forcing a single answer.

## Recommended page shape

Use the existing page structure when it is already clear. When a page needs restructuring, prefer:

```markdown
---
type: concept
description: "One-line summary of the page, ~160 chars max."
sources:
  - id: s1
    resource: "raw/notes/2024-04-04 Foo.md"
generated:
  by: "agent:wiki-ingest"
  at: 2024-04-04
verified:
  - by: "agent:wiki-freshness"
    at: 2026-06-25
  - by: "human:rijn.buve"
    at: YYYY-MM-DD
stale_after: 2027-01-01
---
# Page Title

## Current Understanding

Current best synthesis. ^claim-current-01

## Practical Implications

What this means operationally. ^claim-implication-01

## Open Questions

- Unresolved question. ^claim-open-01

## Historical Context

Past framing that remains useful. ^claim-history-01
```

`stale_after` is optional. `^block-id` anchors remain allowed as plain anchors for citation, but carry no per-block metadata.

## Verification

After editing one page:

```bash
python3 scripts/system/wiki-provenance-lint.py --format text --root .
python3 -m unittest discover -s scripts/tests -v
```

If tests are too broad for a tiny prose-only edit, at minimum run the provenance lint and explain that the broader test suite was not run.

## Wikilink format

When linking a note, the wikilink target is the note's **exact filename, with spaces** — never slugified. Write `[[Real-Time Map]]`, not `[[Real-Time-Map]]`; `[[1-N Device Association]]`, not `[[1-N-Device-Association]]`. Keep hyphens only where the real filename has them. Slugified links do not resolve in Obsidian.
