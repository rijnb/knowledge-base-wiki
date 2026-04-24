---
name: knowledge-base-health-check
description: Use when the user asks for a health check, lint, audit, or wants to check for orphan pages, contradictions, or data gaps in the wiki.
---

# Knowledge Base - Health Check

When the user asks for a health check or lint:

1. **Orphan pages** — pages with no inbound `[[links]]` from other pages (links from `index.md` or `_index.md` are fine).
2. **Contradictions** — scan for conflicting facts within and between pages (introduced by successive ingestions).
3. **Missing dedicated pages** — topics mentioned across multiple pages that lack their own page.
4. **Missing top-level topics** — if 10+ pages relate to a common concept not listed as a top-level topic in `wiki/index.md`, suggest adding it.
5. **Data gaps** — suggest new sources worth finding.

**Rule:** Never modify the wiki during a health check without user confirmation. Present recommendations only.
