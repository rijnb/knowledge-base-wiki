# Release Notes

## 2026-08-24 — Six log/link integrity fixes (four reported externally)

**`prune_log` no longer deletes fetch records.** Entries with no `file` field — the `email-fetch` and `slack-fetch` records written by the `wiki-fetch-*` skills — were counted as "file no longer exists" and dropped. `wiki-fetch-slack` reads the newest `slack-fetch` entry back as its incremental fetch watermark, so `wiki-doctor --fix-simple-errors` silently reset it and the next Slack fetch re-fetched from scratch. These entries are now preserved verbatim, in place, and never deduplicated (repeated fetches of one source are history, not duplicates).

**Non-HTTP URI schemes are no longer reported as broken links.** `is_external()` accepted only `http`/`https`/`ftp`/`mailto`, so `cid:` (converted email attachments), `tel:`, `sms:`, `obsidian://`, `slack://` and friends fell through to the internal resolver and were reported broken. Now an explicit `EXTERNAL_SCHEMES` allowlist in `scripts/lib/links.py` — deliberately not a generic `<scheme>:` regex, which would classify note titles containing a colon (`[[Meeting: 2026 plan]]`) as external and hide genuinely broken links.

**Batch-log merging is validated** — new `scripts/system/wiki-merge-batch-logs.py`, used by `wiki-finalize-ingest` Step 1 in place of `cat .import/batch-log-*.jsonl >> wiki/log.jsonl`. The old append could not tell a valid entry from a half-written one, fused two entries into one corrupt line whenever a batch log lacked a trailing newline, and deleted the batch logs even when the append had failed. Every line is now parsed as a JSON object first; malformed lines are quarantined in `.import/batch-log-rejected.jsonl`; the batch files are removed only after the merged log is safely in place.

**`wiki-clear-ingest-batches` shows what it will delete.** New `scripts/system/wiki-clear-ingest-batches.py` (`--list` / `--apply`) replaces an inline `rm -f` over two overlapping globs that double-counted every claimed batch (3 files on disk, "Cleared 4 file(s)"), reported its count before deleting anything, and resolved `.import/` against whatever the current directory happened to be. The skill now lists the files before asking, and warns when the batch logs still hold ingest records that never reached `wiki/log.jsonl`.

**`wiki-doctor --format json` works without `--batch-mode`.** It started the curses review TUI regardless of output format, which aborted the whole run with `_curses.error: cbreak() returned ERR` after a full scan — the documented JSON output never appeared. Interactivity is now decided once, up front, and requires a real terminal on both ends plus a non-JSON format; without one the run falls back to printing its report.

**Agent skill mirrors resynced and guarded.** `.agents/`, `.junie/` and `.codex/` are copies of `.claude/skills` made by `copy-claude-skills-to-other-agents.sh`, but nothing failed when that sync was skipped: 8 of 19 skills had drifted, and 12 mirror files still told those harnesses to write `wiki/<topic>/_index.md` and `kb-prov-v1` provenance blocks — a layout and a format that no longer exist. Mirrors are back in sync, and `scripts/tests/test_skill_mirrors.py` now fails when they drift again.

Tests: 378 pass (`python3 -m unittest discover -s scripts/tests`), including new coverage in `test_links.py`, `test_fixers.py`, `test_cli_integration.py` and the new `test_batch_logs.py`.

## 2026-08-20 — Vault-wide OKF v0.2 frontmatter migration + wiki skills updated

One-time content migration across `wiki/` (backup: `~/.vault-backups/tomtom-pre-okf-20260820-130749.tar.gz`):

- **`status:` → `state:`** on 839 pages (values kept verbatim, e.g. `open`, `active (as of Dec 2019)`). `status:` is now reserved for OKF's page-lifecycle enum `draft|stable|deprecated`.
- **Type vocabulary fixed**: `type: competitor` → `competition` (83 pages), `type: systems` → `system` (1 page). Vocabulary is now exactly the 8 topic types.
- **kb-prov-v1 abolished**: 294 pages had their provenance callouts (and one inline HTML-comment variant) mapped to OKF v0.2 frontmatter — `sources: [{id, resource}]`, `generated: {by: "agent:wiki-ingest", at: <latest observed>}`, `verified: [{by: "agent:wiki-freshness", at: <latest checked>}]`. Per-block status/confidence detail was dropped by decision; `^block-id` anchors remain as plain anchors. Zero `kb-prov-v1` strings remain in `wiki/`.

**Skills updated** (`.claude/skills/`, synced to `.agents/` and `.junie/`): `wiki-templates` (all type templates: `state:` rename, required `description:`, OKF reserved-field section), `wiki-ingest-per-note` (requires `description:`; writes frontmatter provenance instead of callouts), `wiki-curate-page` (frontmatter provenance spec; human curation appends `verified: {by: "human:rijn.buve"}`), `wiki-query` (trust tiers from `verified.by` prefix), `wiki-freshness`, `wiki-doctor`, `wiki-add-missing`.

