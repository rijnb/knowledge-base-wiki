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
- **Query** — `wiki-query` skill (default: use this when the user asks any question)
- **Ground conversation in KB** — `wiki-ground` skill
- **Health check / lint** — `wiki-doctor` skill
- **Creating wiki pages** — `wiki-templates` skill
- **Add missing page** — `wiki-add-missing` skill

## Obsidian CLI

When moving, renaming, or deleting files inside the vault, prefer the Obsidian CLI over plain `mv`/`rm` — Obsidian then updates all internal links automatically.

- Move/rename example: `obsidian vault="TomTom" move path=<vault-rel-path> to=<vault-rel-path>`
- Requires Obsidian to be running (`/Applications/Obsidian.app/Contents/MacOS/obsidian`)
- Full reference: run `obsidian help` or load the `obsidian:obsidian-cli` skill

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

## Tests

Tests live in `scripts/tests/`; run with: `python3 -m unittest discover -s scripts/tests -v`
