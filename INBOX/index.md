# INBOX

Store notes here that are not ready for ingestion (yet). If you want to ingest them into the knowledge base, move them to `raw/notes` and execute this LLM prompt:
```
ingest new notes
```
or run the `script/wiki-ingest.sh` script in a CLI.

## Working with the knowledge base

### Adding raw notes

Put source material in the matching `raw/` subfolder, then ingest it:

- `raw/notes` — typed notes, 1:1s, people-specific files
- `raw/clips` — web articles saved with the Obsidian Web Clipper
- `raw/transcripts` — `.vtt` meeting transcripts
- `raw/emails` — emails (ask **"fetch mail"**, or drop `.eml`/`.html` files here)
- `raw/scans` — handwritten pages or scanned PDFs/JPGs
- `raw/slack` — Slack channels and DMs (ask **"fetch slack"**)

Draft notes stay in this `INBOX` folder and are **not** ingested. Move them to `raw/notes` when ready, then say **"ingest new notes"** (or run `scripts/wiki-ingest.sh`). Non-Markdown files are auto-converted; add `ingest: false` frontmatter to a note to keep it out of ingestion.

### Reasons to run the doctor

Ask **"visit doctor"** (or run `scripts/wiki-doctor.py`) regularly — especially after ingesting — to keep the wiki clean. The doctor finds and helps you fix:

- **Broken links** — remove, flag, or replace with plain text
- **Orphaned pages** — delete, or keep (mark `orphan: false`)
- **Stub pages** — pages the LLM referenced but never filled in; delete or keep

The goal is zero false-positive alerts, so a clean run means the knowledge base is genuinely sound.

### Freshness check

Ask **"freshness check"** (or run `scripts/wiki-freshness.sh`) as the third regular maintenance action, alongside ingest and doctor. It adds block-level **provenance** to canonical pages (when a claim was observed/checked, its status, and confidence), which lets `wiki-query` rank current evidence higher and explain when older or superseded evidence is being demoted. Run it after ingest, after fixing doctor findings, or before freshness-sensitive queries.

### When to use "curate this page"

Say **"curate this page"** (or run `wiki-curate-page`) to clean up **one** canonical page using its raw evidence and freshness/drift signals. Reach for it when the freshness/drift queue flags that newer raw notes may have changed a page, or when you notice a specific page is stale or inaccurate. It focuses on a single page and does not bulk-rewrite the wiki. Bulk curation is **not** recommended.

![[INBOX/_resources/index.jpg]]