Verification: full suite 329 tests OK; wiki-doctor frontmatter check 6838 pages, 0 errors, 0 warnings; provenance lint 0 errors, 1 genuine warning (`wiki/systems/MySports Cloud.md` has `generated` but no sources).

`validate_provenance` (`scripts/lib/provenance.py`) now cross-checks `[^sN]` source footnotes against `sources[].id` — flows into `wiki-provenance-lint` and the freshness index automatically. New issue codes: `unknown-footnote-id`, `undefined-footnote-ref`, `footnote-resource-mismatch` (errors), `unreferenced-footnote-def` (warning). Code examples in fences/inline code and non-`sN` prose footnotes are ignored.

First run caught a real defect: `Knowledge Freshness Frontmatter Schema.md` carried two sources mangled into one escaped string (`…base.md\", \"README.md`) — a comma-heuristic bug in the legacy callout parser that merged a quoted bare filename (no `/`) into its predecessor. Fixed the parser in `scripts/lib/legacy_callout.py` (fully quoted values now always split) and repaired the page (dropped mangled `s6`/`s7`, re-pointed the ref to `[^s1][^s5][^s2]`). Vault lints clean: 0 errors.

The OKF migration dropped the claim↔source link (the `kb-prov-v1` callouts mapped `^block-id` anchors to sources; the new frontmatter only listed sources page-level). Restored it in OKF-native form:

