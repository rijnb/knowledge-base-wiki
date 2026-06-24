---
name: wiki-fetch-slack
description: Use when the user asks to fetch Slack, ingest Slack, sync Slack channels, or process Slack messages into the knowledge base.
---

# Wiki — Slack Ingest

Fetch Slack threads and DMs configured in `config/personal_info.md` and write them as Markdown files to `raw/slack/`. After fetching, tell the user to use the `wiki-ingest` skill (or say `ingest new notes`) to ingest them — or run `scripts/wiki-ingest.sh` for unattended bulk ingestion.

## Step 1: Read config

Read `config/personal_info.md`. Find the `# Slack` section and parse the Markdown table:

| Channel / DM | Days | Mode |
|---|---|---|
| #channel-name | N | signal |
| @Person Name | N | software design decisions |

- Rows starting with `#` → Slack channels
- Rows starting with `@` → individual DMs with that person
- `Days` blank → use 7 days (default), or the command-level override if provided
- `Mode` blank → default to `signal`

**Mode values:**
- `signal` — apply universal noise exclusion filter (see Step 3)
- `all` — no filtering, include everything
- any other text — treat as a focus topic: strict inclusion filter (include only threads directly about that topic)

If `personal_info.md` is missing or has no `# Slack` section, report:
> "No Slack sources configured. Add a `# Slack` table to `config/personal_info.md`."
Then stop.

If the `# Slack` table cannot be parsed (missing header row, malformed pipes, unrecognised column names), report the specific problem and stop.

**Command override:** If the user said "fetch Slack last N days", use N for all sources regardless of per-row Days values.

## Step 2: Check available Slack MCP tools

Before fetching, list available Slack MCP tools. Look for tools to:
- List channels / find a channel by name
- Fetch channel message history (with a time window)
- Fetch thread replies for a given message

The exact tool names depend on which Slack MCP is configured. Use whatever tools are available to accomplish the steps below.

## Step 3: Fetch and write files for each source

Process each row in the config table in order.

**Directory names:**
- Channel `#architecture-decisions` → `raw/slack/architecture-decisions/`
- DM `@Alice van Dijk` → `raw/slack/DM-Alice van Dijk/`

Create the directory if it does not exist.

**Look up cached state:** Before resolving IDs or fetching, find the most recent `slack-fetch` entry for this source in `wiki/log.jsonl`:
- With jq: `jq 'select(.type == "slack-fetch" and .source == "<dir>")' wiki/log.jsonl | tail -1`
- Fallback (no jq): `grep '"slack-fetch"' wiki/log.jsonl | grep '"<dir>"' | tail -1`

From that entry extract:
- `id` — cached channel or user ID (use directly; skip MCP resolution if present)
- `date` — use as fetch window start (fall back to start of day N calendar days ago if absent)

**ID resolution:** Only resolve via MCP if no cached `id` was found above.
- For `#`-prefixed rows: look up the channel by name.
- For `@`-prefixed rows: search for the person by display name or real name. If the tool returns multiple matches, use the closest exact match. If no match is found or the lookup is ambiguous, warn ("Could not resolve @Person Name to a Slack user — skipping") and skip that row. Do not guess.

**Fetch:** Use the Slack MCP to get all messages in the source that had activity within the fetch window (from the determined window start to now). Separate threads from loose (unthreaded) messages.

**Apply mode filter:** For each thread, apply the filter based on the source's resolved mode:

- **`all`** — include everything, no filtering.
- **Topic string** (any value other than `signal` or `all`) — strict inclusion filter: only include threads with a direct, obvious connection to that topic. When in doubt, skip. *(The `signal` thread-override does not apply here — if the root looks like noise, skip the thread regardless of replies.)* A thread must have a direct, obvious connection to be included — loose or tangential relevance is not enough.
- **`signal`** (or blank) — noise exclusion filter: skip the thread if it clearly falls into one of these categories:
  - Absence / illness / scheduling notices ("I'm not feeling well", "I'll be out", "I'll be late to standup", "missing standup", "appointment")
  - Join / leave system events (Slack-generated "X has joined the channel")
  - PR review nudges and reminders (human or automated): "please review this PR", "be mindful of PRs assigned to you", bot notifications (build status, pipeline, deployment confirmations), meeting reminders, calendar pings
  - Bare status pings as root message with no substantive content ("done", "on it", "will check", "FYI" with nothing else)
  - Cross-posts without added context ("sharing this from #other-channel" with no commentary)
  - Pure social messages: threads where the root has no reply messages (only emoji reactions on the root), one-word standalone replies ("noted", "thanks", "+1")
  - Unanswered standalone questions with no replies and no follow-up: a loose message asking a quick question that received no response
  - Task assignments with only acknowledgement replies: a root message delegating or assigning a task ("could you finalize X?", "please handle Y", "would you be able to do Z?") where all replies are simple confirmations ("yes", "will do", "on it", "done") with no substantive discussion about the task itself
  - **Thread override:** if the root message looks like noise but the replies contain substantive discussion (decisions, problem-solving, design questions, feature discussions), keep the entire thread. The filter evaluates the thread as a whole, not just the opening message. When in doubt — include.

