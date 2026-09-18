# Release Notes

_Newest first. A few short bullets per release — only what changed and why it matters. Detail lives in the commit messages and in the plan notes each entry points to._

## 2026-09-18 — `work-topic` skill

- Say "add a topic": interviews you, then writes `work/topics/<Topic>.md` and recompiles.
- Offers to fold the subject into an existing topic instead, and defaults to `watching` — only 10 topics may be active.

## 2026-09-18 — `wiki-doctor` tag check

- Flags tags absent from `config/tags.md` and malformed shapes, several of which Obsidian silently refuses to index.
- Vault clean: 11,283 notes, 0 bad tags. Every ingest now validates its own tags.

## 2026-09-18 — Tagging wired into both ingest paths

- `wiki-ingest.sh` Phase 4 and the `wiki-finalize-ingest` skill both tag new notes; the skill covers interactive ingests the shell phase never reaches.
- Must run after the rename pass: `assign` reads the excerpt cache, which stores paths.

## 2026-09-18 — Tag assignment applied

- 4730 notes tagged. Coverage 99% of 11,282 notes, mean 4.3 tags; `raw/` went from 971 tagged to 3735 of 3736.
- Wrong-namespace suggestions are corrected when one approved tag shares the term — 84% of rejects were that, recovering 1312 tags.
- Structural files (`index.md`, `CLAUDE.md`, …) are no longer tagged, and notes that had no frontmatter are revertible again.

## 2026-09-17 — Tag assignment uses Sonnet, not Haiku

- Measured A/B: 3.3× faster, half the off-list rate, steadier tag counts. $6.81 vs $3.41 for the whole phase.
- The two models agreed on almost nothing (Jaccard 0.21), so the diffs decided it, not the statistics.

## 2026-09-17 — Tag remap applied

- 8464 notes rewritten: 39,692 occurrences over 4444 flat tags → 33,091 over 1857 hierarchical ones.
- Refuses any target absent from `config/tags.md`; every note backed up and hash-verified revertible.
- Frontmatter surgery preserves each note's existing shape, so only the tags line changes.

## 2026-09-17 — Tag taxonomy built

- 4443 tags → 1818 canonical in 19 namespaces, via two LLM passes and three deterministic ones.
- `.tags/overrides.tsv` holds the hand-made gate corrections and wins over every automatic pass.
- `--phase consolidate` re-derives everything from the checkpoint for free.

## 2026-09-17 — `wiki-tags.py`: inventory, hashtag escaping, excerpts

- New tag pipeline, phases 0–2. Dry run is the default throughout.
- 92 stray inline hashtags escaped across 47 files; 39 tags Obsidian never indexed are now classified.
- The Obsidian CLI only answers when the app is already running — otherwise it boots it and hangs the caller.
- Plan and measurements: `INBOX/Plan Systematic Tags.md`.

## 2026-09-17 — `work-*` tooling hardened

- Three adversarial reviews, every finding reproduced before it was accepted; suite 650 → 747.
- `--archive-done` is now safe on real pages (encoding, code fences, CRLF), and pages that used to vanish parse.
- "Contact" now means evidence of contact, not a name appearing somewhere — several rows were wrong.

## 2026-09-17 — `review-doc` skill

- "Review this document" → a draft verdict you adjudicate, grounded in the KB.
- One reviewer subagent per lens in parallel, then a fresh adversarial pass that confirms, weakens or drops each finding.
- Never sends anything; writes only the review file.

## 2026-09-17 — `work-brief` skill and script

- Assembles the deterministic packet a pre-1:1 brief is written from; the five lines are the skill's judgement.
- Reuses the weekly script's parsing, so a brief and a review can never disagree about a date or a name.

## 2026-09-17 — `work-weekly` skill and script

- Monday review: snapshot, backlog, overdue stakeholders, what happened on your topics, unmapped material.
- Everything countable in the script, only the judgement in the skill — keeps the review inside half an hour.
- ~0.4 s over ~5.5k raw files.

## 2026-09-17 — `work-backlog.py` compiler

- Compiles `work/topics/` into `work/Backlog.md`: portfolio, open actions, delegated, overdue, deadlines, smells.
- Deterministic, so the topic pages stay the single source of truth and the backlog can be deleted at will.
- Also `--archive-done` (checked boxes into the log) and `--recap PERIOD`.

## 2026-09-17 — Generated `work-*` files warn visibly

- The "do not hand-edit" banner is a callout, not an HTML comment — a comment is invisible in reading view.

## 2026-09-09 — Legacy-provenance check scoped to real callouts

- The `kb-prov-v1` error now needs an actual callout, so the nine pages documenting the old scheme stop failing.

## 2026-09-08 — Provenance validator tolerances

- A footnote link missing only the `.md` extension is no longer a mismatch; YAML flow mappings parse.
- Fixed 95 false `invalid-provenance` pages.

## 2026-09-07 — `wiki-find` skill and script

- Lists *every* wiki page on a subject, from the index files and frontmatter tags. Whole vault in <1 s.
- Replaces ~48k tokens of repeated grep that truncated its own answer.

## 2026-09-06 — Junie support removed

