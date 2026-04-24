# Knowledge base wiki
(C) 2026, Rijn Buve

This is an LLM-maintained knowledge base for work. The primary goal is **decision intelligence**: understanding why decisions were taken, on what basis, by whom, and when. 

Secondary goals are mapping how technologies and systems relate, who is involved in what, and how competitors compare. 

The user curates the 'raw' source files; the LLM never changes the 'raw' files. The LLM maintains the wiki, does all writing, cross-referencing, and bookkeeping. The user reads the wiki, but never, or hardly ever, touches it.
## In a nutshell

Access to the knowledge base is as follows:
- **create and collect notes** 
	- user produces raw notes and stores them in the `raw/notes` directory, or
	- user uses the Obsidian Web Clipper to store notes in `raw/clips`, or
	- user stores `.vtt` meeting transcripts in `raw/transcripts`, or
	- user drags `.eml` emails to `raw/emails`, or
	- user stored handwritten notes or scanned pages (PDF, JPG) in `raw/scans`
- **ingest notes**
	- user asks to ingest (new) raw notes
	- LLM transcribes non-Markdown `raw/transcripts` (`.vtt`) and `raw/scans` (`.pdf/.jpg`) to Markdown (in `transcribed` directories)
	- LLM ingests raw notes and updates all relevant wiki topic pages in `wiki/`
	- LLM updates the semantic database `qmd` and runs a health check to keep the knowledge base lean and clean (after user confirmation)
- **query wiki** 
	- user asks a high-level question
	- LLM queries semantic database (with the `qmd` skill) for relevant page links (fast/token-efficient)
	- LLM processes `qmd`-suggested pages and produces answer to user
	- LLM store valuable conversations in `raw/conversations` to extend the knowledge base

The combination of using a semantic database to fetch relevant pages before analyzing documents and reasoning about them, makes this implementation of a knowledge significantly faster and more token efficient than when it's using Markdown files only.
## Directory structure (condensed)

```
<root>/
├── config/              ← config file for Obsidian web clipper
├── scripts/             ← helper scripts for CLAUDE.md
├── raw/
│   ├── clips/           ← web articles and saved pages (web clipper)
│   ├── confluence/      ← pages fetched from Atlassian Confluence (fetch cache)
│   ├── emails/          ← email threads (.elm)
│   ├── notes/           ← notes, 1:1s, and people-specific files
│   ├── scans/           ← handwritten pages, whiteboards
│   │   └── transcribed/ ← transcribed scans (LLM-generated Markdown)
│   └── transcripts/     ← meeting and conversation transcripts (.vtt)
├── wiki/
│   ├── index.md         ← top-level navigation to section indexes
│   ├── log.md           ← append-only ingest log
│   ├── concepts/        ← mental models and domain concepts
│   │   └── _index.md    ← alphabetical index of all concept pages
│   ├── competition/     ← competitor profiles
│   ├── conversations/   ← interesting and valuable conversations (query results)
│   ├── decisions/       ← decision records
│   ├── people/          ← people and team pages
│   ├── problems/        ← living problem tracking pages
│   ├── projects/        ← living project tracking pages
│   └── systems/         ← living system reference pages
├── CLAUDE.md            ← schema and workflow instructions for Claude Code
└── README.md            ← this file
```

**Rule:** `raw/` is immutable — the LLM reads from it, never writes to it (exception: `raw/confluence/` is written during Confluence fetch — treat as a fetch cache). `wiki/` is LLM-owned — the LLM writes, the user reads. Always update the relevant `wiki/<type>/_index.md` and `wiki/log.md` on every ingest. `CLAUDE.md` is co-evolved by both.

Only the Claude prompt and scripts are part of the Git repository, the raw notes and the generated wiki are not stored in Git.
## Workflows

### Action: ingest (standard)

When the user provides a source file to process, or ask to 'ingest new raw notes':

