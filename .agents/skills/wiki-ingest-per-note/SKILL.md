---
name: wiki-ingest-per-note
description: Use when about to process individual notes during Wiki ingestion — loaded as a required background skill by wiki-ingest and wiki-ingest-next-batch. Contains file conversion rules, topic assignment rules, WikiLink rules, and the session log format.
---

# Per-Note Ingestion

> **⚠ MANDATORY LOGGING — DO NOT SKIP**
> After finishing all Wiki pages for each note, you MUST immediately append a JSON log entry to the batch log file specified in your prompt (e.g. `Write session logs to .import/batch-log-1.jsonl`).
> **Do this after every single note — do not wait until all notes are done.**
> Failing to write the log entry means the note is treated as unprocessed and will be re-ingested.

For each file you need to ingest, first use a sub-agent to convert it and any of its attachments if needed:
- **`.vtt` transcripts** in `raw/transcripts/`:
  - run `python3 scripts/system/convert-vtt-to-md.py --input-dir raw/transcripts --output-dir raw/transcripts/converted`.
  - Ingest only `.md` files.
- **`.eml` emails** in `raw/emails/`:
  - run `python3 scripts/system/convert-eml-to-md.py --input-dir raw/emails --output-dir raw/emails/converted`.
  - Ingest only `.md` files.
- **`.html` emails** in `raw/emails/`:
  - run `python3 scripts/system/convert-html-to-md.py --input-dir raw/emails --output-dir raw/emails/converted`.
  - Ingest only `.md` files.
- **pdf** in `raw/<section>` or in a `_resources` directory:
  1. Check if `<file_dir>/converted/<filename>.md` exists — if so, skip.
  2. Convert it to Markdown using `pdftotext`:
     ```
     pdftotext "<pdf-path>/<pdf-file>.pdf" "<pdf-path>/converted/<pdf-file>.md"

     ```
  2. Check if the converted markdown file is garbled or not (check the first 25 lines). If it seems to be garbled, re-convert the PDF using your LLM vision. Overwrite the converted `.md` file in that case with your conversion.
- **images, .docx** and other files in `_resources`: for each of these files that is not already Markdown:
  1. Check if `<file_dir>/converted/<filename>.md` exists — if so, skip.
  2. Otherwise, convert to Markdown using the appropriate tool (do not install new tools!), or use LLM vision.
     Save the result as Markdown to `<file_dir>/converted/<filename>.md` with frontmatter: `source` (path to original), `converted` (now).

If you converted the attachment of a note, always append to the bottom of the source note:
```markdown
### AI converted attachments
| Original attachment | Converted to Markdown |
| [[original link]] | [[converted link]] |
```
(One table row per converted attachment; if the section already exists, append additional rows.)

After conversion of any file to Markdown make sure you ingest that new file as well as the original. So, if you read `x.md` and it has an attachment to `y.jpg` and `y.jpg.md` gets generated during the conversion, then you must now ingest not just `x.md` but also `y.jpg.md`.

> **⚠ CONVERSION LOGGING — DO NOT SKIP**
> For **every** file you convert during processing (whether it was a batch entry like `foo.eml`, or an attachment discovered while reading a note like `y.pdf` / `y.jpg` / `y.docx`), you MUST later write log entries for **both** the source file path and the converted `.md` path.
> The next batch run scans `raw/` for `.md`, `.pdf`, `.doc`, `.docx`, `.txt`, `.vtt`, `.eml` files and re-ingests anything whose exact path is not present in a log entry. If you log only the converted `.md` (or only the parent note), the source attachment will be re-ingested next time.

Then, for each Markdown file to ingest:
- The top-level Wiki topic list is: competition, concepts, decisions, people, problems, projects, systems.
- **Only use topics from that list.** Never create a `wiki/<dir>/` that is not one of those topics — not "systems", not "architecture", not anything else.
- Topic definitions — use these to classify correctly and avoid cross-topic confusion:
  - `competition` → external companies, external products, competitores, or approaches competing with yours
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
  | `decisions` | Does the note record a choice between alternatives, a rationale, or a policy? | Yes, for every distinct choice, even informal ones. |
  | `people` | Does the note mention a named person with both first and last name who is a confirmed employee or appears in multiple sources? | Yes, for every such person. |
  | `problems` | Does the note describe a failure, bug, risk, blocker, or open question? | Yes, for every distinct problem. |
  | `projects` | Does the note mention a named initiative, programme, or workstream? | Yes, for every distinct project. |
  | `systems` | Does the note mention a named product, service, platform, component, or tool that is owned or used by the organisation? | Yes, for every distinct named system — even if barely described. |

