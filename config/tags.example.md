---
description: "Example tag vocabulary. Copy to config/tags.md and replace with your own."
---
# Tags

**Example file.** Copy it to `config/tags.md` and fill it with your own
vocabulary. `config/tags.md` is deliberately untracked: a real vocabulary
names your own systems, projects and customers.

To build one, use `scripts/wiki-tags.py` — `--phase inventory` to see the tags
you already have, then `--phase namespaces`, `--phase taxonomy` and
`--phase terms` to propose a hierarchy. Review `.tags/tags.md` and copy it
here. `INBOX/Tagging New Notes.md` documents the whole loop.

## How to use it

When tagging a note, pick from this list. If nothing here fits, **add the
tag to this list first**, then use it — so this file stays the single
source of truth and `wiki-doctor` can check against it.

Removing a tag from this list does not remove it from notes: the tagging
scripts never strip a tag. That needs a remap run.

## Rules

- lowercase; `namespace/term` or `namespace/term/term`. Never 1 segment, never 4.
- hyphens inside a segment (`code-review`), never underscores or spaces.
- English, always.
- Never a person's name. Never a bare company name — a customer programme
  is `project/<name>`.
- `year/YYYY` is the one exempt pattern.

## Shape

One `## <namespace>` section per namespace, holding its tags as list items:

```markdown
## process

- `process/code-review`
- `process/testing`

## year

- `year/2026`
```

Only list items under a `## <namespace>` heading are read as vocabulary, and a
tag must sit under its own namespace's heading — so the prose above is safe, and
a tag filed under the wrong heading is ignored rather than silently accepted.