1. Check the last date of file ingestion using `wiki/log.md`. The file is sorted oldest-to-newest, so you should `tail` the file to see when the last ingestion date was.
2. Read the source files that have not been ingested yet, from `raw/`.
3. Source files may contain links to attachments (for example, in the `_resource` directory); always read the attachments as well.
4. Transcribe attachments if they are images or PDFs (e.g., handwritten notes, whiteboard photos) using `mcp__claude_ai_Atlassian__fetch` or a similar tool;.
5. Save transcriptions as Markdown with YAML frontmatter to a `transcribed/` in the directory where you read the source note and make sure the YAML frontmatter of the Markdown file links back to the original source note.
6. Transcripts from meetings in `raw/transcripts` may be in VTT format. Make sure the `.vtt` are prefix with `YYYY-mm-dd` of their `mtime` and rewrite them to a proper Markdown file and store the `.md` file next to the `.vtt` file (same name, different extension). Use the tags, like speaker tags, to make it clear who said what. Subsequently ingest the Markdown file.
7. Emails in `raw/emails/` may be in `.eml` format. Convert these to Markdown using `scripts/eml_to_md.py` for that (use `scripts/eml_to_md.py --help` to find out how the tool works).
8. Render the email body as Markdown; preserve quoted reply threads with `>` blockquotes. Subsequently ingest the `.md` file.
9. Identify whether the note to be ingested has a relation to these terms: competition, concepts, decisions, people, problems, projects and competitors.
10. For each terms: create a new wiki page or update the existing one based on the ingested note. When updating existing pages: add new information and expand sections; preserve existing content; never delete or overwrite hand-curated content.
11. When you identify contradictions between what was there and what you have added, clearly mark this contradiction with a short explanation of what contradicts and why.
12. Cross-reference terms pages — add `[[wikilinks]]` between related pages.
13. Update the relevant `wiki/<type>/_index.md` — add new pages (one line: link + summary); update summaries if materially changed. Keep entries alphabetically sorted.
14. Append to end of `wiki/log.md`: `## [YYYY-MM-DD] ingest | [[<relative path>]]` followed by a 1-2 sentence brief.
15. At the end of ingestion, present a multi-select menu (use `AskUserQuestion` with `multiSelect: true`) with these options — run only what is confirmed. Always execute QMD indexing before lint:
    - **All (recommended)** — QMD text + vector embedding + lint; supersedes all individual selections
    - **QMD text re-index** (`qmd update`) — fast, rebuilds keyword index only
    - **QMD vector embedding** (`qmd update && qmd embed`) — slow, loads ~2 GB models; supersedes text-only if both are selected
    - **Lint** — health check: orphan pages, contradictions, data gaps

A single ingested source note may easily touch 5–15, or even more, wiki pages. That is expected and desirable.

After ingestion of the notes, commit the changes to Git and push to `main`.

Note: if the user asks to 'ingest raw notes' (instead of new raw notes), then the user actually means to only ingest the new raw notes; do not ingest (or re-ingest) all notes, ever, without user confirmation.
### Action: ingest (Confluence via MCP)

This ingestion is triggered when a Confluence URL or Confluence page title is provided:

1. Fetch the page via `mcp__claude_ai_Atlassian__fetch`
2. Save to `raw/confluence/<page-slug>.md` with frontmatter (exception to the raw/ read-only rule — this is a fetch cache):
   ```yaml
   ---
   source_url: <confluence-url>
   fetched: YYYY-MM-DD
   ---
   ```
3. Proceed with standard ingest flow (above) from step 3.

**Re-ingest:** 
- If the user says "refresh this Confluence page", re-fetch, overwrite the cache, diff against the previous version, and flag any changes that affect existing wiki pages. 
### Action: bulk ingestion

When processing multiple raw source files, ingest them incrementally in batches of 20 files, unless specified otherwise, date sorted newest-to-oldest. Each batch builds the wiki term pages mentioned above incrementally. After each source note, announce which topics were created or updated and update the log file (see below). 

**Batch commit message format:**
```
wiki: ingest batch <N> — <type>/<date-range>
```
Example: `wiki: ingest batch 3 — notes/2025-01 to 2025-03`

When a batch is done, proceed with the next batch, until all notes are processed.
### Action: query

When the user asks a question:

1. Use `mcp__plugin_qmd_qmd__query` to search across wiki collections (concepts, decisions, people, systems, competition). For broad questions also search the notes collection.
2. Use `mcp__plugin_qmd_qmd__get` or `mcp__plugin_qmd_qmd__multi_get` to retrieve specific documents identified in step 1.
3. If QMD returns no results, fall back to reading the relevant `wiki/<type>/_index.md` directly, or `wiki/index.md` for top-level navigation.
4. Synthesize an answer with citations (`[[wiki/decisions/title]]`, `[[wiki/systems/name]]`, etc.).
5. If the answer is a valuable artifact (comparison, analysis, non-obvious connection), file it as a new wiki page in `wiki/discussions` and update the index.
### Action: health check (or lint)

