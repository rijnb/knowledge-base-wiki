---
name: wiki-ingest
description: Use when the user asks to ingest, import, or process one or more notes; mentions a raw note file path; provides a Confluence URL or page title; or says "ingest note", "ingest notes", "ingest new notes", or "ingest files". NOT for Slack messages — use wiki-fetch-slack instead.
---

# Knowledge Base - Ingest

## Session 1 — coordinator

When asked to "ingest new raw notes" (or similar):

1. **Convert raw files** (run automatically before partitioning):
   ```bash
   python3 scripts/system/convert-vtt-to-md.py --input-dir raw/transcripts --output-dir raw/transcripts/converted
   python3 scripts/system/convert-eml-to-md.py --input-dir raw/emails --output-dir raw/emails/converted
   ```
   These convert VTT transcript files and EML email files into Markdown so they are picked up by the batch importer. Skip silently if the input directories don't exist.
2. **Partition** (run automatically): `bash scripts/system/wiki-create-import-batches.sh`
   - Default max batch size is 50 files. Override with `--max-size N` (e.g. `--max-size 20`).
   - This removes any old `.import/batch-import-*.txt` remnants and creates fresh ones.
   - **If the script exits with code 3**: there are no new notes to ingest. Report "Nothing to ingest" and stop.
   - **If the script exits with code 2**: a previous ingest was not completed. Ask the user what to do (use `AskUserQuestion` when available; otherwise ask a concise plain-text question), with these options:
     - **"Ingest next batch"** — stop here and tell the user: "Use `wiki-ingest-next-batch` (or say `ingest next batch`) in a new session to continue."; do NOT re-run `wiki-create-import-batches.sh`.
     - **"Abort previous ingestion and restart importing new notes"** — re-run `bash scripts/system/wiki-create-import-batches.sh --force` to wipe old batches, then continue with this flow from step 3.
     - **"Abort"** — stop immediately and do nothing.
   - Check the exit code explicitly after running the script: `bash scripts/system/wiki-create-import-batches.sh; echo "EXIT:$?"` and look for `EXIT:2` or `EXIT:3`.
3. **Check how many batches have content**: count non-empty `.import/batch-import-*.txt` files (the script prints the count).
   - **If only 1 batch has content**: process it (step 4) and immediately proceed to Finalization — say "Batch done. Say `finalize ingest` (or `/wiki-finalize-ingest`) to wrap up."
   - **If 2+ batches have content**: Tell the user — "Batches ready. Open N more sessions and say `ingest next batch` in each one. I'll start batch 1 now. When all sessions are done, come back here." — then proceed to step 4.
4. **Process batch 1**: first claim it atomically:
   ```bash
   mv .import/batch-import-1.txt .import/batch-import-1.claimed.txt
   ```
   Then read `.import/batch-import-1.claimed.txt`. Dispatch sub-agents in batches of 10 when the current client supports and permits delegation; otherwise process the files in the current session in manageable chunks.
   Each sub-agent prompt must begin with: 
     "Invoke `wiki-ingest-per-note` before processing. Write session logs to `.import/batch-log-1.jsonl`. Then ingest these files: [list]."
   After all sub-agents finish, delete `.import/batch-import-1.claimed.txt`.
5. After all batch processing is complete (batch 1 done here + all batch agents done): run finalization with the `wiki-finalize-ingest` skill, or dispatch one `wiki-finalize-ingest` agent when the current client supports and permits it. Report the batch summary to the user while finalization runs.

## Confluence ingestion

Triggered by a Confluence URL or page title:

- Fetch via the available Atlassian connector. In Claude this may be `mcp__claude_ai_Atlassian__fetch`; in Codex use the available Atlassian/Rovo fetch/search tools. If no connector is available, ask the user for the exported page content before writing files.
- Save to `raw/confluence/<Page Title>.md` with frontmatter:
```yaml
---
source_url: <url>
fetched: YYYY-MM-DD HH:mm:ss
last_modified: YYYY-MM-DD   # the page's last-updated / version date from the fetch metadata
created: YYYY-MM-DD         # the page's creation date, if the fetch exposes it
---
```
  - `last_modified` is the real content date (Confluence's "Last updated" / version date). Always record it when available — it gives the page an accurate, medium-confidence `date` instead of falling back to the `fetched` sync timestamp.
- Continue with per-note ingestion for that file (as a single-file session — write to `.import/batch-log-1.jsonl`).
- **Assign freshness dates inline** (don't wait for finalize): after all Wiki pages are written, run the date pass so the new raw page and every created/updated Wiki page get `date` / `date_span` / `date_confidence` immediately. Run the full pass (idempotent, only rewrites pages whose dates changed — no need to enumerate paths):
  ```bash
  python3 scripts/system/wiki-assign-dates.py --apply
  ```
  (To date only specific files instead, append `--paths "raw/confluence/<Page>.md" "wiki/<topic>/<page>.md" …`.)
- Then tell the user to run `finalize ingest` to rebuild indexes and re-index search.

**Refresh:** "refresh this Confluence page" → re-fetch, overwrite cache, diff vs previous, flag changes affecting existing Wiki pages.

## Slack ingestion

For Slack channels and DMs, use the `wiki-fetch-slack` skill instead of this one.
Trigger phrases: "fetch Slack", "ingest Slack", "sync Slack channels".

## wiki/log.jsonl format

`wiki/log.jsonl` is append-only. One JSON object per line, sorted oldest-to-newest by append order.

```jsonl
{"date":"YYYY-MM-DD HH:mm:ss","session":1,"file":"raw/notes/meeting-2026-03-01.md","summary":"Quarterly planning meeting notes.","pages_created":["wiki/decisions/adopt-vector-tiles.md","wiki/projects/AutoStream.md"],"pages_updated":["wiki/people/Jane Smith.md"]}
```

Finding un-ingested notes: `jq -r '.file' wiki/log.jsonl` — lists all ingested paths.  
Fallback without jq: `grep -oP '"file":"\K[^"]+' wiki/log.jsonl`

## Notes

- A single note may touch 5–25+ Wiki pages. That is expected and desirable.
- Never re-ingest a file already present in `wiki/log.jsonl` without explicit user confirmation.
- Parallel sessions writing to the same Wiki page is safe: the second session reads the already-updated page and extends it further.
