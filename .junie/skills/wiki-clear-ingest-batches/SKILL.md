---
name: wiki-clear-ingest-batches
description: Use when the user wants to clean up, clear, reset, or abort ingestion batch files — batch-import-* or batch-log-* files in .import/. Examples: "clear batches", "reset import", "clean up ingest files", "abort ingest".
---

# Knowledge Base - Clear Ingest Batches

Confirm before deleting anything. Use `AskUserQuestion` when available; otherwise ask a concise plain-text question and wait for the user's answer:

```
Question: "What would you like to do with the ingestion files in .import/?"
Options:
  - Clear all ingestion records in .import/ — deletes all batch-import-* and batch-log-* files in .import/
  - Abort — do nothing and stop
```

If the user chooses **Clear all ingestion records in .import/**:

```bash
# Wrapped in `bash -c` with `shopt -s nullglob` so unmatched globs expand to
# nothing instead of aborting (zsh nomatch) or being passed as a literal pattern.
# Runs identically under bash or zsh (the Bash tool uses zsh).
bash -c '
  shopt -s nullglob
  files=(.import/batch-import-*.txt .import/batch-import-*.claimed.txt .import/batch-log-*.jsonl)
  [ ${#files[@]} -gt 0 ] && rm -f "${files[@]}"
  echo "Cleared ${#files[@]} file(s)."
'
```

Then confirm to the user how many files were removed.

If the user chooses **Abort**: stop immediately and do nothing.
