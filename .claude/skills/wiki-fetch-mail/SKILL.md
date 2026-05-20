---
name: wiki-fetch-mail
description: Use when the user asks to fetch mail, sync email inbox, or process emails into the knowledge base.
---

# Wiki — Mail Fetch

Fetch email files from the configured OneDrive inbox and copy them to `raw/emails/` for ingestion.

## Step 1: Read config

Read `config/personal_info.md`. Find the `# Email` section and parse the Markdown table:

| Setting | Value |
|---|---|
| Inbox | /path/to/inbox |

Extract the `Inbox` value. If the `# Email` section is missing or the `Inbox` row cannot be found, report:

> "No email inbox configured. Add an `# Email` table with an `Inbox` row to `config/personal_info.md`."

Then stop.

## Step 2: Verify inbox

Check that the inbox path exists and is accessible:

```bash
ls "<inbox_path>"
```

If the path does not exist or is inaccessible, report:

> "Email inbox not found or not accessible: <path>"

Then stop.

## Step 3: Scan inbox

List all `.html` and `.eml` files in the inbox (flat directory, no recursion):

```bash
find "<inbox_path>" -maxdepth 1 \( -name "*.html" -o -name "*.eml" \) | sort
```

If no files are found, report:

> "Nothing to fetch — inbox is empty."

Then stop.

## Step 4: Copy and drain

For each file in the list:

1. If a file with the same name already exists in `raw/emails/`, skip the copy (count as skipped) but still delete the original from the inbox — it is already safe in `raw/emails/`.
2. Otherwise, copy the file to `raw/emails/` first, then delete the original:

```bash
cp "<inbox_path>/<filename>" "raw/emails/<filename>" && rm "<inbox_path>/<filename>"
```

If the copy fails, warn ("Could not copy <filename> — skipping") and leave the original in the inbox. Do not delete a file whose copy failed.

In all cases where the file ends up in `raw/emails/` (whether copied now or already present), delete it from the inbox.

## Step 5: Log

Append one line to `wiki/log.jsonl` (replace N with actual counts and use local time):

```json
{"date": "YYYY-MM-DD HH:mm:ss", "type": "email-fetch", "inbox": "<path>", "files_copied": N, "files_skipped": N}
```

## Step 6: Report and hand off

Report a summary:

```
Mail fetch complete:
  N files copied to raw/emails/
  N files skipped (already present)
```

Then tell the user:

> "Email files written to `raw/emails/`. Run `scripts/wiki-ingest-loop.sh` to ingest them into the wiki."
