---
name: wiki-finalize-ingest
description: Use when the user asks to finalize an ingest, merge batch logs, or rebuild Wiki indexes after a batch import.
---

# Knowledge Base - Finalize Ingest

> **When running as an agent** (dispatched by `wiki-ingest`, no user interaction available): at Step 0, abort with an error message if unclaimed batch files exist instead of using `AskUserQuestion`. At Step 5, run All steps without prompting.

## Step 0 — Check state

Before doing anything, verify there is something to finalize:

```bash
ls .import/batch-log-*.jsonl 2>/dev/null
ls .import/batch-import-*.txt 2>/dev/null
```

- **No `.import/batch-log-N.jsonl` files AND no `.import/batch-import-N.txt` files**: nothing to finalize. Tell the user: "No batch import logs or files found. Nothing to finalize — run `wiki-ingest` to start a new import."
- **Unclaimed `.import/batch-import-N.txt` files still exist** (not `.claimed.`): warn the user: "Some batches have not been processed yet. Make sure all `wiki-ingest-next-batch` sessions have finished before finalizing." Ask: "Proceed anyway (partial finalization) or abort?" Use `AskUserQuestion` when available; otherwise ask a concise plain-text question and wait for the answer.
- **Only `.import/batch-log-N.jsonl` files exist**: all batches are done — proceed to Step 1 of finalizing.

## Step 1 — Merge logs

Append all `.import/batch-log-*.jsonl` to `wiki/log.jsonl` (create `wiki/log.jsonl` if it doesn't exist). 
Then delete all `.import/batch-log-*.jsonl` and any remaining `.import/batch-import-*.txt`.

## Step 2 — Rebuild indexes

Run the index-page script from the project root:

```bash
python3 scripts/system/wiki-create-index-pages.py
```

This rebuilds `wiki/index.md` and all `wiki/<topic>/_index.md` files.

## Step 2.5 — Assign freshness dates

Run the freshness pass so every wiki and raw page carries up-to-date `date` / `date_span` / `date_confidence` frontmatter (newly ingested pages get dated; existing pages get refreshed if newer sources were added):

```bash
python3 scripts/system/wiki-assign-dates.py --apply
```

This is deterministic and idempotent — safe to run on every finalize. It resolves each page's content date from source-note filenames, parent-folder years, source frontmatter, and (for raw pages) body text, recording `date_confidence` (high/medium/low) so stale or capture-only dates are flagged. Report its summary line (resolved / no-date / confidence distribution). Pages with no datable source are intentionally left without a `date` field.

Use this command to scan Markdown files for stubs:
```bash
find wiki -name "*.md" -exec awk '/^---/{p++} p==1{print FILENAME": "$0} p==2{p=0; nextfile}' {} + | grep "stub:.*true"
```
If any exist, list them in a "Stubs still needing expansion" section so the user knows what gaps remain.

## Step 4 — Summarize

Present a table of all pages created/updated across all sessions (read from the just-merged session log data). 

## Step 5 — Post-processing menu

Ask which post-processing steps to run. Use `AskUserQuestion` with `multiSelect: true` when available; otherwise ask a concise plain-text question and wait for the answer. Always run QMD before lint:

- **All (recommended)** — lint + QMD text + vector embedding; supersedes individual selections
- **Lint** — health check: orphans, contradictions, gaps 
- **QMD text re-index** (`qmd update`) — fast, keywords only
- **QMD vector embedding** (`qmd update && qmd embed`) — slow, ~2 GB models; supersedes text-only if both selected

## Step 6 - End message

After running the lint check or QMD do not suggest to run finalize again. Do propose to run `scripts/wiki-doctor.py` if any problems were found during the lint check.
