---
name: knowledge-base-ingest
description: Use when the user asks to ingest, import, or process notes; mentions a raw note file path; provides a Confluence URL or page title; or says "process new files". Covers standard ingestion, Confluence MCP fetching, and bulk batch processing.
---

# Knowledge Base - Ingest

## Standard ingestion

When user provides a source file or asks to 'ingest new raw notes':

1. Check last ingestion date: `grep "^## \[" wiki/log.md | tail -50`
2. Read source files in `raw/` not yet ingested.
3. Read any attachments linked from source files (e.g. `_resource/` directories).
4. Transcribe images/PDFs (handwritten notes, whiteboards) using `mcp__claude_ai_Atlassian__fetch` or similar.
5. Save transcriptions to `transcribed/` alongside the source, with YAML frontmatter linking back to the source.
6. For `.vtt` transcripts in `raw/transcripts/`: prefix filename with `YYYY-MM-DD` (mtime), rewrite to Markdown (`.md`, same name), tag speakers clearly. Ingest the `.md`.
7. For `.eml` emails in `raw/emails/`: convert with `scripts/eml_to_md.py` (run `--help` for usage). Render body as Markdown; preserve reply threads as `>` blockquotes. Ingest the `.md`.
8. Identify relationships to: competition, concepts, decisions, people, problems, projects.
9. For each: create or update the wiki page. Add new info, expand sections; never delete or overwrite hand-curated content.
10. Mark contradictions explicitly with a short explanation of what conflicts and why.
11. Cross-reference with `[[wikilinks]]` between related pages.
12. Update `wiki/<type>/_index.md` — add new entries (link + summary); keep alphabetically sorted.
13. Append to `wiki/log.md`: `## [YYYY-MM-DD] ingest | [[<relative path>]]` + 1–2 sentence brief.
14. At end of ingestion, show multi-select menu (`AskUserQuestion` with `multiSelect: true`). Always run QMD indexing before lint:
    - **All (recommended)** — QMD text + vector embedding + lint; supersedes individual selections
    - **QMD text re-index** (`qmd update`) — fast, keywords only
    - **QMD vector embedding** (`qmd update && qmd embed`) — slow, ~2 GB models; supersedes text-only if both selected
    - **Lint** — health check: orphans, contradictions, gaps
15. Commit and push to `main`.

**Note:** "ingest raw notes" means only new (un-ingested) notes. Never re-ingest all notes without explicit user confirmation.

A single source note may touch 5–15+ wiki pages. That is expected and desirable.

## Confluence ingestion

Triggered by a Confluence URL or page title:

1. Fetch via `mcp__claude_ai_Atlassian__fetch`
2. Save to `raw/confluence/<page-slug>.md` with frontmatter:
   ```yaml
   ---
   source_url: <url>
   fetched: YYYY-MM-DD
   ---
   ```
3. Continue with standard ingest from step 3 above.

**Refresh:** "refresh this Confluence page" → re-fetch, overwrite cache, diff vs previous, flag changes affecting existing wiki pages.

## Bulk ingestion

When processing multiple files: ingest in batches of 20, newest-to-oldest. After each note, announce topics created/updated and update log.

**Commit format:**
```
wiki: ingest batch <N> — <type>/<date-range>
```
Example: `wiki: ingest batch 3 — notes/2025-01 to 2025-03`

Proceed batch-by-batch until all notes are processed.

## log.md format

`wiki/log.md` is sorted oldest-to-newest. Each entry is a `## [YYYY-MM-DD]` header followed by a Markdown list. One header per ingested item — never concatenate items on one line.

```markdown
# Ingest Log

## [2026-04-20] init | wiki initialized

## [2026-04-25] ingest - [[raw/transcripts/meeting-2026-03-01.md]] Quarterly planning meeting.
- [[more notes]] - Short description.
- Created pages:
  - [[decisions/adopt-vector-tiles]]
  - [[systems/AutoStream]]
- Updated pages:
  - [[people/Jane Smith]]
```

Parse recent entries: `grep "^## \[" wiki/log.md | tail -50`
