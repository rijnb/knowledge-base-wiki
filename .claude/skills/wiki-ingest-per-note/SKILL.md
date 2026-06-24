---
name: wiki-ingest-per-note
description: Use when about to process individual notes during Wiki ingestion — loaded as a required background skill by wiki-ingest and wiki-ingest-next-batch. Contains file conversion rules, topic assignment rules, WikiLink rules, and the session log format.
---

# Per-Note Ingestion

## Privacy opt-out

Before reading a Markdown note body, inspect only its YAML frontmatter. If it contains `ingest: false` (also `ingest:false`, quoted `false`, or case variants like `False`), skip the note entirely: do not convert attachments, do not create or update Wiki pages, and do not append any batch-log or `wiki/log.jsonl` entry. Report only the skipped note basename. This is a privacy boundary for stale or manually edited batch files; the partition script normally prevents protected notes and their explicitly linked local `raw/` files from entering batches in the first place.

> **⚠ MANDATORY LOGGING — DO NOT SKIP**
> After finishing all Wiki pages for each note, you MUST immediately append a JSON log entry to the batch log file specified in your prompt (e.g. `Write session logs to .import/batch-log-1.jsonl`).
> **Do this after every single note — do not wait until all notes are done.**
> Failing to write the log entry means the note is treated as unprocessed and will be re-ingested. The only exception is a Markdown note with `ingest: false`, which must be skipped without logging.

**Non-Markdown files are never ingested directly.** Each one is converted FIRST — move + companion + text extraction must all happen BEFORE inferring any `wiki/` pages from it.

> **⚠ ALWAYS use the converter script for `.eml`, `.html`, and `.vtt` — never hand-write their companion `.md`.** Only these scripts perform the `YYYY-MM-DD` filename-date prefix rename (and write the correct type-specific frontmatter). A hand-written companion silently loses the date prefix and drifts in format (e.g. `source: [[wikilink]]` instead of `source: "_resources/…"`). The manual procedure below applies ONLY to types with no script (pdf, images, docx, …).

The manual conversion procedure (pdf / images / docx only):
1. The original file is **moved** into a `_resources/` subdirectory of the directory it lives in (files already inside a `_resources/` directory stay where they are).
2. A **companion `.md` with the same name** (extension `.md`) is written where the original lived — i.e. in the directory above `_resources/` — containing:
   - frontmatter: `source: "_resources/<original filename>"` plus `converted: <now>` (the converter scripts write richer type-specific frontmatter instead)
   - an embed of the original: `![[<original filename>]]`
   - the extracted text in a collapsed callout, every line prefixed with `> `:
     ```markdown
     > [!ocr-extractor]- Extracted text
     > <line 1 of the extracted text>
     > <line 2 of the extracted text>
     ```
3. Wiki pages are then inferred from the **companion `.md`**, never from the original.

How to convert each type (use a sub-agent if needed):
- **`.vtt` transcripts** (script REQUIRED — never hand-convert): run `python3 scripts/system/convert-vtt-to-md.py --input-dir raw/transcripts` (or pass a single file path). The script does the move, companion, callout, AND the date-prefix rename for you.
- **`.eml` emails** (script REQUIRED — never hand-convert): run `python3 scripts/system/convert-eml-to-md.py --input-dir raw/emails` (or a single file path). The script does the move, companion, callout, AND the date-prefix rename.
- **`.html` emails** (script REQUIRED — never hand-convert): run `python3 scripts/system/convert-html-to-md.py --input-dir raw/emails` (or a single file path).
- **pdf** anywhere under `raw/`:
  1. Skip conversion if a companion `.md` already exists (same stem in the directory above `_resources/`, with `source:` pointing at the file), or if a legacy `<file_dir>/converted/<filename>.md` exists. Ingest that existing `.md` instead.
  2. Move the PDF into `_resources/` (skip the move if it is already inside a `_resources/` directory): `mkdir -p "<dir>/_resources" && mv "<dir>/<file>.pdf" "<dir>/_resources/"`
  3. Extract the text: `pdftotext "<dir>/_resources/<file>.pdf" -` (writes to stdout). Check whether the output is garbled (check the first 25 lines); if so, extract with your LLM vision instead.
  4. Write the companion `<dir>/<file>.md` as described above (frontmatter, `![[<file>.pdf]]`, extracted text in the callout).
- **images, .docx** and other non-Markdown files: same as PDF, but extract the text using the appropriate tool (do not install new tools!) or your LLM vision.

If you converted the attachment of a note, always append to the bottom of the source note:
```markdown
### AI converted attachments
| Original attachment | Converted to Markdown |
| [[original link]] | [[companion link]] |
```
(One table row per converted attachment; if the section already exists, append additional rows.)

After conversion of any file make sure you ingest the companion `.md`. So, if you read `x.md` and it has an attachment `y.jpg`, then `y.jpg` is moved to `_resources/` (if not already there), companion `y.md` gets generated, and you must ingest not just `x.md` but also `y.md`.

