---
name: write-article
description: Use when the user asks to write, draft, or produce an article, blog post, explainer, or long-form piece — "write an article about...", "draft a post on...", "turn this research into an article". Combines vault knowledge with web research into a footnoted, publication-quality article.
---

# Write Article

Produce a publication-quality article grounded in verifiable facts from the vault and the web. Interview the user first, research before outlining, let the user choose what gets visualized, and end the article with a self-critical weaknesses section.

**Core principle: every load-bearing claim carries a footnote to a verifiable source. No source → soften the claim or cut it.**

## Workflow — phases in order, no skipping

### Phase 1 — Grill the user

Interview the user (the `grill-me` pattern, self-contained here): **one question at a time**, each with your recommended answer, walking down the decision tree until shared understanding. If a question can be answered by searching the vault, search instead of asking.

If the user declines the interview ("just write it", "I'm in a hurry"): do not skip the items — compress them. Present your recommended answers to all seven items in a single message and ask for one confirmation. The Phase 3 gate still applies but may likewise be a single combined confirmation.

If the user volunteers a visual in the request ("with a diagram of X"): record it as a Phase 3 candidate. It still gets confirmed after research alongside the other candidates — research may reveal a better cut of the same concept.

Resolve at minimum:
1. **Topic and working thesis** — what is the one arguable sentence the article defends?
2. **Audience** — who reads it, what do they already know?
3. **Purpose** — inform, persuade, propose action? What should the reader *do* after reading?
4. **Register** — practitioner/opinionated (default, matches the exemplars) vs neutral/expert.
5. **Length target** — default 1,500–3,500 words; news-item ≥1,000; tutorial can run longer.
6. **Must-use sources** — vault notes, URLs, talks the user wants incorporated or credited.
7. **Publication target** — internal note, Confluence, external blog (affects tone and what may be disclosed).

Do NOT ask about visualizations yet — that comes after research (Phase 3), when you know the content.

### Phase 2 — Research

Vault first, then web:
- **Vault:** follow the `wiki-query` skill (QMD search, freshness re-rank, provenance rules). Respect `date` / `date_confidence` / `superseded_by` frontmatter.
- **Web:** `WebSearch` to find sources; the `obsidian:defuddle` skill to read specific URLs cleanly. Prefer primary sources (papers, official docs, the original talk/post) over aggregators.

Build a **fact sheet**: one line per fact — claim, source (URL or vault note), source date, confidence. Keep it in the conversation (or the session scratchpad for long jobs) — it is working material, not a vault file. Flag facts that rest on a single source or on stale/low-confidence vault pages; these feed the weaknesses section in Phase 5.

If research contradicts the working thesis, stop and tell the user before writing.

### Phase 3 — Outline and visualization grilling

Present to the user:
1. A **section outline** where every heading is a full arguable claim (see Style contract).
2. The fact-sheet highlights: the 3–5 strongest facts/numbers and any gaps.
3. **Visualization candidates**: concepts from the research that are genuinely complex — multi-step flows, architectures, feedback loops, side-by-side contrasts. For each candidate say what the diagram would show and why prose alone falls short.

Then ask the user **exactly which concepts to visualize** (possibly none). Only user-approved concepts become diagrams. Do not invent diagrams for simple ideas — a comparison of two things is usually a table, not a picture.

Wait for approval of outline + visual choices before writing.

### Phase 4 — Write the article

