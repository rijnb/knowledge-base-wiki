---
name: wiki-ground
description: Use when the user asks to ground this conversation in the knowledge base, says "wiki-ground", asks to treat the KB as source of truth, or wants domain answers backed by the Wiki. Optional topic front-loads relevant knowledge base pages.
argument-hint: "[optional topic to front-load]"
---

# Wiki Grounding

For the remainder of this conversation, treat the knowledge base (KB) as the source of truth for domain facts.

- Before answering any question whose answer materially depends on companies, concepts, conversations, decisions, people, problems, projects, or systems that you are not already certain of from the KB, first invoke `wiki-query`, then answer from what it returns.
- Treat `[[wikilink]]`-style terms and canonical entity names as KB-backed. Do not invent domain facts about them: a known gap is recoverable; a fabricated fact the team trusts is not.
- This is a standing instruction for this conversation, not a one-time lookup.

## Optional Topic

If the user invoked this skill with a non-empty topic, immediately invoke `wiki-query` on that topic to front-load the relevant KB pages, then briefly summarize what you found and wait for the user's next request.

If no topic was supplied, do not query yet. Confirm in one line that knowledge base grounding is active for this conversation, then wait for the user's next request.