### Thread files

Copy each message's text exactly as returned by the Slack MCP — character for character. Do not edit, summarize, paraphrase, shorten, or remove anything. Preserve typos, emoji, informal language, code blocks, formatting, and links exactly as they appear.

For each thread:

1. Convert the root message timestamp to `YYYY-MM-DD HH_mm_ss` format (replace `:` with `_`). This is `thread_ts`.
2. Convert the latest reply timestamp the same way. This is `latest_reply_ts`.
3. Filename: `<thread_ts> - reply - <latest_reply_ts>.md`

Note: filenames use underscores (`HH_mm_ss`); frontmatter `latest_reply_ts` and `fetched` fields use colons (`HH:mm:ss`).

Check for an existing file in the directory whose name starts with `<thread_ts> - reply`:
- **Not found** → write new file
- **Found, filename already ends with `reply - <latest_reply_ts>.md`** → skip (unchanged)
- **Found, filename ends with a different reply ts** → delete old file, write new file

File format:

```
---
source: slack
channel: "#architecture-decisions"
thread_url: <permalink from MCP response; omit field if not available>
fetched: YYYY-MM-DD HH:mm:ss # local time
latest_reply_ts: "YYYY-MM-DD HH:mm:ss"
mode: <resolved mode: signal, all, or the topic string>
---

**@username** — YYYY-MM-DD HH:mm:ss
<root message text>

**@username** — YYYY-MM-DD HH:mm:ss
<reply text>
```

For direct messages (DMs), use `channel: "DM: Alice van Dijk"` in the frontmatter.

### Loose messages file

Copy each message's text exactly as returned by the Slack MCP — character for character. Do not edit, summarize, paraphrase, shorten, or remove anything. Preserve typos, emoji, informal language, code blocks, formatting, and links exactly as they appear.

Collect all messages in the source that are not part of any thread. Apply the same mode filter as for threads: `all` passes everything through, a topic string applies the strict inclusion filter, and `signal` applies the noise exclusion categories listed above. If any qualifying messages remain, write them to:

```
raw/slack/<dir>/YYYY-MM-DD loose-message.md
```

Use current date. Overwrite if the file already exists for today.

```
---
source: slack
channel: "#team-platform"
type: loose-messages
fetched: YYYY-MM-DD HH:mm:ss  # local time
mode: <resolved mode: signal, all, or the topic string>
---

**@username** — YYYY-MM-DD HH:mm:ss
<message text>

**@username** — YYYY-MM-DD HH:mm:ss
<message text>
```

If there are no loose messages, do not create the file.

**Record fetch in log:** After successfully writing all files for this source, append one line to `wiki/log.jsonl`:

```json
{"date": "YYYY-MM-DD HH:mm:ss", "type": "slack-fetch", "source": "<dir>", "id": "<channel or user id>", "window_start": "YYYY-MM-DD HH:mm:ss"}
```

`date` is the local time the fetch completed. `window_start` is the actual start of the window used. `id` is the resolved channel or user ID. Only append if the source completed without error — do not append if it was skipped due to a channel-not-found or MCP error.

## Error handling

- **Slack MCP unavailable or no Slack tools found**: report the error and stop — do not write any files.
- **Channel not found or no access**: warn (e.g. "Could not access #channel-name — skipping") and continue with remaining sources.
- **Thread fetch fails**: warn and skip that thread, continue with remaining threads.
- **No new or updated threads across all sources**: report "Nothing to fetch from Slack — all threads are up to date." and stop cleanly.

## Step 4: Report and hand off

After processing all sources, report a summary:

```
Slack fetch complete:
  N new thread files written
  N thread files updated (replaced)
  N thread files unchanged (skipped)
  N loose message files written
```

Then tell the user:

> "Slack files written to `raw/slack/`. Use the `wiki-ingest` skill (or say `ingest new notes`) to ingest them — or run `scripts/wiki-ingest.sh` for unattended bulk ingestion."