When the user asks for a health check:

1. Scan for orphan pages (no inbound `[[links]]` from other pages). It is perfectly OK if the only inbound link is from an `index.md` or `_index.md` file.
2. Scan for contradictions in or between pages. These may occur when contradicting facts have been ingested earlier.
3. Identify topics mentioned in multiple pages that lack their own dedicated page within top-level topics.
4. Identify missing top-level topics. These may be suggest if multiple (10 or more) pages relate to the same high-level concept (just like projects, systems, decisions are high-level concepts) but the concept is not listed as a top-level topic in the main index.
5. Suggest data gaps and new sources worth finding.

The health check should never modify the database without user confirmation, but should provide clear recommendations for resolution of identified issues.
## Topic types in `wiki/` (priority order)

1. **Concepts** — technologies, standards, mental models, domain vocabulary
2. **Systems** — our products, platforms, and services
3. **Decisions** — why decisions were taken, on what basis, by whom, and when
4. **Projects** — active and past initiatives
5. **Problems** — active and past problems
6. **Competitors** — competing companies, products, and approaches
7. **People** — colleagues, contacts, external stakeholders, teams
## Page templates for topics

Use these rules when creating new pages:
- **Wikilink convention:** In page body text, always use bare slugs like `[[elastic-map]]`.
- Sections that provide links are presented bullet lists, not comma separated lists.
- Sections that provide links but that are empty are omitted (for example, if a system has no related decisions, the `## Related decisions` section is left out entirely).
- In `wiki/<type>/_index.md` entries, use vault-relative paths: `[[wiki/systems/elastic-map]]`. 
- Never mix formats. 
- If you reference a page or a raw note, or a person, make sure you make the reference a proper Wikilink.
- In the YAML frontmatter, make sure lists of items are using this format:
```
some-list:
  - item-1
  - item-2
```
### `wiki/index.md`

Top-level navigation page — links to section indexes only. Never add individual page entries here.
```markdown
---
type: index
date: YYYY-MM-DD
---
# Knowledge Base - index

Topics:
* [[wiki/competition/_index|Competition]] — competing companies, products, and approaches
* [[wiki/concepts/_index|Concepts]] — technologies, standards, mental models, domain vocabulary
* [[wiki/decisions/_index|Decisions]] — why decisions were taken, on what basis, by whom, and when
* [[wiki/people/_index|People]] — colleagues, contacts, external stakeholders, teams
* [[wiki/problems/_index|Problems]] — active and past problems
* [[wiki/projects/_index|Projects]] — active and past initiatives
* [[wiki/systems/_index|Systems]] — our products, platforms, and services
```

### `wiki/<type>/_index.md`

One per section (`concepts`, `decisions`, `systems`, `people`, `problems`, `projects`, `competition`). Entries must be kept alphabetically sorted. When adding a new page, add one line here; when materially changing a page summary, update the line.
```markdown
---
type: index
date: YYYY-MM-DD
---
# <Type> - index

<One-sentence description of what this topic type covers, from the topic types list above.>

- [[wiki/concepts/isa-regulation|ISA regulation]] — EU Intelligent Speed Assistance mandatory regulation; requires current speed limit data even post-subscription-expiry.
- [[wiki/concepts/lane-level-navigation|Lane level navigation]] — LLN capabilities: visualization, positioning, guidance, closures, turn-dependent jams; HD Orbis data requirements.

---

[[wiki/index|← Index]]
```
### `wiki/decisions/<slug>.md`

```markdown
---
type: decision
status: accepted | superseded | proposed
date: YYYY-MM-DD
systems: 
  - system-name
people:
  - person-name
---
# Decision: <title>
## Context
## Concern
## Criteria
## Options
## Decision
## Rationale
## Consequences
## Related decisions
- [[...link to related decision (short description of relationship)...]]
- [[...]]
## Related systems
- [[...links to related systems (short description of relationship)...]]
- [[...]]
## Related people
- [[...links to related people (short description of relationship)...]]
- [[...]]
## Related notes
- [[...links to related raw notes (short description of relationship)...]]
- [[...]]
```

**Rule:** `## Concern` describes the problem without referencing any solution. Solutions belong only in `## Options`, `## Decision`, and `## Rationale`.
### `wiki/systems/<slug>.md`