> **⚠ CONVERSION LOGGING — DO NOT SKIP**
> For **every** file you convert during processing (whether it was a batch entry like `foo.eml`, or an attachment discovered while reading a note like `y.pdf` / `y.jpg` / `y.docx`), you MUST later write log entries for **both** the moved original (its NEW `_resources/` path — the batch-entry path no longer exists after the move) and the companion `.md` path.
> The next batch run scans `raw/` for `.md`, `.pdf`, `.doc`, `.docx`, `.txt`, `.vtt`, `.eml` files and re-ingests anything whose exact path is not present in a log entry and has no companion `.md`. If you log only the companion (or only the parent note), the source file risks being re-ingested next time.

Then, for each Markdown file to ingest:
- The top-level Wiki topic list is: competition, concepts, conversations, decisions, people, problems, projects, systems.
- **Only use topics from that list.** Never create a `wiki/<dir>/` that is not one of those topics — not "architecture", not "tools", not anything else.
- Topic definitions — use these to classify correctly and avoid cross-topic confusion:
  - `competition` → external companies, external products, competitors, or approaches competing with yours
  - `conversations` → valuable results of earlier queries or AI conversations worth preserving as knowledge
  - `concepts` → technology terms, standards, domain vocabulary, mental models (NOT your own systems)
  - `decisions` → recorded choices between alternatives, with rationale (even informal ones)
  - `people` → named individuals (first+last name) who are employees or appear in multiple sources
  - `problems` → bugs, risks, blockers, failures, open questions requiring resolution
  - `projects` → named initiatives, programmes, workstreams (ongoing or completed)
  - `systems` → named products, platforms, services, tools owned or operated by your organisation
- **Work through every topic in the order listed above — do not skip any topic.** For each topic, answer its extraction question and act on the result:

  | Topic | Extraction question | Create a page ONLY when… |
  |---|---|---|
  | `competition` | Does the note mention a competitor, their product, or a market comparison? | Yes, for every distinct competitor or competing product. |
  | `concepts` | Does the note introduce or rely on a technical term, standard, methodology, or domain-specific idea that is not already a named system? | Yes, for every distinct concept. |
  | `conversations` | Is this note the result of a query or AI conversation whose conclusions are worth preserving as standing knowledge? | Yes, when the conversation produced insights, decisions, or summaries worth retaining beyond the session. |
  | `decisions` | Does the note record a choice between alternatives, a rationale, or a policy? | Yes, for every distinct choice, even informal ones. |
  | `people` | Does the note mention a named person with both first and last name who is a confirmed employee or appears in multiple sources? | Yes, for every such person. |
  | `problems` | Does the note describe a failure, bug, risk, blocker, or open question? | Yes, for every distinct problem. |
  | `projects` | Does the note mention a named initiative, programme, or workstream? | Yes, for every distinct project. |
  | `systems` | Does the note mention a named product, service, platform, component, or tool that is owned or used by the organisation? | Yes, for every distinct named system — even if barely described. |

- **Before creating or updating any Wiki page**, output a brief extraction table listing every candidate entity per topic found in the note. Only after completing the full table for all 8 topics, start writing files.
- **When in doubt, create a stub.** If you are unsure whether something qualifies, create a stub page (frontmatter `stub: true`, a title, and one italic source line). Stubs are cheap to delete; missed entities are expensive to recover.
- For relevant topics: create a new page or update an existing one.
  - Always create pages at exactly one level deep: `wiki/<topic>/<page>.md` — never deeper (e.g. `wiki/concepts/NavSDK.md`, not `wiki/concepts/Navigation/NavSDK.md`).
  - Never delete or overwrite hand-curated content; expand and add instead.
  - Do NOT add or edit `date` / `date_span` / `date_confidence` frontmatter — these freshness fields are populated automatically at finalization by `scripts/system/wiki-assign-dates.py`, computed from the source note's date. Just write the page content and `## Sources`; the dates follow.
  - For people: only create pages for confirmed employees, or people mentioned in multiple different sources. Require both first and last name (drop both the page and the reference, if incomplete). Ignore titles ("Dr.", "PhD.", "MD.") when parsing names — "John Smith, Dr." is one person named John Smith.
  - Check if the ingestion leads to a contradiction on the page. If ingestion leads to contradictions on a page, clearly mark the contradiction with a short explanation and add frontmatter tag `contradiction: true`.
  - **Supersession:** if the note **explicitly** states that something replaces, reverses, decommissions, or deprecates an existing wiki page (e.g. "X is being decommissioned in favour of Y", "this reverses the 2019 decision"), record it instead of just flagging a contradiction: add `superseded_by: [[wiki/<topic>/<successor>]]` (and optional `superseded_date:`) to the OLD page, and the reciprocal `supersedes: [[wiki/<topic>/<old>]]` to the successor. Only do this when the replacement is explicit — never infer it. The successor page must exist (create it in this session if needed). Don't delete the old page; it stays as history.
  - **Freshness candidates:** if the note seems to confirm, clarify, narrow, broaden, contradict, or supersede an existing claim but the replacement is not explicit enough for durable metadata, leave the canonical prose conservative. Mention the candidate relationship in your note summary and let the drift/curation workflow handle it one page at a time.
  - **Block provenance:** when you are already editing a small, specific claim on a canonical page, you may add a stable block ID and a compact `kb-prov-v1` provenance entry for that block. Do not try to backfill an entire page during ordinary ingest.
  - Cross-reference related pages using `[[WikiLinks]]`.
  - **WikiLink rule:** Only WikiLink to a page that (a) already exists in `wiki/`, or (b) you are creating/have created in this same session. If you identify a topic worth referencing but cannot describe it yet, create a minimal stub: frontmatter with `type` and `stub: true`, a `# Title` heading, and one italic line noting the source file. Stubs count as `pages_created` in the session log. Don't add the "stub: true" tag if you were able to generate at least minimal information on the subject.
  - **Stub expansion rule:** Before creating a new page, check if a stub already exists at that path (frontmatter contains `stub: true`). If so, expand it into a full page — remove `stub: true`, fill in proper content, and count it as `pages_updated` (not `pages_created`) in the session log.
