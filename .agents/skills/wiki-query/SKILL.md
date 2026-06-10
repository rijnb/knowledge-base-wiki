---
name: wiki-query
description: Use when the user asks any question, requests research, or wants information from the knowledge base. This is the default action in this repository — when in doubt, search the Wiki. Use for "find me...", "what do we know about...", "tell me about...", "who is...", "what is...", or any general research question.
---

# Knowledge Base - Query

When the user asks any question:

- Search the QMD collection `tomtom`, which indexes the whole vault root. Use QMD MCP `query`/`get`/`multi_get` tools when available; otherwise use the `qmd` CLI (`qmd query`, `qmd get`, `qmd multi-get`). **Over-fetch** — ask for more candidates than you need (≈12–15) so the recency re-rank below has room to work.
- Retrieve the candidates before answering. **Always read each page's `date` / `date_confidence` frontmatter** when you retrieve it (QMD ranks by relevance only — it does NOT know about dates).
- **Recency re-rank (soft tiebreaker).** QMD ordering is pure relevance. Before answering, re-order the candidates yourself:
  - Relevance still dominates. Apply only a **mild** penalty for age, and only as a tiebreaker among results of *similar* relevance — prefer the page with the newer `date`.
  - **Never drop the only source on a topic** just because it is old, and don't penalise low-relevance-but-unique evidence.
  - **Skip the penalty for historical questions** ("what was the original…", "who led X in 2015", "history of…") — there, old pages are the right answer.
  - When two candidates cover the same fact, lead with the newer one and note the older as historical.
- If QMD returns no results, fall back to reading `wiki/<type>/_index.md` directly, or `wiki/index.md` for top-level navigation.
- Synthesize an answer with citations: `[[wiki/decisions/title]]`, `[[wiki/systems/name]]`, etc.

## Freshness awareness (IMPORTANT)

This Wiki was built from notes going back to ~2006, so it mixes current and long-outdated information. Both wiki pages and `raw/` source pages carry freshness metadata in frontmatter — **always read it and weigh it before trusting a claim**:

- `date: YYYY-MM-DD` — the page's content date. For a wiki page, the newest source feeding it (best "as of" signal); for a raw page, the artifact's own date.
- `date_span: YYYY` or `YYYY–YYYY` — a wide span means the page **mixes eras**; old and new facts sit side by side.
- `date_confidence: high | medium | low` — `low` means the date is only a capture/ingestion date (e.g. an old document scanned recently) and may **overstate** freshness; treat such dates skeptically.

Rules when answering (today's date is available in context):
1. **Surface the date.** State the "as of" date for time-sensitive facts: "As of 2024 (per the page's `date`)…". Never present dated info as if it were necessarily current.
2. **Flag stale data.** If `date` is more than ~2–3 years old, explicitly warn that it may be outdated and worth verifying — especially for org structure, people's roles, projects, systems, and decisions.
3. **Prefer newer on conflict.** When two pages/sources disagree, trust the one with the more recent `date` and say which you chose and why. Note `status: superseded` / `deprecated` pages as historical.
4. **Distrust low confidence.** For `date_confidence: low`, caveat that the date is uncertain.
5. **Call out era-mixing.** For a wide `date_span`, separate "historically" from "more recently" rather than blending them.
6. **Unknown freshness.** If a page has no `date` field, its recency is unknown — say so rather than assuming it is current.

Prefer recent sources when gathering evidence, but don't discard old pages — they're valuable for history, just label them as such.

## Supersession (explicit replacements)

Some pages are explicitly marked as replaced by a newer page via frontmatter:

- `superseded_by: [[wiki/...]]` — this page is **historical**; the linked page is its replacement.
- `supersedes: [[wiki/...]]` — this page replaces an older one.

When a retrieved page has `superseded_by`:
1. **Follow the link** (and any chain — A→B→C) to the newest live page and answer from **that**, not the superseded one.
2. Use the superseded page only for history ("Previously X did this until ~2022; it was superseded by [[New Thing]]"). Never present superseded content as the current state.
3. If the user explicitly asks about the old thing or its history, describe it and note it's superseded.

This is a stronger signal than `date`: a superseded page may still be recent, but it has been deliberately retired.

Follow-up:
- If the answer seems to be a valuable artifact (analysis, full recap, comparison, non-obvious connection between pieces of information), propose filing it as a new page in `wiki/conversations/` and updating the index. In that case, the title of the new page should be descriptive and include the date, e.g. `wiki/conversations/YYYY-MM-DD Descriptive Page Title For Discussion.md`.
- Include the page in the index, with a one-liner summary of the content.
