---
name: work-topic
description: Use when the user wants to add a new work topic, open a topic page, start tracking a piece of work, says "new topic", "add a topic", "track this", or asks to create work/topics/<Topic>.md — interviews them, then writes the page.
---

# Work — Add a Topic

Interview the user about one new subject, then write `work/topics/<Topic>.md` yourself. The
point of the interview is that a topic page is only useful if its `progress:` sentence and its
next action are real; a page created from a title alone becomes a stub nobody revisits.

**Time-box: 3 minutes.** Six questions, most with a proposed answer the user can accept. Never
ask something the vault can answer.

## 1. Read the context first

Before asking anything:

```bash
ls work/topics/
grep -h "^status:\|^horizon:" work/topics/*.md | sort | uniq -c
sed -n '1,40p' work/Compass.md
```

That gives the existing topics (so you can spot a duplicate or a parent), the current
portfolio load, and the mandate/lever/outcomes the new topic should hang off.

**Check for an existing home before proposing a new page.** If the subject looks like part of a
topic that already exists, say so and ask whether to fold it in instead — a section and a log
line on the existing page beats an eleventh topic. Adding to the portfolio is the costly option.

## 2. Interview

Ask with `AskUserQuestion` where the options are genuinely discrete, otherwise plain prose. Lead
each question with your proposed answer drawn from step 1, so the user usually just confirms.

1. **What is the subject?** One line. From it derive the page title in Title Case — the filename
   rule is plain readable text, no slugs, no accents, and none of `: / \ * ? " < > |`.
2. **Is this really new,** or part of `[[Existing Topic]]`? (Skip if step 1 found no candidate.)
3. **`status`** — `watching` for something you are only keeping an eye on, `active` for work you
   are actually doing now. **Default to `watching`** and say why: the portfolio cap is 10 active
   topics, and `work-backlog.py` warns above it. If the user wants `active` while already at the
   cap, say which topic that implies parking and let them choose — do not park one yourself.
4. **`horizon`** — `now`, `next` or `later`. Only meaningful for `active`; ask only then.
5. **`progress`** — one sentence on where the subject stands *today*. Push for a fact, not an
   intention: "Dry-run held 2026-09-10; my checkpoints not yet agreed" is useful,
   "getting started" is not. This is the field the weekly review rewrites and the backlog shows.
6. **The next action, and who owns it** — yours (`## Next actions (me)`) or someone else's
   (`## Delegated`, as `- [ ] @Name — …`). An `active` topic with no next action is reported as
   a smell by the compiler, so get one or ask the user to accept `watching` instead.

Then propose, without asking separately — the user corrects if wrong:

- **`goal`** — the Compass outcome it serves, as a wikilink. Omit rather than invent one.
- **`stakeholders`** — names already in `work/Stakeholders.md`, as wikilinks. Only people who
  genuinely need something from the user on this subject.
- **`related`** — existing topic pages it touches, as wikilinks.
- **`lever`** — copy the value used by the topics it sits closest to.
- **`next_review`** — a date. Default two weeks out for `active`, six for `watching`.
- **`deadline`** — only if the user named one. It surfaces in the backlog within 42 days.

## 3. Write `work/topics/<Title>.md`

```markdown
---
type: topic
status: watching
horizon: later
lever: throughput
goal: "[[Some Compass Outcome]]"
stakeholders: ["[[Person One]]"]
progress: "One factual sentence about where this stands today."
next_review: 2026-10-30
related: ["[[Adjacent Topic]]"]
date: <today>
---
# <Title>

## Why it matters

Two or three sentences: why this is on the radar at all, and what changes if it goes well or badly.

## My role

What the user actually does here — sponsor, decider, reviewer, doer. Being explicit about this
is what stops a topic quietly becoming someone else's work on the user's list.

## Next actions (me)

- [ ] <the next action>

## Delegated

- [ ] @Name — <what they owe>

## Log

- <today> — topic opened
```

Rules that matter:

- **`type: topic` is mandatory.** Without it the compiler skips the file and the topic silently
  never appears in the backlog.
- Only the four `##` sections above are parsed — `Next actions (me)`, `Delegated`, `Log`, and
  (on weekly files) `Snapshot`. Any other section you add is ignored by the compiler, so the
  page can carry its own tables and notes freely.
- Omit `## Delegated` items entirely rather than writing a placeholder; `- (none)` is what the
  compiler prints, not what the page should say.
- Leave a field out rather than guessing it. An absent `goal` is honest; a wrong one misroutes
  the weekly review.
- Never write `work/Backlog.md` — it is compiled.

## 4. Regenerate and report

```bash
python3 scripts/work-backlog.py
```

Then tell the user, in three lines:

- the path written, and the `status` / `horizon` it went in as;
- the new active-topic count against the cap of 10, if the topic is `active`;
- anything the compiler now reports about the page — a missing `progress`, no next action, a
  malformed `next_review`. Fix it there and then rather than leaving it for Monday.

If the user declined to give a `progress` sentence or a next action, say plainly that the page is
a stub and what is missing, rather than presenting it as done.