- **After finishing all Wiki pages for this note**, verify:
  - Every named system mentioned in the note has a page in `wiki/systems/`.
  - Every named person (first + last name) mentioned in the note has a page in `wiki/people/`.
  - The number of pages touched is reasonable relative to the length and density of the note (a dense meeting note should produce many pages, not one or two).
  - If any of these checks fail, go back and fill in the gaps before moving on.
- Do NOT update `wiki/<topic>/_index.md` during a session (deferred to finalization).
- **After finishing each note's Wiki pages** (immediately, before moving to the next note): append its log entries to the batch log file specified in your prompt. Write one JSON object per line.
  - Write one entry for the file you were asked to ingest. If that batch entry was a non-Markdown file that you moved, use its NEW `_resources/` path (the batch path no longer exists after the move).
  - **In addition, for every conversion you performed during processing**, write entries for BOTH the moved original AND the companion `.md`. This includes:
    - Batch entries that are non-Markdown (`.eml`, `.vtt`, `.pdf`, `.docx`, …) — log the moved original (`_resources/` path) AND its companion `.md`.
    - Attachments converted while reading a note (e.g. `y.pdf` → companion `y.md`, `y.jpg` → companion `y.md`) — log BOTH the original's `_resources/` path AND the companion, even though the attachment was not a batch entry.
    - Companions that already existed when you got the file (conversion previously done but not logged) — still log BOTH paths after ingesting the companion.
  - The original-file entry can have an empty `pages_created`/`pages_updated` and a `summary` of "Source file moved to _resources and converted." The Wiki-page details belong on the companion-`.md` entry.
  - Rationale: the next batch run scans `raw/` for source extensions (`.pdf`, `.eml`, `.vtt`, `.doc`, `.docx`, `.txt`) and re-ingests anything whose path is not in any log entry and has no companion `.md`. Missing entries cause re-ingestion next time.

  Plain Markdown note (single entry):
```json
{"date":"YYYY-MM-DD HH:mm:ss","session":1,"file":"raw/notes/filename.md","summary":"One-sentence description.","pages_created":["wiki/concepts/NavSDK.md"],"pages_updated":["wiki/people/Jane Smith.md"]}
```
  Batch entry that required conversion (two entries — moved original first, then the companion `.md`):
```json
{"date":"YYYY-MM-DD HH:mm:ss","session":1,"file":"raw/emails/_resources/foo.eml","summary":"Source file moved to _resources and converted.","pages_created":[],"pages_updated":[]}
{"date":"YYYY-MM-DD HH:mm:ss","session":1,"file":"raw/emails/foo.md","summary":"One-sentence description.","pages_created":["wiki/concepts/NavSDK.md"],"pages_updated":["wiki/people/Jane Smith.md"]}
```
  Note `x.md` (in batch) with a PDF attachment `y.pdf` converted on the fly (three entries):
```json
{"date":"YYYY-MM-DD HH:mm:ss","session":1,"file":"raw/notes/x.md","summary":"One-sentence description.","pages_created":[],"pages_updated":["wiki/projects/AutoStream.md"]}
{"date":"YYYY-MM-DD HH:mm:ss","session":1,"file":"raw/notes/_resources/y.pdf","summary":"Source file moved to _resources and converted.","pages_created":[],"pages_updated":[]}
{"date":"YYYY-MM-DD HH:mm:ss","session":1,"file":"raw/notes/y.md","summary":"One-sentence description of the PDF contents.","pages_created":["wiki/concepts/SomeStandard.md"],"pages_updated":[]}
```
  The same original+companion pattern applies to `.vtt`, `.pdf`, `.docx`, images, and any other non-Markdown source that is converted — whether the source appeared in the batch directly or was discovered as an attachment during processing.

  The batch log path and session number were given to you in your prompt (e.g. `Write session logs to .import/batch-log-1.jsonl`). Do not wait until all notes are processed — write each entry as you go.

> **⚠ REMINDER:** You MUST write this log entry before moving on to the next note. This is not optional. If you skip it, the batch pipeline cannot track progress and the note will be re-ingested later.
