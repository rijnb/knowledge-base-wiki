# Workflows

Before your start, read the file `config/personal_info.md` (it may not exist, which is OK).
Use the information from that file to make your responses more relevant to me.

## Wiki skills

`wiki-query` is the default for any question — use it first. Ingestion flows through `wiki-ingest` (which auto-loads `wiki-ingest-per-note` rules for per-note processing). `wiki-doctor` is the health check; run with `--fix-simple-errors` to auto-relocate loose files using the Obsidian CLI.

Use the appropriate `wiki` skill for each action:
- **Fetch mail** (sync email inbox) — `wiki-fetch-mail` skill
- **Fetch slack** (fetch channels and DMs) — `wiki-fetch-slack` skill
- **Ingest** (notes, Confluence, start bulk) — `wiki-ingest` skill
- **Ingest next batch** (parallel sessions) — `wiki-ingest-next-batch` skill
- **Finalize ingest** (merge logs, rebuild indexes) — `wiki-finalize-ingest` skill
- **Migrate existing KB** (adopt framework without bulk re-ingesting) — `wiki-migrate-existing` skill
- **Query** — `wiki-query` skill (default: use this when the user asks any question)
- **Find all notes on a subject** (inventory / list of relevant pages) — `wiki-find` skill
- **Ground conversation in KB** — `wiki-ground` skill
- **Health check / lint** — `wiki-doctor` skill
- **Curate one page** — `wiki-curate-page` skill
- **Creating wiki pages** — `wiki-templates` skill
- **Add missing page** — `wiki-add-missing` skill

## Work skills

Personal work organisation lives in `work/` (topic pages, backlog, stakeholders) and is
compiled by `scripts/work-backlog.py`.

- **Monday weekly review** (scan, triage, this week's chosen work) — `work-weekly` skill
- **Pre-1:1 stakeholder brief** (five lines before a 1:1) — `work-brief` skill
- **Review a document, deck or proposal** (or a quick take on a question) — `review-doc` skill

## Obsidian CLI

When moving, renaming, or deleting files inside the vault, prefer the Obsidian CLI over plain `mv`/`rm` — Obsidian then updates all internal links automatically.

- When aksed to move a note to `xyz`, check if that directory exists in `raw/` or `wiki/` first (the user may not specify the whole path)
- Move/rename example: `obsidian vault="TomTom" move path=<vault-rel-path> to=<vault-rel-path>`
- **Requires Obsidian to be already running** (normally `/Applications/Obsidian.app/Contents/MacOS/obsidian`).
  With the app running, a query is a fast client call that exits by itself. With the app closed, the
  `obsidian` shim *is* the app binary: it boots the app, prints startup/update logs, never answers the
  query, and hangs any caller waiting on it — including `subprocess.run(capture_output=True)` and a
  plain `cmd > file`
- So check first, don't just add a timeout: `_find_obsidian_cli()` + `_obsidian_responds()` in
  `scripts/lib/fixers.py`. Interactively, `obsidian vault="TomTom" files total` is the cheap probe
- Always close stdin (`stdin=subprocess.DEVNULL`); the CLI waits on it otherwise
- Full reference: run `obsidian help` or load the `obsidian:obsidian-cli` skill

## Tags

`config/tags.md` is the curated tag vocabulary and the single source of truth. Add a tag
there *before* using it; never invent one on the fly.

- Shape: `namespace/term` or `namespace/term/term`. Never 1 segment, never 4. Lowercase,
  hyphens inside a segment. `year/YYYY` is the one exempt pattern
- Never a person's name and never a bare company name — a customer programme is `project/<name>`
- **Read the tag inventory via `obsidian tags`, never grep.** The CLI is the only thing that sees
  inline hashtags as tags, and it is what Obsidian itself filters on. Note that it reports phantom
  *parent aggregates* (`#year` carries the summed count of every `year/*` though no note declares it)
- Reading one note's own frontmatter may stay an ordinary file read
- Writes go through `scripts/wiki-tags.py`, not by hand and not via `obsidian property:set`
- Plan and current status: `INBOX/Plan Systematic Tags.md`

## Topic types in `wiki/`

- **Competition** (`wiki/competition/`) — competing companies, products, and approaches
- **Concepts** (`wiki/concepts/`) — technologies, standards, mental models, domain vocabulary
- **Conversations** (`wiki/conversations/`) — valuable results of earlier queries/conversations
- **Decisions** (`wiki/decisions/`) — why decisions were taken, on what basis, by whom, and when
- **Problems** (`wiki/problems/`) — active and past problems
- **People** (`wiki/people/`) — colleagues, contacts, external stakeholders, teams
- **Projects** (`wiki/projects/`) — active and past initiatives
- **Systems** (`wiki/systems/`) — our products, platforms, and services

## Release Notes

After any changes to scripts (`scripts/`) or skills (`~/.claude/skills/`), append a brief entry to `INBOX/RELEASE-NOTES.md` describing what changed and why.

## File names for notes

- Use plain readable text, no slugs (no hyphens instead of spaces)
- No accents or diacritics (e, i, o — not é, î, ö)
- No characters that have meaning for the file system: `:`, `/`, `\`, `*`, `?`, `"`, `<`, `>`, `|`

## Linking to notes

When citing or linking a note — in an answer or inside a page — the wikilink target must be the note's exact filename, with spaces. Never slugify. Write `[[Real-Time Map]]`, not `[[Real-Time-Map]]`; `[[1-N Device Association]]`, not `[[1-N-Device-Association]]`. Do not convert spaces to hyphens; keep hyphens only where the real filename has them. Slugified links do not resolve in Obsidian.

## Tests

Tests live in `scripts/tests/`; run with: `python3 -m unittest discover -s scripts/tests -v`
