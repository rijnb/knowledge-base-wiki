---
name: knowledge-base-query
description: Use when the user asks any question, requests research, or wants information from the knowledge base. This is the default action in this repository — when in doubt, search the wiki. Use for "find me...", "what do we know about...", "tell me about...", "who is...", "what is...", or any general research question.
---

# Knowledge Base - Query

When the user asks any question:

1. Use `mcp__plugin_qmd_qmd__query` to search across wiki collections: `concepts`, `decisions`, `people`, `systems`, `competition`. For broad questions, also search `notes`.
2. Use `mcp__plugin_qmd_qmd__get` or `mcp__plugin_qmd_qmd__multi_get` to retrieve documents identified in step 1.
3. If QMD returns no results, fall back to reading `wiki/<type>/_index.md` directly, or `wiki/index.md` for top-level navigation.
4. Synthesize an answer with citations: `[[wiki/decisions/title]]`, `[[wiki/systems/name]]`, etc.
5. If the answer is a valuable artifact (analysis, full recap, comparison, non-obvious connection), propose filing it as a new page in `wiki/conversations/` and updating the index. The title should be descriptive and include the date, e.g. `wiki/conversations/2024-06-01-analysis-of-competitor-x.md`. Include a summary of the content in the index for discoverability.