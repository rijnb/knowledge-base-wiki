---
name: wiki-ingest-next-batch
description: Use when continuing a batch import that was started in another session — when the user says "ingest next batch" or opens a parallel session during a multi-batch import.
---

# Knowledge Base - Ingest Next Batch

This skill handles Sessions 2–N of a multi-batch import started by `wiki-ingest`.

## Step 1 — Check state

Before claiming a batch, verify the import is in progress:

```bash
ls .import/batch-import-[0-9]*.txt 2>/dev/null | grep -v '\.claimed\.' | sort -V
ls .import/batch-log-*.jsonl 2>/dev/null
```

- **No unclaimed `.txt` files AND no `.jsonl` log files**: nothing to do — tell the user "No batch import in progress. Use `wiki-ingest` to start a new import."
- **No unclaimed `.txt` files BUT `.jsonl` log files exist**: all batches are processed. Tell the user: "All batches appear complete. Say `finalize ingest` (or `/wiki-finalize-ingest`) to merge logs and rebuild indexes."
- **Unclaimed `.txt` files exist**: proceed to Step 2.

## Step 2 — Claim a batch atomically

Run the following to find and claim the next unclaimed batch:

```bash
for f in $(ls .import/batch-import-[0-9]*.txt 2>/dev/null | grep -v '\.claimed\.' | sort -V); do
  mv "$f" "${f%.txt}.claimed.txt" 2>/dev/null && echo "${f%.txt}.claimed.txt" && break
done
```

- If the loop prints a filename (e.g. `.import/batch-import-2.claimed.txt`) → that is your batch; proceed to Step 3.
- If nothing is printed → all batches are taken or already done; report "No unclaimed batch found — another session may be processing the last batch" and stop.

## Step 3 — Process the batch

Determine the batch number from the claimed filename (e.g. `.import/batch-import-2.claimed.txt` → N=2). Dispatch sub-agents in batches of 10 to process the files. Each sub-agent prompt must begin with: "Invoke `wiki-ingest-per-note` before processing. Write session logs to `.import/batch-log-N.jsonl`. Then ingest these files: [list]." (Replace N with the actual batch number.)

## Step 4 — Finish

After processing all files, delete the `.claimed.txt` file.

Report:
- Batch number claimed
- Number of notes processed
- Pages created and updated

Then check if more unclaimed batches remain:

```bash
ls .import/batch-import-[0-9]*.txt 2>/dev/null | grep -v '\.claimed\.'
```

- **Unclaimed batches remain**: tell the user "More batches available — other sessions can run `wiki-ingest-next-batch` to claim them."
- **No unclaimed batches remain AND `.jsonl` logs exist**: tell the user "All batches are now processed. When all parallel sessions are done, say `finalize ingest` (or `/wiki-finalize-ingest`) in the coordinator session to wrap up."