- `.junie/` mirror deleted; backends are now `claude`, `vibe`, `codex`.

## 2026-09-06 — Fail-safe allowlist `.gitignore` and hooks

- Everything is ignored by default; only framework infrastructure is un-ignored, so notes cannot be committed by accident.
- `pre-commit`/`pre-push` block anything outside the allowlist even after `git add -f` or `--no-verify`.
- Activate per clone with `scripts/install-hooks.sh` — `core.hooksPath` is not cloned.

## 2026-09-04 — README audit

- Rewritten against the code: provenance section, QMD collection, doctor flags, skills and scripts all corrected.

## 2026-08-30 — Wikilink rewriters tolerate padding

- `[[ Padded Link]]` silently no-opped in every rewriter; all five now match and normalise the padding.
- New `write-article` skill: publication-quality articles from vault plus web research, with footnoted claims.

## 2026-08-27 — `write-article` refinements

- Articles end with a weaknesses table (stable IDs, so "fix W3" works) and a heading-alternatives table.
- An explicit end-of-article marker separates the piece from its review apparatus.
- Mermaid diagrams need a minimum font size.

## 2026-08-26 — Orphan attachments in the review TUI

- `[ATCH]` rows with preview and delete; no "keep" action, because there is no frontmatter to stamp on a binary.

## 2026-08-25 — Orphan attachments, Unicode links, footnote check

- New orphan-attachment check for the vault-root `_resources/` — report-only, since there is no note to relocate to.
- **NFC normalisation in link resolution**: the same vault gave different results on APFS and HFS+. Now identical.
- New accent-duplicate check; 3 real duplicate pairs merged.
- New footnote check: `[^s2]` is a local ref the link checker never saw. Vault clean across 3,329 refs.

## 2026-08-24 — Six log/link integrity fixes

- `prune_log` no longer deletes fetch records, which had been silently resetting the Slack fetch watermark.
- Batch-log merging is validated; the old `cat` append fused entries and deleted logs even on failure.
- Non-HTTP URI schemes (`cid:`, `tel:`, `obsidian://`) are no longer reported as broken links.
- Skill mirrors resynced, and `test_skill_mirrors.py` now fails on drift.

## 2026-08-20 — OKF v0.2 migration

- Vault-wide frontmatter migration: `status:` → `state:` on 839 pages, type vocabulary fixed, `kb-prov-v1` abolished.
- Provenance moved from body callouts to frontmatter, with `[^sN]` footnotes cross-checked against `sources[].id`.
- `_index.md` → `index.md` (8 files), index generator rewritten for progressive disclosure.
- Every non-index page gained a one-line `description:` (6,838 backfilled); new frontmatter check in `wiki-doctor`.

## 2026-08-18 — Misplaced-attachment check

- Verifies an attachment linked from `raw/` or `INBOX/` lives in that note's own `_resources/`; `--fix-simple-errors` relocates it.
- First run found 69 misplaced links across 32 files.

## 2026-07-29 — Fix `finalize_lock` crash at end of ingest

- A `RETURN` trap is not per-function: it fired on every later return and killed the script under `set -u`, after all work was done.

## 2026-07-22 — Fix finalize step order

- Hashes were stamped before the date pass rewrote the notes, so every fresh note was re-flagged as new.
- Order is now Merge → Assign dates → Stamp/relink → Rebuild → Summarize → Post-process.

## 2026-07-08 — Stop slugified wikilinks

- A wikilink target is the exact filename with spaces, never a slug — stated in the skills, `CLAUDE.md` and the resolver.

## 2026-07-03 — Vault-wide link resolution

- Links to files outside `raw/` and `wiki/` were falsely reported broken; the index now walks the whole vault, as Obsidian does.

## 2026-06-25 — Freshness follow-up fixes

- `ingest: false` notes are respected throughout; `wiki-freshness.sh` writes its queues even when the lint fails.

## 2026-06-24 — Provenance and freshness tooling

- Block provenance, freshness inventory, drift detection, curation packets and a query-time freshness packet.
- One command, `scripts/wiki-freshness.sh`, runs lint → inventory → drift → coverage; the ingest loop calls it.
- `scripts/wiki-migrate-existing.sh` adopts an existing `raw/` + `wiki/` corpus without re-ingesting it.
- New `ingest: false` frontmatter opt-out.

## 2026-06-15 — Converters, date scope, rename-safe dedup

- Ingest uses the converter scripts for `.eml`/`.html`/`.vtt`, so filenames and frontmatter are right.
- "Already ingested" is decided by content hash, not filename: renaming a note no longer re-ingests it.
- Date assignment never touches top-level vault files.

## 2026-06-11 — Test suite and loose-file check

- New test suite under `scripts/tests/`.
- `wiki-doctor` detects non-Markdown files outside `_resources/` and can move them.
- Converted sources now sit in `_resources/` with a companion `.md`, replacing the old `converted/` layout.

## 2026-06-10 — AI backend configuration and `wiki-ground`

- LLM-backed scripts read `ai_backend` from `config/settings.md`; no code edits to switch.
- New `wiki-ground` skill grounds a whole conversation in the knowledge base.
