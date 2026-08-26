---
name: wiki-clear-ingest-batches
description: Use when the user wants to clean up, clear, reset, or abort ingestion batch files — batch-import-* or batch-log-* files in .import/. Examples: "clear batches", "reset import", "clean up ingest files", "abort ingest".
---

# Knowledge Base - Clear Ingest Batches

## Step 1 — Show what would go

Never confirm a deletion the user cannot see. From the vault root:

```bash
python3 scripts/system/wiki-clear-ingest-batches.py --list
```

This prints the exact files and warns when the batch logs still hold ingest records that never reached `wiki/log.jsonl`. If it reports nothing to clear, say so and stop.

## Step 2 — Confirm

Show the user the file list from Step 1, then ask. Use `AskUserQuestion` when available; otherwise ask a concise plain-text question and wait for the answer:

```
Question: "What would you like to do with the ingestion files in .import/?"
Options:
  - Clear all ingestion records in .import/ — deletes the N files listed above
  - Abort — do nothing and stop
```

**If Step 1 warned about unmerged ingest records**, put that in the question: clearing discards them, and every note they cover is re-ingested from scratch on the next import. Offer `wiki-finalize-ingest` as the alternative that keeps them.

## Step 3 — Clear

Only after the user chooses to clear:

```bash
python3 scripts/system/wiki-clear-ingest-batches.py --apply
```

Report the count it prints — that is what was actually deleted, not what was matched. If it lists any `FAILED:` lines, surface them; the exit code is non-zero when a file could not be removed.

If the user chooses **Abort**: stop immediately and do nothing.
