---
name: wiki-migrate-existing
description: Use when the user wants to migrate an existing raw/ + wiki/ knowledge base into the provenance/freshness workflow.
---

# Knowledge Base - Migrate Existing Corpus

Use this skill when a user already has `raw/` source notes and `wiki/` canonical pages, and wants to adopt the provenance/freshness tooling without bulk re-ingesting the historical raw corpus.

Start with a dry-run:

```bash
scripts/wiki-migrate-existing.sh --root .
```

To apply:

```bash
scripts/wiki-migrate-existing.sh --root . --apply
```

Default behavior is safe: existing raw files are migration-baselined in `wiki/log.jsonl` during `--apply`, so later ingest does not process the whole old corpus. The baseline respects `ingest: false` notes and their explicitly linked local raw files.

Only use this reverse option when the user explicitly wants historical raw notes to be eligible for fresh ingestion:

```bash
scripts/wiki-migrate-existing.sh --root . --apply --allow-reingest-existing
```

Report:

- whether this was dry-run or apply;
- whether existing raw files were baselined;
- doctor/freshness issue counts;
- where `.wiki-scratch/migration-report.md` was written.

After migration, use ordinary `wiki-ingest` only for new notes and `wiki-curate-page` for selected legacy pages that need factual cleanup.
