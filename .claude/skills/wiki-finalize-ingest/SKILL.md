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
ls .import/batch-import-[0-9]*.txt 2>/dev/null | grep -v '\.claimed\.'
```

- **No `.import/batch-log-N.jsonl` files AND no `.import/batch-import-N.txt` files**: nothing to finalize. Tell the user: "No batch import logs or files found. Nothing to finalize — run `wiki-ingest` to start a new import."
- **Unclaimed `.import/batch-import-N.txt` files still exist** (not `.claimed.`): warn the user: "Some batches have not been processed yet. Make sure all `wiki-ingest-next-batch` sessions have finished before finalizing." Ask: "Proceed anyway (partial finalization) or abort?" Use `AskUserQuestion` when available; otherwise ask a concise plain-text question and wait for the answer.
- **Only `.import/batch-log-N.jsonl` files exist**: all batches are done — proceed to Step 1 of finalizing.

## Step 1 — Merge logs

Append all `.import/batch-log-*.jsonl` to `wiki/log.jsonl` (create `wiki/log.jsonl` if it doesn't exist), then delete all `.import/batch-log-*.jsonl` and any remaining `.import/batch-import-*.txt`:

```bash
# Wrapped in `bash -c` with `shopt -s nullglob` so unmatched globs expand to
# nothing instead of aborting (zsh nomatch) or being passed as a literal pattern.
# This runs identically whether the caller is bash or zsh (the Bash tool uses zsh).
bash -c '
  shopt -s nullglob
  logs=(.import/batch-log-*.jsonl)
  imports=(.import/batch-import-*.txt)
  [ ${#logs[@]} -gt 0 ] && cat "${logs[@]}" >> wiki/log.jsonl
  [ ${#logs[@]} -gt 0 ] && rm -f "${logs[@]}"
  [ ${#imports[@]} -gt 0 ] && rm -f "${imports[@]}"
  true  # always exit 0 when cleanup completes without error
'
```

Then stamp content hashes onto the merged log, and repoint any entries whose note was renamed (both deterministic and idempotent — safe to run every finalize). Run stamp first; relink matches orphans by the hashes stamping records:

```bash
python3 scripts/system/wiki-stamp-log-hashes.py
python3 scripts/system/wiki-relink-log-renames.py
```

Stamping records a `hash` (SHA-256 of the source bytes) and `mtime` on each entry so that **renaming** a raw note later in Obsidian does not cause it to be re-ingested; notes whose **content** changed are still re-ingested. The relink pass rewrites the `file` of any entry whose note was renamed to its current path, so the log stays accurate and `prune_log` does not later orphan-drop it.

## Step 2 — Rebuild indexes

Run the index-page script from the project root:

```bash
python3 scripts/system/wiki-create-index-pages.py
```

This rebuilds `wiki/index.md` and all `wiki/<topic>/_index.md` files.

## Step 3 — Assign freshness dates

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

Ask which post-processing steps to run. Use `AskUserQuestion` with `multiSelect: true` when available; otherwise ask a concise plain-text question and wait for the answer. Always run QMD before lint.

Always re-index QMD via `scripts/system/qmd-sync-collections.sh` — never call raw `qmd update` / `qmd embed`. The script also (re)registers the vault root as the single `tomtom` collection, removes stale `wiki-*`/`raw-*` collections, and loops `qmd embed` until no embeddings remain pending.

- **All (recommended)** — lint + QMD text + vector embedding; supersedes individual selections
- **Lint** — health check: orphans, contradictions, gaps 
- **QMD text re-index** (`bash scripts/system/qmd-sync-collections.sh --skip-embed`) — fast, keywords only
- **QMD vector embedding** (`bash scripts/system/qmd-sync-collections.sh`) — slow, ~2 GB models; supersedes text-only if both selected

## Step 6 - End message

After running the lint check or QMD do not suggest to run finalize again. If any problems were found during the lint check, suggest the user runs `python3 scripts/wiki-doctor.py` (interactive mode, without `--batch-mode`) to review and fix the remaining problems one by one.
