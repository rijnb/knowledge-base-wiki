---
name: work-brief
description: Use when the user asks for a pre-1:1 brief, a stakeholder brief, prep for a 1:1 or a meeting with a named person, or wants work/briefs/YYYY-MM-DD <Person>.md written — five lines, grounded in the topic pages and the raw evidence since the last contact.
---

# Work — Pre-1:1 Stakeholder Brief

Produce `work/briefs/YYYY-MM-DD <Person>.md`: five lines the user can say out loud in a 1:1,
plus the evidence they rest on. The data is compiled by a script; the **judgement** — which of
the candidates is worth one of the five lines, and in what words — is the work of this skill.

**Time-box: 5 minutes.** This runs just before a meeting. A brief with four good lines beats a
complete one that arrives after the 1:1 started.

## 1. Gather (deterministic, ~0.5 s)

Take the person from the user's request — a first name is enough.

```bash
python3 scripts/work-brief.py "<person>" --today <YYYY-MM-DD>
```

Prints the packet to stdout — do not write it into the vault. Six sections: `Person`,
`Their topics`, `Since last contact`, `Open asks`, `Other stakeholders on the same topics`,
`Suggested brief skeleton`. The window starts at the resolved last contact (else one cadence
back, else 14 days); `--since YYYY-MM-DD` widens it, `--format json` is there for
post-processing.

**Contact versus mentions.** `## Since last contact` has three sub-sections, and the difference
between the first two is the whole point:

- `### Contact` — files the person actually took part in, each ending in the rule that said so
  (`diary`, `from`, `to`, `attendees`, `speaker`). This is what the `Since last time` line may
  rest on.
- `### Mentions them (not contact)` — files that name them and nothing more: a cc on a
  circulation of fourteen, a name in somebody else's notes. FYI candidates only ("this went past
  with your name on it"); never evidence that anything was said between you.
- `### On their topics, without naming them` — strong topic matches as file lines, then a
  `+N weak via goal/stakeholder` count per topic. A topic carried only by that count is not a
  topic the person is working on.

If `## Person` carries a `first name ambiguous with [[Someone]]` line, the roster holds another
person with the same first name, so the delegated and owed lists were matched on the full name
only — an item written `@Pat` is on neither list. Say so if it changes a line; never guess which
of them it meant.

**If the script exits non-zero, stop.** It exits 2 with a message on stderr when there is no
`work/` tree, no
stakeholder table, no topic pages, or the name is ambiguous or unknown. Show the stderr line, say
what would fix it — for an ambiguous or unknown name, that is the candidate list it printed, so
ask which one and never pick for the user — and stop there. Never write a brief from an empty or
partial packet; five invented lines are worse than no file.

## 2. Write `work/briefs/YYYY-MM-DD <Person>.md`

Use `--today` for the date. Derive the name part of the filename from the display name on the
packet's title line, in this order:

1. Remove wikilink brackets — `[[` and `]]`.
2. Keep only the part before the first ` / ` — a display name may carry a role or a team after a
   slash, and a `/` in a filename is a directory separator.
3. Transliterate diacritics to ASCII: é→e, ö→o, ł→l, ç→c, ø→o, and so on.
4. Remove the characters `:` `/` `\` `*` `?` `"` `<` `>` `|`.
5. Collapse runs of whitespace to a single space, and trim.

The result is `work/briefs/YYYY-MM-DD <Name>.md`. A packet titled `[[Renée Bäcker / Platform]]`,
briefed on 2026-03-10, becomes `work/briefs/2026-03-10 Renee Backer.md`.

Three parts, in this order:

| Part | Content |
|------|---------|
| The five lines | `Since last time` / `What I need from you` / `Risk I see` / `Decision needed` / `FYI`. **One sentence each**, said in the first person, naming a topic. A line with nothing behind it in the packet says so — "nothing since we last spoke" is an honest line; an invented one is not. |
| `## Evidence` | The raw paths the lines actually rest on, one per line, each with what it was used for. Only paths from the packet. |
| `## Open asks` | The packet's `Open asks` section **verbatim** — both sub-sections, unedited. The user reads this off the page in the meeting. |

The skeleton's candidates are *material*, not sentences: a log line is a candidate because it is
dated inside the window, not because anything judged it interesting. Reject the ones that are not
worth the person's time, move one to a different line if that is where it belongs, and write the
sentence yourself. A weak mention can only ever become the `FYI` line; if it is the best thing
available for `Since last time`, the honest line is "nothing since we last spoke".

When a line would claim something about the domain — what a system does, what a decision was,
what a number is — check it with `wiki-query` first, and say only what comes back. The packet
carries dates, paths, progress lines and actions; it does not carry facts about the world.

## 3. Close

Print the five lines in the chat so the user can edit them before the meeting, then remind them
of the after-the-1:1 steps (below). Stop there.

## 4. After the 1:1 (the user does this)

Put this in the chat when the brief is delivered:

```markdown
- [ ] One dated line into `raw/diary/` — what was said, what was decided
- [ ] Set `Last` for that person in `work/Stakeholders.md` to today
- [ ] Add anything they took on as `- [ ] @Name — …` under `## Delegated` on the topic page
- [ ] Recompile: `python3 scripts/work-backlog.py`
```

Run the recompile for the user when they ask.

## Rules

- **Never send anything.** No email, no Slack, no calendar invite, no message drafted "ready to
  send". The brief is a file; the user edits it and delivers it themselves.
- **Never edit a topic page or the stakeholder table in this skill.** The packet is read-only and
  the brief file is the only thing written. Those two updates are the user's step 4.
- One file per person per day: re-running on the same day updates that file rather than creating
  a second one.
- No invented facts. Every line traces to the packet or to one `wiki-query` answer.
- Wikilink targets are exact filenames with spaces — `[[Some Topic]]`, never `[[Some-Topic]]`.

## Common mistakes

| Mistake | Fix |
|---------|-----|
| Pasting the candidates in as the five lines | They are material; write one sentence per line |
| Five lines where the packet supports two | Say "nothing since we last spoke" and stop |
| Drafting the message to send them | Never. The user delivers it |
| Guessing which person an ambiguous name meant | Show the candidate list and ask |
| Treating a mention as contact | It only names them; `### Contact` is the evidence |
| Writing a brief after the script exited non-zero | Show stderr, name the fix, stop |
| Rewording or trimming `## Open asks` | Verbatim — it is read out in the meeting |
| Writing the packet into the vault | It is stdout; the brief is the artifact |
| Updating `Last` "to be helpful" | That is the user's step after the meeting, not before it |
