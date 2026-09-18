# INBOX

Store notes here that are not ready for ingestion (yet). Draft notes in `INBOX` are **not** ingested. When a note is ready, move it to `raw/notes` and say:
```
ingest new notes
```
or run `scripts/wiki-ingest.sh` in a terminal for unattended bulk ingestion.

## What is in this vault

Three areas, with different owners:

| | what it is | who edits it |
|---|---|---|
| `raw/` | your evidence — notes, clips, emails, transcripts, scans | **you** (the LLM never edits your notes) |
| `wiki/` | canonical pages built from `raw/` | the LLM |
| `work/` | your work organisation — what you are doing and what is next | **you**, one topic page at a time |

The first two are the knowledge base: what we *know*. `work/` is separate — what you are *doing*. See below for each.

## Working with the knowledge base

Every action below is a `wiki-*` skill you trigger with a plain phrase in Claude; most also have a script for unattended use.

### Adding raw notes

Put source material in the matching `raw/` subfolder, then ingest it:

- `raw/notes` — typed notes, 1:1s, people-specific files
- `raw/clips` — web articles saved with the Obsidian Web Clipper (template in `config/obsidian_webclipper_template.json`)
- `raw/transcripts` — `.vtt` meeting transcripts
- `raw/emails` — emails (ask **"fetch mail"**, or drop `.eml`/`.html` files here)
- `raw/slack` — Slack channels and DMs (ask **"fetch slack"** or **"fetch Slack last N days"**)
- `raw/scans` — handwritten pages or scanned PDFs/JPGs
- `raw/confluence` — fetch cache for Confluence pages (give **"ingest"** a Confluence URL or page title)

Non-Markdown files are auto-converted: the original moves to `_resources/` and a companion `.md` (preview + extracted text) takes its place. Add `ingest: false` frontmatter to a note to keep it (and the local files it links) out of ingestion.

### Ingesting

| Say | Skill | What happens |
|-----|-------|--------------|
| **"ingest new notes"** / "ingest `<path>`" / a Confluence URL | `wiki-ingest` | Partitions new notes into batches and processes the first one |
| **"ingest next batch"** (in a parallel session) | `wiki-ingest-next-batch` | Claims and processes one more batch |
| **"finalize ingest"** | `wiki-finalize-ingest` | Merges logs, assigns dates, rebuilds `index.md` files, re-indexes QMD, runs doctor + freshness |
| **"clear batches"** / "abort ingest" | `wiki-clear-ingest-batches` | Removes `.import/` batch files after a failed or abandoned import |

Dedup is by content hash, so renaming a raw note does not re-ingest it; editing it does. `scripts/wiki-ingest.sh` runs the whole loop unattended (convert → batch → ingest → finalize) and pauses when the Claude usage window is nearly full.

### Asking questions

Just ask — **`wiki-query`** is the default skill for any question ("what do we know about…", "who is…", "tell me about…"). It searches QMD, ranks retrieved pages by provenance freshness, and demotes stale or superseded evidence with an explanation. Say **"wiki-ground [topic]"** to make the whole conversation treat the KB as source of truth. Say **"write an article about [topic]"** for a footnoted, publication-quality piece from vault knowledge plus web research.

### Maintaining the wiki

Three regular maintenance actions, in this order — especially after ingesting:

1. **"health check"** (or run `scripts/wiki-doctor.py`) — `wiki-doctor` finds and helps fix:
   - **Broken links** — remove, flag, or replace with plain text
   - **Orphaned pages** — delete, or keep (mark `orphan: false`)
   - **Stub pages** — pages the LLM referenced but never filled in; delete or keep
   - **Loose files** — non-Markdown files outside `_resources/`; `--fix-simple-errors` relocates them via the Obsidian CLI (Obsidian must be running)

   The goal is zero false-positive alerts, so a clean run means the knowledge base is genuinely sound.

2. **"freshness check"** (or run `scripts/wiki-freshness.sh`) — `wiki-freshness` validates block-level **provenance** on canonical pages (when a claim was observed/checked, its status, confidence) and writes two queues under `.wiki-scratch/`: `freshness-curation-candidates.md` (pages at real query-time risk — work this one first) and `provenance-coverage-backlog.md` (pages still without provenance).

3. **"curate this page"** — `wiki-curate-page` cleans up **one** canonical page using its raw evidence and the drift signals. Reach for it when the freshness queue flags a page, or when you notice a page is stale. Bulk curation is **not** recommended.

Also: **"add missing [topic]"** (`wiki-add-missing`) creates a page for a system, person, concept, project, decision, competitor, or problem the wiki lacks; `wiki-templates` supplies the page structure.

### Semantic search index

`wiki-query` relies on the QMD index. Finalize keeps it in sync; after manual edits run `qmd embed`, or `scripts/qmd-full-reindex.sh` for a full rebuild (`--skip-embed` skips the slow embedding step).

### Moving and renaming

Use the Obsidian CLI so links stay intact: `obsidian vault="TomTom" move path=<from> to=<to>`.

## Managing your work — `work/`

`work/` organises your work so that at any moment you can answer: what am I working on, what is next (mine or delegated), who is overdue for contact, and what did I do last month. Budget for running it: **≤ 30 min/day**.

**The only thing you maintain by hand is a topic page.** One file per large topic in `work/topics/`, each carrying a `status:` (`active` / `watching` / `parked`), a `progress:` sentence, and `## Next actions (me)`, `## Delegated` and `## Log` sections. Something to do → add `- [ ] …`. Something happened → add a dated line under `## Log`. A new subject with no topic → copy an existing page as a stub with `status: watching`.

Everything else is either rarely touched or generated:

| File | Role |
|------|------|
| `Compass.md` | mandate, lever, 90-day outcomes, and the out-list — rewritten rarely |
| `Stakeholders.md` | who needs what, contact cadence, `Last` contact date |
| `Backlog.md` | **compiled — never edit.** Regenerate with `python3 scripts/work-backlog.py` |
| `Topics.base` | table views: Now / All / Overdue review / Watching and parked |
| `weekly/`, `briefs/`, `reviews/`, `recaps/` | outputs of the skills below |

Three things to say in Claude:

| Say | Skill | What happens |
|-----|-------|--------------|
| **"run the weekly review"** | `work-weekly` | Monday review: scan what is new, triage each active topic, pick this week's work. Writes `work/weekly/YYYY-Www.md` |
| **"brief me for my 1:1 with [name]"** | `work-brief` | Five lines before a 1:1, grounded in the topic pages and the evidence since you last spoke |
| **"review this document"** | `review-doc` | A verdict on a doc, deck or proposal, grounded in the knowledge base |

Full manual, including the daily and monthly loops: [[How To Use Work Planning]]. Like `raw/` and `wiki/`, `work/` is **never committed to git** — it is yours alone.


![[INBOX/_resources/index.jpg]]
