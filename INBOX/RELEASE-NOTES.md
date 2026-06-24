# Release Notes

## 2026-06-24 — Existing knowledge base migration script

Added `scripts/wiki-migrate-existing.sh` as a safe dry-run-first migration wrapper for existing `raw/` + `wiki/` corpora. With `--apply`, it baselines existing raw files in `wiki/log.jsonl` by default so future ingest does not re-ingest the historical corpus; `--allow-reingest-existing` is the explicit reverse option. Added `wiki-baseline-raw-log.py`, root-aware date/QMD helpers, tests, README guidance, and a `wiki-migrate-existing` skill.

## 2026-06-24 — Freshness reminders and scratch ignore

Ignored generated `.wiki-scratch/` queue files, updated `wiki-doctor.py` to emit a structured freshness follow-up recommendation, and made the ingest loop dry-run/output text explicitly mention the automatic freshness step.

## 2026-06-24 — One-command freshness workflow

Added `scripts/wiki-freshness.sh` as the easy freshness front door. It runs provenance lint, freshness inventory, drift detection, and coverage backlog generation, and the ingest loop now runs it automatically after finalization/QMD sync. Added a `wiki-freshness` skill and updated ingest/finalize/query skills so users should not need to remember the lower-level script names.

## 2026-06-24 — Minimal provenance status stamps

Added `wiki-provenance-stamp-status.py` and `scripts/lib/provenance_stamp.py` for classifier-approved low-risk legacy pages. The tool adds a `Freshness Status` block with `migration_status: legacy-inferred-minimal`; query packets now report these as `use-as-page-caution`, and coverage keeps them in the backlog as `minimal-stamp` instead of treating them as fully block-migrated.

## 2026-06-24 — Review caution stamps for high-risk drift pages

Extended minimal provenance stamps with `review_mode` values such as `source-mismatch`, `needs-currentness-answer`, and `sensitive-review`. The remaining high-risk drift queue can now be made safer at query time with caution-only stamps while still requiring page-by-page factual curation.

## 2026-06-24 — Provenance coverage backlog

Added `wiki-provenance-coverage.py` and `scripts/lib/provenance_coverage.py` to separate full Wiki provenance coverage from freshness drift. The coverage backlog writes `.wiki-scratch/provenance-coverage-backlog.md` for all canonical pages still lacking block provenance, while `wiki-drift-detect.py` remains the smaller risk-driven curation queue.

## 2026-06-24 — Raw-hit bridge for freshness queries

`wiki-freshness-query.py --qmd` now preserves raw-note QMD hits. Raw hits are resolved back to real vault paths, mapped to canonical Wiki pages via wikilinks and title variants, exposed as `raw_mappings`, and kept as `raw_evidence` when no canonical page can be found.

## 2026-06-24 — Freshness query fallback and comma-safe provenance sources

Fixed `wiki-freshness-query.py --qmd` so an empty QMD-to-Wiki resolution no longer falls back to scanning every Wiki page. Provenance inline lists now parse quoted comma-containing source paths correctly, while missing optional provenance fields remain allowed for gradual migration.

## 2026-06-24 — Query-time freshness packet

Added `wiki-freshness-query.py` and `scripts/lib/freshness_query.py` so retrieved Wiki pages can be converted into ranked canonical blocks for a specific query. The helper can also run local QMD discovery with `--qmd`, resolve QMD's normalized Wiki result IDs back to real vault paths, demote historical/stale/disputed evidence with explanations, and flag unmigrated legacy pages instead of silently trusting them.

## 2026-06-24 — Block provenance foundation for freshness-aware queries

Added a read-only `kb-prov-v1` provenance parser/validator and `wiki-provenance-lint.py` entrypoint. This is the first migration slice for query-time freshness: canonical pages can now carry stable block IDs plus a compact provenance callout without rewriting existing `wiki/` pages.

## 2026-06-24 — Freshness inventory, drift detection, and curation workflow

Added read-only freshness inventory, drift detection, page-curation packet scripts, and deterministic block-ranking tests, plus `wiki-curate-page` guidance for one-page canonical cleanup. Query, ingest, and finalize skills now treat freshness as block/query-time evidence first and canonical rewrites as targeted review work.

## 2026-06-24 — Supersession lint produces far fewer false positives

`wiki-supersession-lint.py` now skips review-queue matches inside code fences, table rows, headings, and inline-code-hugged phrases, plus self-references (a page describing its own rename). On the current vault this cut the queue from 96 to 75 noise-mostly entries before reviewer triage. Confirmed false positives still go in `.wiki-scratch/supersession-ignore.txt` (one path per line) and never reappear.

## 2026-06-24 — Sync refreshes agent skills first

`sync-all-repos.sh` now runs `scripts/system/copy-claude-skills-to-other-agents.sh` before syncing so `.agents/`, `.codex/`, and `.junie/` skill mirrors are up to date in every synced target.

## 2026-06-24 — Safer ingest batching and synced skills

Ingest now preserves colliding sanitized raw filenames instead of overwriting, rejects zero-sized batches, keeps unconverted HTML email exports visible to batching, and refreshes agent skill mirrors from `.claude/skills`.

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
