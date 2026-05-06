# Workflows

Before your start, read the file `config/personal_info.md` (it may not exist, which is OK).
Use the information from that file to make your responses more relevant to me.

Use the appropriate `wiki` skill for each action:
- **Ingest** (notes, Confluence, start bulk) — `wiki-ingest` skill
- **Ingest Slack** (fetch channels and DMs) — `wiki-slack-ingest` skill
- **Ingest next batch** (parallel sessions) — `wiki-ingest-next-batch` skill
- **Finalize ingest** (merge logs, rebuild indexes) — `wiki-finalize-ingest` skill
- **Query** — `wiki-query` skill (default: use this when the user asks any question)
- **Health check / lint** — `wiki-lint` skill
- **Creating wiki pages** — `wiki-templates` skill
- **Add missing page** — `wiki-add-missing` skill

# Topic types in `wiki/`

- **Competitors** — competing companies, products, and approaches
- **Concepts** — technologies, standards, mental models, domain vocabulary
- **Conversations** — valuable results of earlier queries/conversations
- **Decisions** — why decisions were taken, on what basis, by whom, and when
- **Problems** — active and past problems
- **People** — colleagues, contacts, external stakeholders, teams
- **Projects** — active and past initiatives
- **Systems** — our products, platforms, and services