- **New `scripts/system/wiki-restore-source-footnotes.py`** (+ `scripts/lib/source_footnotes.py`, `scripts/lib/legacy_callout.py` — vendored pre-OKF callout parser, extended for flow-style `{…}` block entries): joins the backup's callout (`anchor → resources`) with current frontmatter (`resource → sN`) and inserts `[^sN]` refs before each anchor plus a `[^sN]: [[resource]]` definitions block at page end. Dry-run by default, `--apply` to write, idempotent, JSON report. Tests in `scripts/tests/test_source_footnotes.py`.
- **Applied to all 292 pages**: 2,137 footnote refs inserted; 44 anchors on 28 pages had no callout entry (post-callout-era blocks, reported only). Reports in `.wiki-scratch/footnotes-{dryrun,apply}.json`.
- **Repaired 3 pages that silently lost provenance in the OKF migration** (their callouts used flow-style block entries the migration couldn't parse): `Level of Detail (LOD)`, `Connected Car - Aftermarket Platform (CoCa)`, `Fisker Ocean Program` — re-stamped `sources:` from the backup callouts.
- **Skills updated** (`wiki-ingest-per-note`, `wiki-curate-page`, `wiki-templates`): new pages and curated pages must cite each claim with `[^s<N>]` refs (before the `^block-id` anchor) and maintain the end-of-page footnote-definitions block.

## 2026-08-20 — Provenance tooling migrated from kb-prov-v1 callouts to OKF v0.2 frontmatter

All provenance/freshness scripts now read page-level provenance from YAML frontmatter (`sources`, `generated`, `verified`, `stale_after`) instead of the removed `> [!provenance]` callouts:

- `scripts/lib/provenance.py` — new `parse_provenance()` (constrained YAML-subset frontmatter parser) and frontmatter-based `validate_provenance()` (source id/resource + uniqueness, generated/verified by+at, YYYY-MM-DD dates; `generated` without `sources` is a warning). Callout parser deleted; duplicate `^block-id` detection kept.
- `scripts/system/wiki-provenance-lint.py` — same CLI/exit codes; pages without provenance are fine (coverage is separate); any leftover `kb-prov-v1` string in a non-index wiki page is now an error.
- `scripts/lib/provenance_stamp.py` + `wiki-provenance-stamp-status.py` — stamping inserts frontmatter `sources` (ids s1, s2, …) + `generated {by: "agent:wiki-ingest", at}` (optional `verified` via API); refuses pages that already have `generated:`/`sources:`. Manifest format unchanged. The "## Freshness Status" body section and mode text blocks were dropped (no body edits anymore).
- `scripts/lib/provenance_coverage.py` — coverage = page has `generated:` or `sources:`; statuses reduced to covered / no-provenance / invalid-provenance.
- `scripts/lib/freshness_index.py` — page-level inventory: `generated_at`, latest `verified_at`, derived `status` (current/stale via `stale_after`/unknown) and `confidence` (`human:` actor → high); reads renamed frontmatter key `state` (was `status`).
- `scripts/lib/freshness_query.py`, `drift.py`, `curation.py` — rank/score whole pages by frontmatter provenance dates; drift reasons renamed (`no-page-provenance`, `stale-page`).
- Tests rewritten/adapted in `scripts/tests/` (provenance, stamp, coverage, freshness index/query, drift, curation); full suite green (329 tests).

Every `wiki/**/*.md` page (except indexes) now carries a one-line `description:` frontmatter field (6838 pages backfilled). New shared extractor `scripts/lib/descriptions.py` (`extract_description()`: first sentence after frontmatter, HTML comments stripped, wikilinks kept intact, leading emphasis unwrapped, 160-char cap). New idempotent backfill script `scripts/system/wiki-backfill-descriptions.py` (`--dry-run` supported) inserts the field after `type:`/`tags:`, YAML double-quoted. `scripts/system/wiki-create-index-pages.py` now prefers the `description:` field for entry summaries and falls back to the extractor. Tests in `scripts/tests/test_descriptions.py`.

## 2026-08-20 — wiki-doctor: new frontmatter validation check

`scripts/wiki-doctor.py` (batch mode) now validates wiki page frontmatter via `scripts/lib/checks/frontmatter.py`, covering every `wiki/**/*.md` except `index.md`. Errors: missing/unparseable frontmatter block, missing or unknown `type:` (allowed: competition, concept, conversation, decision, person, problem, project, system), `status:` outside the OKF enum `draft|stable|deprecated` (old subject-state values belong in `state:`), and any `kb-prov-v1` legacy provenance remnant. Warning (does not affect exit code): missing `description:`. Reported in both text (`FRONTMATTER CHECK` section) and JSON (`frontmatter_issues` + `frontmatter_summary`); no `--fix` behavior. Tests added in `scripts/tests/test_checks.py` and `scripts/tests/test_cli_integration.py`.

## 2026-08-20 — Index rename `_index.md` → `index.md` + OKF v0.2 progressive disclosure format

Topic indexes are renamed from `wiki/<topic>/_index.md` to `wiki/<topic>/index.md` (8 files, moved via the Obsidian CLI so all inbound wikilinks were rewritten automatically), aligning the vault with OKF v0.2's reserved-filename convention (§8) — an OKF consumer looking for `index.md` below the bundle root previously found nothing, losing all progressive disclosure. This fixes defect #1 and part of defect #2 of the 2026-08-20 OKF compliance assessment.

**Generator** (`scripts/system/wiki-create-index-pages.py`) rewritten for a progressive disclosure format, all deterministic (no LLM involved):
- `wiki/index.md` (bundle root) is now the **only** index with frontmatter, carrying only `okf_version: "0.2"`; its section table gains a per-topic page count.
- Topic indexes carry **no frontmatter** (§8-strict; verified nothing reads `type: index` — all index detection in scripts is filename-based). The rebuild date moved to the byline.
- Topics with >100 pages are grouped under letter headings (`## A` …, diacritics NFKD-folded, e.g. Ž→Z) with a `Sections:` jump line carrying per-letter counts, so a consumer reads one letter section instead of a 1,600-line file. Smaller topics stay flat.
- New `## Recently updated` block (top 10 by frontmatter `date`, when ≥10 dated pages).
- Entry summaries are first-sentence, capped at 160 chars; both sentence-split and cap are wikilink-balance-safe (never emit an unclosed `[[…`).

**Guard scripts**: dropped `_index.md` from the index-filename checks in `scripts/lib/paths.py`, `scripts/lib/checks/orphans.py`, `scripts/lib/checks/stubs.py`, `scripts/system/wiki-assign-dates.py`, `scripts/system/wiki-supersession-lint.py`, `scripts/system/migrate-converted-to-resources.py`.

**Skills updated** to the new name/format: `wiki-templates` (both index template sections rewritten; indexes now documented as generated artifacts — do not hand-edit), `wiki-query`, `wiki-finalize-ingest`, `wiki-ingest-per-note`.

**Important**: the generator regenerates all 9 index files wholesale on every finalize-ingest — updating it in the same change as the rename was mandatory, or the next ingest would have silently recreated the `_index.md` files. Manual edits to any index file are still overwritten at rebuild, as before. Historical prose mentions of `_index.md` in `raw/` and the INBOX assessment were deliberately left untouched (evidence, not live docs).

Verification: provenance lint clean (6,838 files), full test suite passes (296), all 10,209 wikilinks across the 9 regenerated indexes resolve. Known pre-existing issue (not a regression, also present in the old indexes): three `wiki/problems/` pages had `#` in their filenames (`…(smart-data-access#240).md` etc.), which Obsidian parses as a heading anchor in any wikilink to them. **Resolved same day**: renamed `#` → `_` (`…(smart-data-access_240).md`) via the Obsidian CLI, with the 7 inbound wikilinks rewritten manually (Obsidian's auto-rewrite cannot follow links it mis-parses as heading anchors) and indexes regenerated. Display texts and prose mentions of the real GitHub issue refs (`smart-data-access#240`) were deliberately kept — only link targets and filenames changed. All 10,209 index wikilinks verified resolving afterwards.

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