Follow the Style contract, Grounding rules, and Visuals rules below. Write to `INBOX/YYYY-MM-DD Title.md` (today's date; plain readable title — spaces, no slugs, no diacritics, no `: / \ * ? " < > |`).

Frontmatter (matches authored INBOX notes):

```yaml
---
tags: [article, <topic-tags>]
date: YYYY-MM-DD
author: "[[Rijn Buve]]"
description: "<the article's dek — one sentence>"
source: "<[[wikilink]] or URL of the primary source, if one dominates>"
---
```

### Phase 4a — End-of-article marker

Directly after the closing synthesis paragraph, insert a clear marker separating the readable article from the review/reference apparatus:

```markdown
---

*— End of article. The sections below are review aids and references. —*
```

Everything after the marker, in this order: `## Potential Weaknesses`, `## Heading Alternatives`, footnote definitions. The marker stays in internal notes; when publishing externally or to Confluence, ask the user whether the apparatus (marker + weaknesses) ships or gets cut.

### Phase 4b — Heading alternatives table

After Potential Weaknesses (and before the footnote definitions), append a section `## Heading Alternatives` — a working aid for the user, removed once headings are settled:

```markdown
## Heading Alternatives

> [!note] Working aid — reply e.g. "headings: 1b, 2a, 4c" (unmentioned numbers keep the current heading) and I'll apply them and delete this section. "Keep headings" deletes it as is.

| # | Current | a — Short claim | b — Imperative | c — Plain |
|---|---|---|---|---|
| 1 | <current H2> | ... | ... | ... |
```

- One row per `##` body section (skip Potential Weaknesses and this section itself).
- At least 3 alternatives per heading, one per column flavor: **a** short claim, **b** imperative, **c** plain/descriptive noun-ish (still specific, never "Background").
- Alternatives must be shorter or easier to scan than the current heading, not synonyms of equal weight.
- When the user replies with picks (in any wording — "1c, 2a", "use column b", "keep 3, rest plain"), apply the chosen headings and **delete the whole section**. It must not survive into a published or final article.

### Phase 5 — Weaknesses section and delivery

Append `## Potential Weaknesses` directly after the end-of-article marker (omit only if there truly are none — rare). Present it as a **table with unique IDs** so the user can refer to entries in later prompts ("address W3", "W2 is acceptable, drop it"):

```markdown
## Potential Weaknesses

| ID | Section | Kind | Weakness |
|---|---|---|---|
| W1 | <heading it concerns> | Single-source | <one sentence, cite the footnote number> |
```

- IDs are `W1`, `W2`, … in article order; never renumber existing IDs when editing the article later (a resolved weakness's row is deleted or marked, not recycled).
- **Kind** is one of:
  - **Single-source** — a load-bearing fact with only one source (cite the footnote number).
  - **Stale source** — vault page older than ~2–3 years, `date_confidence: low`, or superseded.
  - **Extrapolation** — the article generalizes beyond what the source measured.
  - **Counterargument** — the strongest objection the article does not rebut.
  - **Gap** — what the research could not confirm.
- When the user later addresses a weakness by ID (e.g. "fix W3", "add a rebuttal for W4"), update the relevant article section and then update the table: delete the row if fully resolved, or reword it if only narrowed. Keep the remaining IDs unchanged.

Deliver: tell the user the file path, the word count, which concepts were visualized, repeat the weaknesses table in chat (with IDs), and remind them they can pick heading alternatives by replying like "headings: 1b, 2a" and address weaknesses by ID ("fix W3"). The article always lands in `INBOX/` first; if the Phase 1 publication target is Confluence, offer to publish it there (Atlassian MCP tools) after the user has reviewed the INBOX draft — never publish externally without explicit go-ahead.

## Style contract

The contract below is self-contained — follow it without reading the exemplars. It was distilled from 25 well-produced clips in `raw/clips/`; consult these only when a rule needs a live example (skip silently if moved/deleted):
- Section architecture + FAQ close: `raw/clips/2026-08-26 How Uber built a software factory for agentic coding the MCP gateway and the platform underneath.md`
- Vignette/roadmap opening: `raw/clips/2026-07-22 Harness Engineering Multi-Agent Orchestration When to Split the Agent, and How Not to Pay 15x for It -VI.md`
- Closing checklist + side-by-side synthesis: `raw/clips/2026-08-25 CrewAI VI Remembering Is Not the Same as Knowing How CrewAI Memory and Knowledge Actually Differ.md`

- **Title as `# H1`**, then a **thesis dek**: one bold full-sentence claim directly under the title — an argument, not a label.
- **Lede = concrete scene or striking fact**, never throat-clearing. A named-character failure vignette or a precise number ("$122k/month of token spend") that the article then explains.
- **Roadmap early**: after the lede, 3–5 bullets or one paragraph saying what the piece answers.
- **Headings are full claims or imperatives**, flat `##` hierarchy (occasional `###`): "Route every tool through one MCP gateway", not "MCP Gateway". Test: the article must be reconstructable from headings alone.
- **Mechanism → plain words → analogy**: after each technical claim, an "In other words..." restatement; dry wit via analogy, not jokes.
- **Concrete numbers over adjectives**: every big claim carries a measured quantity. "15x tax", not "much more expensive".
- **One controlling metaphor** introduced near the title and paid off in the final line.
- **Second person for the reader, first person for lived experience.** Short declarative sentences for punch, longer for mechanism.
- **Tables for side-by-side contrasts**; short, commented, runnable code fences where code helps.
- **Closing arc**: a "Do this today" checklist of 3–5 small imperatives, then a synthesis paragraph restating the thesis with a memorable line.
- **Credit block** when the material is substantially someone else's talk/paper: "Credit: ... The numbers and design calls are all theirs."

## Grounding rules

- Cite with **Markdown footnotes `[^1]` at the point of claim** — the marker sits on the sentence that makes the claim, like the exemplars' inline links.
- Footnote text (all collected at the very end of the file, after Potential Weaknesses and Heading Alternatives — Obsidian renders footnotes at the bottom regardless of where the definitions sit):
  - Web: `[^1]: [Article title](https://url) — Publisher, YYYY-MM-DD.`
  - Vault: `[^2]: [[Exact Note Filename]] — vault note, dated YYYY-MM-DD.` A wikilink target is the note's exact filename as it exists on disk — copy it verbatim from the QMD result or `ls`. Vault filenames use **spaces**; do not convert them to hyphens, ever. If you find yourself writing `[[Some-Hyphenated-Name]]`, you have slugified: stop and copy the real filename.
- **Mandatory before delivery: verify every `[[wikilink]]` in the article resolves.** For each target run `find raw wiki INBOX -name "<target>.md"` (or check the QMD `get` path). A miss means you invented or slugified the name — fix it from the filename on disk. Do not rationalize a miss ("the vault must be hyphen-named"); the filesystem is the authority.
- Every number, quote, and non-obvious factual claim gets a footnote. Opinions and synthesis need none but must read as the author's, not as fact.
- Note stale sources in the footnote itself: `(as of 2023 — may be outdated)`.

## Visuals rules

- **Mermaid only** (renders natively in Obsidian, no plugins, editable).
- Only user-approved concepts from Phase 3.
- Place each diagram inside the section that explains it, with an italic caption line beneath: `*Figure N: what the reader should see in it.*`
- Keep diagrams legible: at most 12 nodes, short labels, one idea per diagram. If it needs more, split it or cut it.
- Pick the diagram type for the mechanism: `flowchart` for flows/architecture, `sequenceDiagram` for interactions over time, `stateDiagram-v2` for lifecycles.
- Syntax check each diagram against the common breakers: no bare `end` as a node ID, quote labels containing `(){}[]|` or `:`, no leading/trailing spaces in node IDs, `%%` for comments. If the Obsidian CLI is available, open the note to confirm it renders.

## Common mistakes

| Mistake | Fix |
|---|---|
| Asking about visuals during Phase 1 | You can't know what deserves a diagram before researching. Ask in Phase 3. |
| Treating a user-volunteered diagram as pre-approved | It's a Phase 3 candidate like any other — confirm it after research. |
| Reading "just write it" as approval of an outline the user hasn't seen | Compress the gates to single confirmations, but never remove them. |
| Noun-phrase headings ("Background", "Architecture") | Rewrite every heading as a claim or imperative. |
| Claims with adjectives instead of numbers | Find the number in research, or footnote-flag it as unquantified. |
| Footnoting a vault page with a slugified wikilink | Use the exact filename with spaces (`[[Model Context Protocol]]`, not `[[Model-Context-Protocol]]`) and verify it exists on disk before delivery. |
| Diagramming a simple comparison | Use a table. Diagrams are for mechanisms, flows, structures. |
| Skipping the weaknesses section because the article "feels solid" | The fact sheet flags from Phase 2 always yield at least single-source or extrapolation entries; if genuinely none, say so explicitly to the user. |
| Writing before the user approves outline + visuals | Phase 3 approval is a hard gate. |
| Leaving the Heading Alternatives table in a final/published article | It is a working aid — delete it when the user picks headings (or says to keep them). |
