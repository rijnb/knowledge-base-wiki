---
name: wiki-find
description: Use when the user wants a list or inventory of all notes about, on, related to, or relevant to a subject — "find all notes about X", "which pages cover X", "list everything we have on X", "what notes are relevant to X". Not for answering a question about X (that is wiki-query).
---

# Wiki — Find All Notes on a Subject

Goal: a **complete** list of wiki pages relevant to a subject, cheaply. The per-type `wiki/<type>/index.md` files (one line per page: link, title, one-line description) and the frontmatter `tags:` are the primary signal; page bodies and semantic search only fill gaps. Never grep the ~7k pages yourself — the script does the scanning in under a second.

## Steps

### 1. Expand the subject into terms

Write 6–12 search terms before running anything:

- the subject as phrased, plus singular/plural and hyphenated forms (tags are hyphenated: `agentic-coding`)
- synonyms and near-synonyms the vault would use
- acronyms and product/tool/vendor names that imply the subject
- the likely `tags:` spellings

Prefer distinctive multi-word terms. A lone generic word (`agent`, `map`, `data`) matches half the vault — pair it or drop it.

Example, subject "agentic coding":
`agentic coding, agentic-coding, coding agent, coding agents, coding-agent, agentic sdlc, claude code, cursor, codex, copilot, vibe coding, harness engineering`

### 2. Run the finder

```bash
python3 scripts/wiki-find.py "<comma-separated terms>" --out <scratchpad>/find-<subject>.md
```

Default = index pass (title, filename, description) + tags pass. Always pass `--out`: a broad subject yields 200+ lines (50+ KB), which overflows the terminal; stdout then carries only the summary line, and you read the file once. Flags:

| Flag | Use when |
|------|----------|
| `--body` | fewer than ~15 hits, or a niche subject whose pages rarely carry it in title/description/tags |
| `--types concepts,systems` | the user scoped the request to some topic types |
| `--format json` | you need to post-process (e.g. merge with QMD hits) |
| `--out FILE` | always; write the list to a file, print only the summary |
| `--no-pages` | index-only quick look |

Output is Markdown grouped by type, in `wiki/index.md` order. Tag- and body-only hits are annotated `(tags: …)` / `(body: …)` so you can judge them.

### 3. Fill semantic gaps with QMD

Run one `vec` and one `hyde` query (collection `tomtom`, ~20 results, `intent` set to the subject). Add any `wiki/…` page not already in the list. Skip `raw/` hits — this skill lists wiki pages.

Expect low yield (typically 0–5 new pages); it is two calls, so run it anyway. QMD may return hyphenated paths (`wiki/systems/Claude-Code.md`) for files that are really `Claude Code.md` — resolve each new hit to the actual filename with `ls` before linking it.

### 4. Prune false positives

Scan titles and descriptions. Drop a page when the term is incidental (`cursor` inside "precursor", `copilot` meaning Microsoft 365 Copilot, `harness` in a test-rig page). Open a page only when its description is ambiguous or useless (stubs and provenance-only pages carry descriptions like "minimal provenance stamp only" — judge those by title, or open them); keep that to ~10 pages, frontmatter only. When in doubt, keep it and say so.

### 5. Deliver the full list

The deliverable is the list. Its shape:

1. One line: total count, and the terms used.
2. Sections per topic type in `wiki/index.md` order (Competition, Concepts, Conversations, Decisions, People, Problems, Projects, Systems), each headed `## <Type> (<n>)`.
3. One entry per page: `- [[wiki/<type>/<Exact Filename>|<Title>]] — <one-line description>`. Wikilink targets are exact filenames with spaces — never slugified, never hyphenated. Drop the finder's `(tags: …)` / `(body: …)` annotations; they are for your pruning, not the reader.
4. Every page you kept appears. A list of 300 is 300 lines; "and ~40 more" is not a list. Above ~80 entries, file the list (step 6) without waiting for a yes, and paste only the per-type counts plus the file path in chat.

### 6. Offer to file it

A subject inventory is a useful artifact. Offer to save it as `wiki/conversations/YYYY-MM-DD Notes on <Subject>.md` (frontmatter per the `wiki-templates` skill, body = the pruned list) and add a one-line entry to `wiki/conversations/index.md`. Do this when the user says yes, or immediately when the list exceeds ~80 entries.

## Common mistakes

| Mistake | Fix |
|---------|-----|
| Grepping `wiki/` with several `grep -ril` rounds | Run `scripts/wiki-find.py` once; it reads indexes + tags in <1 s |
| Treating QMD's top 10 as the complete set | QMD ranks, it does not enumerate; it is the gap-filler, not the primary pass |
| Truncating the list ("+ ~12 more") | Deliver every entry, or file the list and report counts |
| Single-term search | Expand to 6–12 terms first; tags need hyphenated spellings |
| `[[Agentic-Coding]]` style links | Use the exact filename: `[[wiki/concepts/Agentic Coding|Agentic Coding]]` |
| Answering the question about the subject | That is `wiki-query`; this skill lists pages |
