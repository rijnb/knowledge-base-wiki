---
name: wiki-clear-ingest-batches
description: Use when the user wants to clean up, clear, reset, or abort ingestion batch files — batch-import-* or batch-log-* files in .import/. Examples: "clear batches", "reset import", "clean up ingest files", "abort ingest".
---

# Knowledge Base - Clear Ingest Batches

Use `AskUserQuestion` to confirm before deleting anything:

```
Question: "What would you like to do with the ingestion files in .import/?"
Options:
  - Clear all ingestion records in .import/ — deletes all batch-import-* and batch-log-* files in .import/
  - Abort — do nothing and stop
```

If the user chooses **Clear all ingestion records in .import/**:

```bash
rm -f .import/batch-import-*.txt .import/batch-import-*.claimed.txt .import/batch-log-*.jsonl
echo "Cleared."
```

Then confirm to the user how many files were removed.

If the user chooses **Abort**: stop immediately and do nothing.

