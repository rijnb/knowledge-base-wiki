---
name: wiki-ingest-per-note
description: Use when about to process individual notes during Wiki ingestion — loaded as a required background skill by wiki-ingest and wiki-ingest-next-batch. Contains file conversion rules, topic assignment rules, WikiLink rules, and the session log format.
---

# Per-Note Ingestion

For each file you need to ingest, first use a sub-agent to convert it and any of its attachments if needed:
- **`.vtt` transcripts** in `raw/transcripts/`:
  - run `python3 scripts/convert-vtt-to-md.py --input-dir raw/transcripts --output-dir raw/transcripts/converted`.
  - Ingest only `.md` files.
- **`.eml` emails** in `raw/emails/`:
  - run `python3 scripts/convert-eml-to-md.py --input-dir raw/emails --output-dir raw/emails/converted`.
  - Ingest only `.md` files.
- **pdfs, images, .docx and attachments (files linked from in note)**: for each of these files that is not already markdown:
  1. Check if `<file_dir>/converted/<filename>.md` exists — if so, skip.
  2. Otherwise, convert to markdown using the appropriate tool (e.g. `mcp__claude_ai_Atlassian__fetch` for PDFs/images or convert it yourself).
     Save to `<file_dir>/converted/<filename>.md` with frontmatter: `source` (path to original), `converted` (now).
  3. Append to the bottom of the source note:
     ```markdown
     ### AI converted attachments
     | Original attachment | Converted to markdown |
     | [[original link]] | [[converted link]] |
     ```
     (One table row per converted attachment; if the section already exists, append additional rows.)

After conversion of any file to markdown make sure you ingest that new file as well as the original. So, if you read `x.md` and it has an attachment to `y.jpg` and `y.jpg.md` gets generated during the conversion, then you must now ingest not just `x.md` but also `y.jpg.md`.

Then, for each markdown file to ingest:
- The top-level Wiki topic list is: competition, concepts, decisions, people, problems, projects, systems.
- **Only use topics from that list.** Never create a `wiki/<dir>/` that is not one of those topics — not "systems", not "architecture", not anything else.
- Topic definitions — use these to classify correctly and avoid cross-topic confusion:
  - `competition` → external companies, products, or approaches competing with yours
  - `concepts` → technology terms, standards, domain vocabulary, mental models (NOT your own systems)
  - `decisions` → recorded choices between alternatives, with rationale (even informal ones)
  - `people` → named individuals (first+last) who are employees or appear in multiple sources
  - `problems` → bugs, risks, blockers, failures, open questions requiring resolution
  - `projects` → named initiatives, programmes, workstreams (ongoing or completed)
  - `systems` → named products, platforms, services, tools owned or operated by your organisation
- **Work through every topic in the order listed above — do not skip any topic.** For each topic, answer its extraction question and act on the result:

  | Topic | Extraction question | Create a page when… |
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
  - For people: only create pages for confirmed employees, or people mentioned in multiple different sources. Require both first and last name (drop both the page and the reference, if incomplete). Ignore titles ("Dr.", "PhD.", "MD.") when parsing names — "John Smith, Dr." is one person named John Smith.
  - Check if the ingestion leads to a contradiction on the page. If ingestion leads to contradictions on a page, clearly mark the contradiction with a short explanation and add frontmatter tag `contradiction: true`.
  - Cross-reference related pages using `[[WikiLinks]]`.
  - **WikiLink rule:** Only WikiLink to a page that (a) already exists in `wiki/`, or (b) you are creating/have created in this same session. If you identify a topic worth referencing but cannot describe it yet, create a minimal stub: frontmatter with `type` and `stub: true`, a `# Title` heading, and one italic line noting the source file. Stubs count as `pages_created` in the session log. Don't add the "stub: true" tag if you were able to generate at least minimal information on the subject.
  - **Stub expansion rule:** Before creating a new page, check if a stub already exists at that path (frontmatter contains `stub: true`). If so, expand it into a full page — remove `stub: true`, fill in proper content, and count it as `pages_updated` (not `pages_created`) in the session log.
- **After finishing all Wiki pages for this note**, verify:
  - Every named system mentioned in the note has a page in `wiki/systems/`.
  - Every named person (first + last name) mentioned in the note has a page in `wiki/people/`.
  - The number of pages touched is reasonable relative to the length and density of the note (a dense meeting note should produce many pages, not one or two).
  - If any of these checks fail, go back and fill in the gaps before moving on.
- Do NOT update `wiki/<topic>/_index.md` during a session (deferred to finalization).
- **After finishing each note's Wiki pages** (immediately, before moving to the next note): append its log entry to the batch log file specified in your prompt. Write one JSON object per line — one for the original file, plus one for each converted markdown file produced from it:
```json
{"date":"YYYY-MM-DD HH:mm:ss","session":1,"file":"raw/notes/filename.md","summary":"One-sentence description.","pages_created":["wiki/concepts/NavSDK.md"],"pages_updated":["wiki/people/Jane Smith.md"]}
```
  The batch log path and session number were given to you in your prompt (e.g. `Write session logs to .import/batch-log-1.jsonl`). Do not wait until all notes are processed — write each entry as you go.
