---
name: wiki-add-missing
description: Use when the user notices a system, concept, person, project, decision, competitor, or problem is missing from the Wiki and wants to create a page for it.
---

# Wiki — Add Missing Page

Follow this workflow step by step. Do not skip steps or batch them together.

---

## Step 1 — Choose topic type

Use `AskUserQuestion` with `type: single_choice` to ask:

> "Which topic type does this page belong to?"

Present these options:
- `competition` — competing companies, products, and approaches
- `concepts` — technologies, standards, mental models, domain vocabulary
- `decisions` — why decisions were taken, on what basis, by whom, and when
- `people` — colleagues, contacts, external stakeholders, teams
- `problems` — active and past problems
- `projects` — active and past initiatives
- `systems` — our products, platforms, and services

---

## Step 2 — Name and description

Use `AskUserQuestion` (free text) to ask:

> "What is the name and a one-sentence description of the missing page?
>
> Example: Name: NDS.Live / Description: The tile and layer-based streaming format of NDS used for real-time map data delivery."

Parse the response to extract:
- **name** — the page title (used verbatim as the filename and H1)
- **description** — one-sentence summary (used in the index entry and to guide search)

---

## Step 3 — Related search terms

Use `AskUserQuestion` (free text) to ask:

> "List any related terms, acronyms, aliases, or people that should be searched to find relevant notes (comma-separated).
>
> Example: NDS, tile streaming, LiveMap, HERE HD Live, map tiles"

Combine these terms with the name and description from Step 2. You will use all of them in the searches below.

---

## Step 4 — Search and collect

Run **parallel** QMD searches to gather all potentially relevant content. Cast a wide net.

### Searches to run (all in parallel):

**Lexical (lex) searches** — exact keyword matches:
- Query: the page name
- Query: each related term from Step 3 (one query per term or combined)

**Semantic (vec) searches** — meaning-based:
- Query: the description from Step 2
- Query: "what is [name] and how does it work"
- Query: each related term phrased as a concept

**Hypothetical document (hyde) search**:
- Query: write a short paragraph describing what an answer about [name] would look like

**Collections to search** (include all):
- `raw-notes` — primary source (2700+ meeting notes, documents)
- `raw-emails` — email threads
- `raw-scans-transcribed` — scanned/transcribed documents
- `raw-confluence` — Confluence pages
- `wiki-concepts`, `wiki-systems`, `wiki-decisions`, `wiki-people`, `wiki-competition`, `wiki-projects`, `wiki-problems` — existing Wiki pages

Use `minScore: 0.5` to filter noise. Use `intent` on every call to improve snippet relevance (set intent to the description from Step 2).

### After searching:
- Retrieve full content of the top-scoring hits using `mcp__plugin_qmd_qmd__get` or `mcp__plugin_qmd_qmd__multi_get`.
- Apply your own insight: think about what adjacent concepts, systems, or people might relate to this topic and run additional targeted searches for those too.
- Collect all source file paths (for citation).

---

## Step 5 — Synthesize and write the page

**REQUIRED BACKGROUND:** Invoke `wiki-templates` for all page templates and formatting rules before writing the page.

Apply the correct template for the chosen topic type. Fill every section with synthesized content from Step 4. Omit any section for which no relevant information was found.

Additional rule: cite sources inline: `Source: raw/notes/2024-03-15 Meeting.md`

Write the completed page to: `wiki/<topic>/<Name>.md`

Use today's date for the `date` field.

---

## Step 6 — Add backlinks

For each page listed in the new page's Related sections:

1. Read the existing page.
2. Find the relevant Related section (e.g. `## Related concepts`, `## Related systems`, `## Related people`).
3. If the new page is not already linked there, add a WikiLink entry: `- [[<new-page-slug>]]`
4. If the section doesn't exist yet, add it before `## Related notes` (or at the end if that section is absent).

Do not modify any other content of those pages.

---

## Step 7 — Update the index

Run the index-page script from the project root to rebuild all topic indexes:

```bash
python3 scripts/wiki-create-index-pages.py
```

---

## Step 8 — Report

After completing all steps, report to the user:
- The path of the new page created
- The number of source documents used
- The pages that received backlinks
- Any sections left empty due to insufficient information
