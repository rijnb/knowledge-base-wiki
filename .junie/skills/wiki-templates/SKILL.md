---
name: wiki-templates
description: Use when creating or structuring a new Wiki page — decisions, systems, people, concepts, competition, conversations, projects, problems, or index files.
---

# Knowledge Base - Page Templates

## Formatting rules

- **Wikilink in body text:** bare WikiLinks — `[[Elastic Map]]`
- **Wikilink in `_index.md` entries:** vault-relative — `[[wiki/systems/Elastic Map]]`
- Never mix formats
- Link sections use bullet lists, not comma-separated inline
- Empty link sections are omitted entirely (e.g. no `## Related decisions` if there are none)
- Always WikiLink any reference to a page, raw note, or person
- YAML frontmatter lists:
  ```
  some-list:
    - item-1
    - item-2
  ```

## Freshness metadata (auto-managed — do NOT hand-edit)

Every content page may carry three machine-managed frontmatter fields:

```
date: YYYY-MM-DD            # page's content date (newest source for a wiki page)
date_span: YYYY | YYYY–YYYY # min–max year of contributing sources (flags era-mixing)
date_confidence: high | medium | low   # low = capture/ingestion date, may overstate freshness
```

These are written and refreshed automatically by `scripts/system/wiki-assign-dates.py`, which `wiki-finalize-ingest` runs after every index rebuild. **Do not set or edit them by hand** — let finalization populate them. When creating a page you may omit them entirely; they will be filled in from the source-note dates at finalize time. (Note: this replaces the older per-type `date: YYYY-MM-DD HH:mm:ss` creation-timestamp convention shown in some templates below — the managed `date` reflects content recency, not creation time.)

## Supersession (when a page is replaced by a newer one)

When a page's content is explicitly superseded by another page (an old architecture replaced by a new one, a decision reversed by a later one, a decommissioned system replaced by its successor), mark the relationship in frontmatter rather than deleting the old page (it stays as history):

```yaml
# on the OLD (superseded) page — the canonical "this is historical" signal:
superseded_by: [[wiki/systems/New Map Pipeline]]   # one link, or a YAML list if split into several
superseded_date: 2022-06-01                          # optional — when it was replaced
tags: [..., superseded]                              # for filtering / graph

# on the NEW (successor) page — reciprocal back-link:
supersedes: [[wiki/systems/Old Map Pipeline]]
```

Rules:
- The **presence of `superseded_by`** is what marks a page as historical — it works on every topic type (people/concepts/competition have no `status` field). Do not encode supersession in the free-text `status` field.
- Always add the reciprocal `supersedes:` on the successor so navigation works both ways.
- The `superseded_by` target **must be an existing page** (no dangling links). Chains are allowed (A→B→C); queries follow them to the newest live page.
- Only assert supersession when a source **explicitly** states the replacement — never guess. Uncertain candidates belong in the lint review queue (see `wiki-doctor`), not applied directly.

## wiki/index.md

Links to section indexes only. Never add individual page entries here.

```markdown
---
type: index
date: YYYY-MM-DD HH:mm:ss
---
# Knowledge Base - index

Topics:
* [[wiki/competition/_index|Competition]] — competing companies, products, and approaches
* [[wiki/concepts/_index|Concepts]] — technologies, standards, mental models, domain vocabulary
* [[wiki/conversations/_index|Conversations]] — valuable results of earlier queries/conversations
* [[wiki/decisions/_index|Decisions]] — why decisions were taken, on what basis, by whom, and when
* [[wiki/people/_index|People]] — colleagues, contacts, external stakeholders, teams
* [[wiki/problems/_index|Problems]] — active and past problems
* [[wiki/projects/_index|Projects]] — active and past initiatives
* [[wiki/systems/_index|Systems]] — our products, platforms, and services
```

## wiki/<type>/_index.md

One per section. Alphabetically sorted. Add one line per new page; update summaries when materially changed.

```markdown
---
type: index
date: YYYY-MM-DD HH:mm:ss
---
# <Type> - index
[[wiki/index|← Index]]

<One-sentence description of what this topic type covers.>

- [[wiki/concepts/isa-regulation|ISA regulation]] — EU ISA mandatory regulation; requires current speed limit data even post-subscription-expiry.

---
[[wiki/index|← Index]]
```

## wiki/decisions/<Page Name>.md

```markdown
---
type: decision
status: accepted | superseded | proposed
date: YYYY-MM-DD HH:mm:ss
systems:
  - system-name
people:
  - person-name
---
# Decision: <title>
## Context
## Concern
## Criteria
## Options
## Decision
## Rationale
## Consequences
## Related decisions
- [[...link (short description of relationship)...]]
## Related systems
- [[...link (short description of relationship)...]]
## Related people
- [[...link (short description of relationship)...]]
## Related notes
- [[...link (short description of relationship)...]]
```

**Rule:** `## Concern` describes the problem only — no solution references. Solutions belong in `## Options`, `## Decision`, `## Rationale`.

## wiki/systems/<Page Name>.md

```markdown
---
type: system
owner:
  - team-name
status: active | deprecated | planned
---
# <System Name>
## What it does
## Interfaces and dependencies
## Known issues and risks
## Related decisions
- [[...link (key-design decisions first)...]]
## Related systems
- [[...link...]]
## Related people
- [[...link...]]
## Related notes
- [[...link...]]
```

## wiki/people/<Page Name>.md

```markdown
---
type: person | team
---
# <Name>
## Role and scope
## Working style and context
## Active on
- [[project-link]]
## Related decisions
- [[...link...]]
## Related systems
- [[...link...]]
## Related notes
- [[...link...]]
```

## wiki/concepts/<Page Name>.md

```markdown
---
type: concept
date: YYYY-MM-DD HH:mm:ss
tags: []
---
# <Concept>
## Short definition
## When it applies
## Explanation of the concept
## Examples in our context
- [[system-link]]
## Related decisions
- [[...link...]]
## Related systems
- [[...link...]]
## Related people
- [[...link...]]
## Related notes
- [[...link...]]
```

## wiki/competition/<Page Name>.md

```markdown
---
type: competitor
---
# <Competitor Name>
## What they do
## Key products and technologies
## How they compare to us
## Related decisions
- [[...link...]]
## Related systems
- [[...link...]]
## Related notes
- [[...link...]]
```

## wiki/conversations/<Page Name>.md

```markdown
---
type: conversation
---
# <Title>
## Summary
## Conversation
## Related
- [[...link...]]
```

## wiki/projects/<Page Name>.md

```markdown
---
type: project
status: active | closed | paused
started: YYYY-MM-DD HH:mm:ss
---
# <Title>
## Project description and goals
## Current state
## Open questions
## Log
<!-- append updates here, newest first -->
## Related decisions
- [[...link...]]
## Related systems
- [[...link...]]
## Related people
- [[...link...]]
## Related notes
- [[...link...]]
```

## wiki/problems/<Page Name>.md

```markdown
---
type: problem
status: open | closed | deferred
started: YYYY-MM-DD HH:mm:ss
---
# <Title>
## Problem statement and goal
## Current state
## Open questions
## Log
<!-- append updates here, newest first -->
## Related decisions
- [[...link...]]
## Related systems
- [[...link...]]
## Related people
- [[...link...]]
## Related notes
- [[...link...]]
```

**Rule:** `## Log` sections are append-only. Add updates here; never modify the rest of the structure.
