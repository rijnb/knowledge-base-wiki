---
name: wiki-query
description: Use when the user asks any question, requests research, or wants information from the knowledge base. This is the default action in this repository — when in doubt, search the Wiki. Use for "find me...", "what do we know about...", "tell me about...", "who is...", "what is...", or any general research question.
---

# Knowledge Base - Query

When the user asks any question:

- Use `mcp__plugin_qmd_qmd__query` to search across Wiki collections: `concepts`, `decisions`, `people`, `systems`, `competition`. For broad questions, also search `notes`.
- Use `mcp__plugin_qmd_qmd__get` or `mcp__plugin_qmd_qmd__multi_get` to retrieve documents identified in step 1.
- If QMD returns no results, fall back to reading `wiki/<type>/_index.md` directly, or `wiki/index.md` for top-level navigation.
- Synthesize an answer with citations: `[[wiki/decisions/title]]`, `[[wiki/systems/name]]`, etc.

Follow-up:
- If the answer seems to be a valuable artifact (analysis, full recap, comparison, non-obvious connection between pieces of information), propose filing it as a new page in `wiki/conversations/` and updating the index. In that case, the title of the new page should be descriptive and include the date, e.g. `wiki/conversations/YYYY-MM-DD Descriptive Page Title For Discussion.md`.
- Include the page in the index, with a one-liner summary of the content.
