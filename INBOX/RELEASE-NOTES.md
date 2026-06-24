# Release Notes

## 2026-06-24 — Ingest cleanup no longer leaves stale batch files

Fixed a bug where stale batch files (e.g. `batch-log-1.jsonl`) could be left behind after finalize/clear, blocking the next ingest with a "previous ingest not completed" error.

## 2026-06-24 — `ingest: false` frontmatter opt-out

Notes under `raw/` can opt out of ingestion with frontmatter `ingest: false`. Local files linked from a protected note are also skipped. Remove the field to make the note eligible again. Documented in `README.md`.

## 2026-06-15 — Finalize re-indexes QMD via the sync script

Finalize now keeps QMD collections consistent (single `tomtom` collection, stale collections removed, embeddings retried) instead of running raw `qmd update`.

## 2026-06-15 — Per-note ingest uses converter scripts for .eml/.html/.vtt

These types are now always converted via the converter scripts, so emails get the correct `YYYY-MM-DD ` filename prefix and frontmatter. Manual conversion only applies to types with no script (pdf, images, docx).

## 2026-06-15 — Date assignment never touches top-level vault files

Date frontmatter (`date`/`date_span`/`date_confidence`) is now only written to files under `wiki/` or `raw/` — never to top-level files like `CLAUDE.md`, `README.md`, or `index.md`.

## 2026-06-15 — Rename-safe ingest dedup

Ingestion now decides "already ingested" by content hash + mtime, not filename. Renaming a raw note in Obsidian no longer re-ingests it; editing it still does.

## 2026-06-11 — Test suite and wiki-doctor improvements

- New test suite in `scripts/tests/` — run with `python3 -m unittest discover -s scripts/tests -v`.
- `wiki-doctor` now detects non-Markdown files outside `_resources/` (in `raw/`, `wiki/`, `INBOX`) and can auto-move them.

## 2026-06-11 — New layout for converted non-Markdown files

Converted sources (`.eml`, `.html`, `.vtt`, `.pdf`, `.docx`, images) no longer go in a `converted/` subdirectory. The original moves to `_resources/` and a companion `.md` (with preview embed + extracted text) is created in its place.

**Migrating an existing corpus:** run `python3 scripts/wiki-doctor.py` once — in interactive mode it detects legacy `converted/` directories and offers to migrate them. The migration is warning-neutral and re-running is a no-op.

## 2026-06-10 — AI backend configuration (`config/settings.md`)

LLM-backed scripts now read their backend from `config/settings.md` (`ai_backend`: `claude`, `vibe`, or `codex`). Change the value and save — no code edits. Falls back to deterministic behavior if the CLI is missing or fails.

## 2026-06-10 — New `wiki-ground` skill

`/wiki-ground [optional topic]` grounds the whole conversation in the knowledge base, querying the KB before answering domain questions. Optional topic front-loads relevant pages on activation.