```markdown
---
type: system
owner: 
   - team-name
status: active | deprecated | planned
---
# <System Name>
## What it does
## Interfaces and dependencies
## Known issues and risks
## Related decisions
- [[...links to related decisions, key-design decisions first (short description of relationship)...]]
- [[...]]
## Related systems 
- [[...links to related systems (short description of relationship)...]]
- [[...]]
## Related people 
- [[...links to related people (short description of relationship)...]]
- [[...]]
## Related notes 
- [[...links to related raw notes (short description of relationship)...]]
- [[...]]
```
### `wiki/people/<slug>.md`

```markdown
---
type: person | team
---
# <Name>
## Role and scope
## Working style and context
## Active on
- [[project-link]]
## Related decisions 
- [[...links to related decisions (short description of relationship)...]]
- [[...]]
## Related systems 
- [[...links to related systems (short description of relationship)...]]
- [[...]]
## Related notes 
- [[...links to related raw notes (short description of relationship)...]]
- [[...]]
```
### `wiki/concepts/<slug>.md`

```markdown
---
type: concept
---
# <Concept>
## Short definition
## When it applies
## Explanation of the concept
## Examples in our context
- [[system-link]]
- [[...]]
## Related decisions
- [[...links to related decisions (short description of relationship)...]]
- [[...]]
## Related systems
- [[...links to related systems (short description of relationship)...]]
- [[...]]
## Related people
- [[...links to related people (short description of relationship)...]]
- [[...]]
## Related notes
- [[...links to related raw notes (short description of relationship)...]]
- [[...]]
```
### `wiki/competition/<slug>.md`

```markdown
---
type: competitor
---
# <Competitor Name>
## What they do
## Key products and technologies
## How they compare to us
## Related decisions
- [[...links to related decisions (short description of relationship)...]]
- [[...]]
## Related systems
- [[...links to related systems (short description of relationship)...]]
- [[...]]
## Related notes
- [[...links to related raw notes (short description of relationship)...]]
- [[...]]
```
### `wiki/conversations/<slug>.md`

```markdown
---
type: conversation
---
# <Conversations>
## Summary
## Conversation
## Related
- [[...links to related notes...]]
- [[...]]
```
### `wiki/projects/<slug>.md` 

```markdown
---
type: project 
status: active | closed | paused
started: YYYY-MM-DD 
---
# <Title>
## Project description and goals
## Current state
## Open questions
## Log
<!-- append updates here, newest first -->
## Related decisions
- [[...links to related decisions (short description of relationship)...]]
- [[...]]
## Related systems
- [[...links to related systems (short description of relationship)...]]
- [[...]]
## Related people
- [[...links to related people (short description of relationship)...]]
- [[...]]
## Related notes
- [[...links to related raw notes (short description of relationship)...]]
- [[...]]
```
### `wiki/problems/<slug>.md`

```markdown
---
type: problem
status: open | closed | deferred
started: YYYY-MM-DD 
---
# <Title>
## Problem statement and goal
## Current state
## Open questions
## Log
<!-- append updates here, newest first -->
## Related decisions
- [[...links to related decisions (short description of relationship)...]]
- [[...]]
## Related systems
- [[...links to related systems (short description of relationship)...]]
- [[...]]
## Related people
- [[...links to related people (short description of relationship)...]]
- [[...]]
## Related notes
- [[...links to related raw notes (short description of relationship)...]]
- [[...]]
```

**Rule:** The `## Log` section is append-only within the page. Updates go here without touching the rest of the structure.
## log.md format

This file is updated by the LLM after every ingest. It contains a oldest-to-newest list of ingestion actions. The log uses Markdown format with a header-3 (`###`) for the status message followed by a Markdown list of items that were added, changed, removed or other. Those items are always presented as a list, never comma-separated on a single line.

Use one header-3 (`###`) line and section per ingested item, do not concatenate items on a `###` line. 

Example:

```markdown
# Ingest Log

## [2026-04-20] init | wiki initialized

## [2026-04-25] ingest - [[raw/transcripts/meeting-2026-03-01.md]] Quarterly planning meeting. Discussed AutoStream roadmap and tile cache latency issue.
  - [[more notes]] - Short description.
- Created pages: 
  - [[decisions/adopt-vector-tiles]]
  - [[systems/AutoStream]]
- Updated pages: 
  - [[people/Jane Smith]]
  - [[more updates]]
```

To know what the latest ingestion dates were, parse recent entries with: `grep "^## \[" wiki/log.md | tail -50`. The file is sorted oldest-to-newest.
