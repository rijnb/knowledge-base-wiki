---
name: work-weekly
description: Use when the user asks for the Monday weekly review, the weekly work review, a weekly planning session, or wants this week's work/weekly/YYYY-Www.md written — scan, triage, and three chosen-work blocks for the week.
---

# Work — Monday Weekly Review

Produce `work/weekly/YYYY-Www.md`: what changed since the last review, what it means for the
current topics, and the three blocks of chosen work for this week. The data is compiled by a
script; the **judgement** — what a new page means and what to do about it — is the work of this
skill.

**Time-box: 30 minutes.** Scan ≤ 10 min, triage ≤ 15 min, commit ≤ 5 min. Going over budget
defeats the purpose; an unfinished section with a named next action beats a complete one written
at 45 minutes.

## 1. Gather (deterministic, ~1 s)

```bash
python3 scripts/work-weekly.py --today <YYYY-MM-DD>
```

Prints the data packet to stdout — do not write it into the vault. Eight sections: `Snapshot`,
`Backlog`, `Stakeholder cadence`, `New on my topics since <date>`, `Unmapped new material`,
`New or changed wiki pages`, `Deadlines and horizon flags`, `Interaction check`. Add
`--since YYYY-MM-DD` to widen the window (default: a week back, or the last review if that is
newer) and `--format json` if you need to post-process.

**If the script exits non-zero, stop.** It exits 2 with a message on stderr when there is no
`work/` tree, no topic pages, or `--today`/`--since` are malformed or out of order. Show the stderr line, say what
would fix it, and stop there — never write a review from an empty packet.

Then read `work/Compass.md` — the review is judged against it, not against the backlog. The file
is git-ignored, so it may well be absent (a fresh clone, or the user has not written one yet).
That is fine and not an error: say so in one line, note the absence once in the review, and judge
against the packet's `Backlog` and `Portfolio` sections instead. Do not create the file and do not
invent its contents.

## 2. Write `work/weekly/YYYY-Www.md`

Use the ISO week of `--today` for the filename (the packet's title line carries the label).
Sections, in this order:

| Section | Content |
|---------|---------|
| `## Snapshot` | **Verbatim** from the packet. `work-backlog.py --recap` parses these lines as start-of-period progress — changing the format breaks recaps. |
| `## Portfolio` | **Verbatim** from the packet's `### Portfolio` block, promoted back to this heading. |
| `## Scan` | The judgement part — see below. |
| `## Stakeholders overdue` | The overdue and never-contacted rows, with the evidence path where there is one — a never-contacted row has no evidence path, and that absence is itself the point. Drop the rows that are merely due later. Rows with no fixed cadence come last in the packet and need no action. |
| `## New on my topics` | Per topic, what actually happened, in your words — not a copy of the file list. A `(via <name>)` annotation means the file matched through one of the topic's `related:` pages rather than by naming the topic itself: check it before believing it. A goal or stakeholder hit is never a file line — it is only ever the `+N weak via goal/stakeholder` count. |
| `## Interaction check` | The pairs and action links that are real, with what to do (usually: add to `related:`). Drop the pairs that share only a broad goal. |
| `## Deadlines` | Deadlines inside six weeks, plus any `horizon: next` topic that should move to `now`. |
| `## Chosen work this week` | Exactly three blocks. Each one **names a topic** and the outcome that ends the block. Not "work on Alpha" — "Alpha: definitions for the three measures written and sent". |
| `## Triage checklist` | The list in step 4, for the user to work through. |

### The Scan section

The material is the packet's `Unmapped new material` and `New or changed wiki pages` sections.
Not every item gets a line — the coverage rule below says which do. Each line that is written
says three things:

1. **What it is** — one clause, from its `description`.
2. **Which existing topics it touches, and how** — the packet's `(title)`, `(related)`, `(goal)`
   and `(stakeholder)` annotations are a *claim*, not a conclusion. `(title)` and `(related)` are
   **strong** touches and usually real; `(goal)` and `(stakeholder)` are **weak** and often mean
   "same corner of the company", which is not an interaction. Say what the interaction actually
   is, or say there is none.
3. **A disposition** — one of `new topic` / `fold into [[X]]` / `watching` / `ignore`.

Order by how many topics an item genuinely touches: a new problem landing on three active topics
outranks a new project landing on none.

Both lists can run long — on an ingest week the wiki list reaches a hundred pages or more. Cover
in full, and only these:

- every item with a **strong touch** on a topic (`(title)` or `(related)`), and
- every **cluster** — two or more items landing on the same topic, or the `2+` link clusters the
  packet names under `Candidate new topics`, which are a signal even when no single item in them
  is. Take the biggest clusters first: five items on one topic says more than two do.

Then summarise the remainder in exactly one counted line:

```markdown
- <n> further items changed with no strong topic touch (ignored)
```

That is a complete answer, not a shortcut. Never list the weak-touch items individually.

**At most ONE candidate gets a bounded dive**, ≤ 10 minutes, via `wiki-query`, and the *user*
picks which. Ask; do not choose for them. Everything else gets its one line.

New topics enter as `status: watching`. A new topic only becomes `status: active` by displacing
an active one — the portfolio cap is 10, and the packet warns above it. Name the topic that would
be parked; do not park it yourself.

## 3. Close

End by printing the `## Portfolio` block in the chat and asking the user to read it aloud once.
That is the point of the review: if a line cannot be said out loud without hedging, its
`progress:` is wrong.

## 4. Triage checklist (the user does this, in the file)

Put this in the weekly file so the user can work down it:

```markdown
- [ ] Tick every action done last week, then run:
      `python3 scripts/work-backlog.py --archive-done <today>`
- [ ] Rewrite `progress:` on every active topic — one sentence, present tense, what is *true* now
- [ ] Set `next_review:` on every topic that has none or has passed
- [ ] Add the `related:` links the interaction check found (both pages)
- [ ] Update `Last` in `work/Stakeholders.md` for anyone contacted since the last review
- [ ] Create the topic pages for the Scan items dispositioned `new topic` (`status: watching`)
- [ ] Recompile: `python3 scripts/work-backlog.py`
```

Run `--archive-done` and the recompile for the user when they ask; never before they have ticked
the boxes, because archiving is a rewrite of the topic pages.

## Rules

- **Never edit a topic page in this skill.** The packet is read-only, the weekly file is the only
  thing written, and topic pages change through the triage checklist (or the user's own hand).
- Write only `work/weekly/YYYY-Www.md`. One file per ISO week; re-running in the same week
  updates that file rather than creating a second one.
- Wikilink targets are exact filenames with spaces — `[[Some Topic]]`, never `[[Some-Topic]]`.
- No invented facts. Everything in the review traces to the packet, to `work/Compass.md` where it
  exists, or to the one `wiki-query` dive.

## Common mistakes

| Mistake | Fix |
|---------|-----|
| Reformatting `## Snapshot` | Copy it verbatim; `--recap` parses it |
| Treating a weak `(stakeholder)` touch as an interaction | Two topics sharing one busy person is not a dependency — say so and move on |
| Diving into three interesting candidates | One dive, ≤ 10 min, the user picks |
| Listing all hundred changed wiki pages in full | Cover the strong touches and the clusters, count the rest in one line |
| Stopping because `work/Compass.md` is missing | It is git-ignored and optional — note its absence and judge against the backlog |
| Writing a review after the script exited non-zero | Show stderr, name the fix, stop |
| Five chosen-work blocks | Three. The fourth is next week's problem |
| Writing the packet into the vault | It is stdout; the review is the artifact |
| Editing topic pages to "help" | That is the user's triage step |
