# Release Notes

## 2026-08-18 — wiki-doctor: new misplaced-attachment check

`wiki-doctor` (batch mode) now verifies that every attachment linked from a note under `raw/` or `INBOX/` actually lives in that note's own `_resources/` directory (legacy `*.resources/` siblings accepted). Previously only two weaker checks existed: broken links (target must exist *somewhere*) and loose files (non-markdown must be in *some* `_resources/`), so a raw note embedding an attachment from another directory's `_resources/` — or from the legacy vault-root `_resources/` — passed silently. `wiki/` notes are exempt by design: they may reference `raw/` attachments, and companion notes living *inside* a resources tree may reference anything in that same tree (no nested `_resources` demanded). An attachment co-located with *one* of its referencing notes satisfies the rule for all of them. Reported as `misplaced_attachments`/`attachment_summary` in JSON and a "MISPLACED ATTACHMENTS" section in text output, and counts toward the non-zero exit code. `--fix-simple-errors` relocates each misplaced attachment (once per unique file) into the referencing note's own `_resources/` via the Obsidian CLI — links update automatically; clash-safe renaming; skipped with a warning when Obsidian is unavailable. Attachment resolution searches `raw/`, `wiki/`, `INBOX/` and the legacy vault-root `_resources/`; skips symlinks (matching the loose-file check) and files outside the vault; and normalizes curly quotes like `resolve_wikilink` does. New module `scripts/lib/checks/attachments.py` + `fix_misplaced_attachments` in `scripts/lib/fixers.py`, tests in `scripts/tests/test_attachments.py`. First run on the real vault found 69 misplaced attachment links (32 unique files), mostly bare-name embeds pointing at the legacy vault-root `_resources/` and a few at `INBOX/_resources/`.

## 2026-07-29 — Fix `finalize_lock: unbound variable` crash at end of `wiki-ingest.sh`

`run_phase_finalize` installed `trap 'rmdir "$finalize_lock" ...' RETURN` to release the parallel-session finalize lock. A RETURN trap is *not* per-function: it stays installed after the function returns and fires again on every later function return, where the `local` no longer exists — so with `set -u` the script died with `line 1019: finalize_lock: unbound variable` (line 1019 is `main()`'s definition line) once `main` returned, after all ingest work had already completed. Fix: expand the lock path into the trap body at install time and have the trap clear itself (`trap - RETURN`), so it fires exactly once. Applied the same fix to the identical latent pattern for `hdr_file` in the usage-API call (harmless there only because that function always runs in a command-substitution subshell).

## 2026-07-22 — Fix finalize step order so freshly-ingested notes aren't re-flagged

`wiki-finalize-ingest` stamped log hashes (old Step 1) *before* running `wiki-assign-dates` (old Step 3). The date pass writes `date`/`date_span`/`date_confidence` frontmatter onto raw notes, changing their bytes — so every just-ingested note ended up with a stale hash and was re-flagged as "new" by `wiki-create-import-batches` on the next import (observed: two already-ingested clips reappeared in a later batch). Reordered the skill so hashing runs last: **Merge → Assign dates → Stamp/relink → Rebuild indexes → Summarize → Post-processing → End**, with an explicit "do not reorder" note explaining why. No code changes — `wiki-stamp-log-hashes.py` still never overwrites existing hashes; it now simply sees the final dated content when it first stamps each entry.

## 2026-07-08 — Stop slugified wikilinks in answers and generated pages

Answers and generated pages sometimes emitted slug-style wikilinks (`[[Note-Links-Like-This]]`) instead of the real spaced filename (`Note Links Like This`), so the links did not resolve in Obsidian. Root cause was weak/missing guidance plus a link resolver that could not repair the slugs. Changes:
- **`wiki-query` skill**: the citation instruction now states explicitly that a wikilink target is the note's exact filename with spaces — never slugified/hyphenated — with correct/incorrect examples.
- **`CLAUDE.md`**: added a "Linking to notes" section (always loaded) with the same rule, covering both answers and pages.
- **`wiki-add-missing`, `wiki-curate-page`, `wiki-ground` skills**: added a one-line "Wikilink format" reminder.
- **`scripts/lib/resolve.py`**: added the hyphen to `_PROBLEMATIC_CHARS` so `wiki-doctor`'s fuzzy resolver maps slug links back to their spaced filenames. Safe because file stems normalize through the same function (genuinely hyphenated titles still match themselves) and only unique matches are auto-fixed. Added three tests in `scripts/tests/test_resolve.py`; full suite passes (265 tests).

## 2026-07-03 — wiki-doctor: vault-wide link resolution

`wiki-doctor` reported false "file not found" for wikilinks whose targets live outside `raw/` and `wiki/` (e.g. `_resources/` at the vault root), because the link-resolution index only walked those two trees. Obsidian resolves a link against any file anywhere in the vault, so `VaultIndex` now builds its path-suffix index from a whole-vault walk (dot-directories like `.git`/`.obsidian` excluded, matching Obsidian). The set of `.md` files that get scanned/linted is unchanged — still `raw/` and `wiki/` only.

## 2026-06-25 — Freshness review follow-up fixes

Fixed the actionable review findings in the freshness/provenance tooling:
- Freshness inventory, drift, and QMD raw-hit mapping now respect `ingest: false` protected raw notes and their explicitly linked local raw files.
- `wiki-freshness.sh` now runs all freshness/provenance steps before returning a non-zero status, so lint errors no longer prevent drift and coverage queues from being written.
- Minimal provenance stamping rejects manifest page paths outside `wiki/` under the selected vault root.
- Added missing-value and negative-limit guards for freshness/migration helper entrypoints.

## 2026-06-24 — Code-review fixes across provenance/freshness/drift tooling

Fixed issues found in a code review of the new provenance/freshness/drift/migration tooling:
- **Freshness ranking**: check date was dead weight (a capped, folded-in term that saturated for every real date). Recency is now a genuine secondary sort key (newer-checked first) after status+confidence; `score_block` no longer folds in the date.
- **Provenance source lists**: unquoted, unprefixed identifiers (e.g. `[alpha, beta]` or `[slack:…, confluence:…]`) were silently merged into one element. The comma-splitter now only keeps a comma inside a value when it sits in a recognized, unterminated source reference.
- **Freshness index**: two block IDs in one paragraph each cross-contaminated the other's `text`; each block now owns only its own line(s).
- **Provenance lint severity**: added a `missing-sources` *warning* for claim blocks with no sources (minimal stamps exempt); lint now exits non-zero only on errors and reports error/warning counts. Coverage and query "invalid-provenance" classification now keys on error-severity only.
- **wiki-migrate-existing.sh**: the legacy-layout step now runs inside `--root` so `migrate-converted-to-resources.py` resolves paths/log against the target vault instead of the caller's cwd; added `--strict` to propagate step failures to the exit code.
- **wiki-baseline-raw-log.py**: log entries now match the canonical writer's insertion order (dropped `sort_keys`); the existing log is backed up to `.wiki-scratch/` before append, and append failures (e.g. OneDrive locks) surface as a clean error.
- Minor: shared `wiki_pages`/`wikilink_target`/`split_frontmatter` helpers (de-duplication), non-negative `--limit`/`--qmd-limit` guards in `wiki-freshness-query.py`, `--root` arg guard in `qmd-sync-collections.sh`, and ambiguous-title handling in drift detection.

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