- **Before creating or updating any Wiki page**, output a brief extraction table listing every candidate entity per topic found in the note. Only after completing the full table for all 7 topics, start writing files.
- **When in doubt, create a stub.** If you are unsure whether something qualifies, create a stub page (frontmatter `stub: true`, a title, and one italic source line). Stubs are cheap to delete; missed entities are expensive to recover.
- For relevant topics: create a new page or update an existing one.
  - Always create pages at exactly one level deep: `wiki/<topic>/<page>.md` — never deeper (e.g. `wiki/concepts/NavSDK.md`, not `wiki/concepts/Navigation/NavSDK.md`).
  - Never delete or overwrite hand-curated content; expand and add instead.
  - Do NOT add or edit `date` / `date_span` / `date_confidence` frontmatter — these freshness fields are populated automatically at finalization by `scripts/system/wiki-assign-dates.py`, computed from the source note's date. Just write the page content and `## Sources`; the dates follow.
  - For people: only create pages for confirmed employees, or people mentioned in multiple different sources. Require both first and last name (drop both the page and the reference, if incomplete). Ignore titles ("Dr.", "PhD.", "MD.") when parsing names — "John Smith, Dr." is one person named John Smith.
  - Check if the ingestion leads to a contradiction on the page. If ingestion leads to contradictions on a page, clearly mark the contradiction with a short explanation and add frontmatter tag `contradiction: true`.
  - **Supersession:** if the note **explicitly** states that something replaces, reverses, decommissions, or deprecates an existing wiki page (e.g. "X is being decommissioned in favour of Y", "this reverses the 2019 decision"), record it instead of just flagging a contradiction: add `superseded_by: [[wiki/<topic>/<successor>]]` (and optional `superseded_date:`) to the OLD page, and the reciprocal `supersedes: [[wiki/<topic>/<old>]]` to the successor. Only do this when the replacement is explicit — never infer it. The successor page must exist (create it in this session if needed). Don't delete the old page; it stays as history.
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
  - Write one entry for the file you were asked to ingest (the path that was in the batch).
  - **In addition, for every conversion you performed during processing**, write entries for BOTH the source file and the converted `.md`. This includes:
    - Batch entries that are non-Markdown (`.eml`, `.vtt`, `.pdf`, `.docx`, …) — log the batch path (the source) AND its converted `.md`.
    - Attachments converted while reading a note (e.g. `y.pdf` → `y.pdf.md`, `y.jpg` → `y.jpg.md`, `y.docx` → `y.docx.md`) — log BOTH `y.pdf` (or `.jpg`/`.docx`/…) AND `converted/y.pdf.md`, even though only `y.pdf` was an attachment, not a batch entry.
  - The source-file entry can have an empty `pages_created`/`pages_updated` and a `summary` of "Source file processed via conversion." The Wiki-page details belong on the converted-`.md` entry.
  - Rationale: the next batch run scans `raw/` for source extensions (`.pdf`, `.eml`, `.vtt`, `.doc`, `.docx`, `.txt`) and re-ingests anything whose path is not in any log entry. Missing the source-file entry causes re-ingestion next time.

  Plain Markdown note (single entry):
```json
{"date":"YYYY-MM-DD HH:mm:ss","session":1,"file":"raw/notes/filename.md","summary":"One-sentence description.","pages_created":["wiki/concepts/NavSDK.md"],"pages_updated":["wiki/people/Jane Smith.md"]}
```
  Batch entry that required conversion (two entries — source file first, then the converted `.md`):
```json
{"date":"YYYY-MM-DD HH:mm:ss","session":1,"file":"raw/emails/foo.eml","summary":"Source file processed via conversion.","pages_created":[],"pages_updated":[]}
{"date":"YYYY-MM-DD HH:mm:ss","session":1,"file":"raw/emails/converted/foo.md","summary":"One-sentence description.","pages_created":["wiki/concepts/NavSDK.md"],"pages_updated":["wiki/people/Jane Smith.md"]}
```
  Note `x.md` (in batch) with a PDF attachment `y.pdf` converted on the fly (three entries):
```json
{"date":"YYYY-MM-DD HH:mm:ss","session":1,"file":"raw/notes/x.md","summary":"One-sentence description.","pages_created":[],"pages_updated":["wiki/projects/AutoStream.md"]}
{"date":"YYYY-MM-DD HH:mm:ss","session":1,"file":"raw/notes/_resources/y.pdf","summary":"Source file processed via conversion.","pages_created":[],"pages_updated":[]}
{"date":"YYYY-MM-DD HH:mm:ss","session":1,"file":"raw/notes/_resources/converted/y.pdf.md","summary":"One-sentence description of the PDF contents.","pages_created":["wiki/concepts/SomeStandard.md"],"pages_updated":[]}
```
  The same source+converted pattern applies to `.vtt`, `.pdf`, `.docx`, images, and any other non-Markdown source that is converted — whether the source appeared in the batch directly or was discovered as an attachment during processing.

  The batch log path and session number were given to you in your prompt (e.g. `Write session logs to .import/batch-log-1.jsonl`). Do not wait until all notes are processed — write each entry as you go.

> **⚠ REMINDER:** You MUST write this log entry before moving on to the next note. This is not optional. If you skip it, the batch pipeline cannot track progress and the note will be re-ingested later.
