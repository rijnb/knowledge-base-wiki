---
name: wiki-finalize-ingest
description: Use when the user asks to finalize an ingest, merge batch logs, or rebuild Wiki indexes after a batch import.
---

# Knowledge Base - Finalize Ingest

> **When running as an agent** (dispatched by `wiki-ingest`, no user interaction available): at Step 0, abort with an error message if unclaimed batch files exist instead of using `AskUserQuestion`. At Step 6, run All steps without prompting.

> **Step ordering matters — do not reorder.** Hash-stamping (Step 3) MUST run *after* `wiki-assign-dates` (Step 2). The date pass mutates raw-note frontmatter (`date` / `date_span` / `date_confidence`), which changes each file's bytes. If hashes were stamped before dating, every freshly-ingested note would carry a stale hash and get re-flagged as "new" on the next `wiki-create-import-batches` run. Stamping last records the final, dated content.

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

Merge all `.import/batch-log-*.jsonl` into `wiki/log.jsonl` (created if it doesn't exist), then delete the batch files. Run from the vault root:

```bash
python3 scripts/system/wiki-merge-batch-logs.py
```

Every line is validated as a JSON object before anything is written. Do **not** replace this with `cat .import/batch-log-*.jsonl >> wiki/log.jsonl`: that appends half-written lines from a crashed batch session verbatim, fuses two entries into one corrupt line whenever a batch log lacks a trailing newline, and deletes the batch logs even when the append itself failed.

The script writes the merged log through a temp file and removes the batch-log and `batch-import-*.txt` files only once that has succeeded. If it exits non-zero, the merge did not happen: `wiki/log.jsonl` is untouched and the batch logs are still in `.import/` — report the error and stop rather than continuing to Step 2.

If it warns that lines were quarantined in `.import/batch-log-rejected.jsonl`, **tell the user** — those are ingest records that could not be parsed, and the notes they describe will be re-ingested on the next import unless the entries are repaired by hand.

The merged entries do **not** yet carry a `hash`/`mtime` — those are stamped in Step 3, after the date pass has finished mutating the raw files.

## Step 2 — Assign freshness dates

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

## Step 3 — Stamp log hashes and relink renames

Now that the date pass (Step 2) has finished modifying raw-note bytes, stamp content hashes onto the merged log, then repoint any entries whose note was renamed (both deterministic and idempotent — safe to run every finalize). Run stamp first; relink matches orphans by the hashes stamping records:

```bash
python3 scripts/system/wiki-stamp-log-hashes.py
python3 scripts/system/wiki-relink-log-renames.py
```

Stamping records a `hash` (SHA-256 of the source bytes) and `mtime` on each entry so that **renaming** a raw note later in Obsidian does not cause it to be re-ingested; notes whose **content** changed are still re-ingested. Because this runs after Step 2, the hash reflects the note's final, date-stamped content — so a note ingested in this cycle is not falsely re-flagged as "new" on the next import. The relink pass rewrites the `file` of any entry whose note was renamed to its current path, so the log stays accurate and `prune_log` does not later orphan-drop it.

## Step 4 — Rebuild indexes

Run the index-page script from the project root:

```bash
python3 scripts/system/wiki-create-index-pages.py
```

This rebuilds `wiki/index.md` and all `wiki/<topic>/index.md` files.

## Step 5 — Summarize

Present a table of all pages created/updated across all sessions (read from the just-merged session log data).

Then run the one-command freshness check:

```bash
scripts/wiki-freshness.sh --root .
```

This command does not rewrite `wiki/` pages. It writes `.wiki-scratch/freshness-curation-candidates.md` and `.wiki-scratch/provenance-coverage-backlog.md`; mention whether there are one-page curation candidates.

## Step 6 — Post-processing menu

Ask which post-processing steps to run. Use `AskUserQuestion` with `multiSelect: true` when available; otherwise ask a concise plain-text question and wait for the answer. Always run QMD before lint.

Always re-index QMD via `scripts/system/qmd-sync-collections.sh` — never call raw `qmd update` / `qmd embed`. The script also (re)registers the vault root as the single `tomtom` collection, removes stale `wiki-*`/`raw-*` collections, and loops `qmd embed` until no embeddings remain pending.

- **All (recommended)** — lint + QMD text + vector embedding; supersedes individual selections
- **Lint** — health check: orphans, contradictions, gaps 
- **QMD text re-index** (`bash scripts/system/qmd-sync-collections.sh --skip-embed`) — fast, keywords only
- **QMD vector embedding** (`bash scripts/system/qmd-sync-collections.sh`) — slow, ~2 GB models; supersedes text-only if both selected

## Step 7 - End message

After running the lint check or QMD do not suggest to run finalize again. If any problems were found during the lint check, suggest the user runs `python3 scripts/wiki-doctor.py` (interactive mode, without `--batch-mode`) to review and fix the remaining problems one by one.
