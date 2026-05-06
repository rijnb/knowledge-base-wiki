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
