# Provenance-Aware Knowledge Base Wiki

(C) 2026, Rijn Buve

This repository started as an implementation of [Andrej Karpathy's idea](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) for an LLM-maintained knowledge base: keep source notes in a folder, let an LLM maintain a Wiki on top of them, and use the Wiki as the practical interface for remembering and reasoning. This implementation keeps that core idea, but goes considerably further. It is designed for long-lived work knowledge, where old notes do not merely accumulate; they need to be curated, checked, superseded, and sometimes deliberately ranked lower when answering current questions.

The knowledge base is structured as an [Obsidian](https://obsidian.md) vault, assisted by the semantic database [QMD](https://github.com/tobi/qmd). Raw evidence lives in `raw/`; canonical pages live in `wiki/`. Ingestion adds and updates canonical pages, while curation improves selected pages over time using source evidence, block-level provenance, and freshness metadata. Provenance-aware query tooling can explain when a claim is current, historical, superseded, disputed, or only minimally migrated, so outdated information is not silently treated as equally reliable.

The implementation supports Anthropic Claude and JetBrains Junie (both CLI) to ingest, curate, query, and maintain the knowledge base.

## Purpose

The primary goal is **efficient decision intelligence**: understanding why decisions were taken, on what basis, by whom, and when. Secondary goals include mapping how technologies and systems relate, who is involved in what, and how competitors compare. And 'efficient', because the mechanism needs to be token (and environmentally) efficient.

**Division of labor:** 
- The user curates source files in `raw/`.
- LLM does all writing, cross-referencing, and bookkeeping in `wiki/`.
- Obsidian is the UI for entering/accessing notes and asking questions (e.g. through `Claudian`).

## Quick Start

```bash
# 1. Clone this repo
git clone <repo-url> ~/my-knowledge-base

# 2. Create raw/ and wiki/ directories (these are not stored in git)
cd ~/my-knowledge-base
mkdir -p raw/{notes,clips,emails,transcripts,scans,slack} wiki

# 3. Install QMD (the semantic search engine)
npm install -g bun
npm install -g @tobilu/qmd

# 4. Register all subdirectories as QMD collections and build the index
./scripts/qmd-full-reindex.sh

# 5. Install the QMD skill for Claude/Junie
qmd skill install --global --yes

# 6. Register QMD as a Claude Code MCP server (add to ~/.claude/claude_desktop_config.json)
#    Or just ask Claude: "read this README.md and install QMD as an MCP server"

# 7. Open this directory as an Obsidian vault: File → Open Folder as Vault
```

After setup, put your notes in `raw/` and tell Claude: **"ingest new raw notes"**.
Alternatively, run:

```bash
./scripts/wiki-ingest.sh
```

After ingesting notes, run the Linter regularly to keep your knowledge base clean:

```bash
./scripts/wiki-doctor.py
```

Freshness checks are the third regular maintenance action, alongside ingest and doctor. You can ask **"freshness check"**, or run:

```bash
./scripts/wiki-freshness.sh
```

You can keep notes that you do not want to be ingested yet (like drafts), in `INBOX`. The inbox will not be part of the ingestion process.

For sensitive Markdown notes that should remain in `raw/` but never be ingested, add frontmatter:

```yaml
---
ingest: false
---
```

The batch importer skips that note and any local `raw/` files explicitly linked from it with wikilinks, embeds, or Markdown links/images. It prints the skipped note basename with the number of linked files skipped, and it does not write a skip entry to `wiki/log.jsonl`. Remove the field later to make the note eligible for ingestion again.

## Update the framework regularly

The framework is updated regularly, so it's wise to `git pull` every now and then:

```bash
cd ~/my-knowledge-base && git pull
./scripts/qmd-full-reindex.sh   # re-register and update any new subdirectories
```

## Prerequisites

**Required:**
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (CLI) — or JetBrains Junie
- [Node.js / npm](https://nodejs.org/) — for installing bun and qmd
- [QMD](https://github.com/tobi/qmd) — local semantic search engine (`npm install -g @tobilu/qmd`)
- [Obsidian](https://obsidian.md) — vault UI (free, Mac/Windows/Linux)
- git

**Optional:**
- [pdftotext](https://poppler.freedesktop.org/) — faster/cheaper PDF extraction (`brew install poppler`); LLM vision is the fallback
- [Obsidian Web Clipper](https://obsidian.md/clipper) — one-click web article saving to `raw/clips/`
- [Claudian](https://github.com/YishenTu/claudian) — run Claude from within Obsidian (ask Claude to install it safely)
- [Amphetamine](https://apps.apple.com/app/amphetamine/id937984704) (Mac App Store) — prevents Mac sleep during long overnight ingests

## MCP Server Setup

Register QMD as a MCP server in `~/.claude/claude_desktop_config.json` (or ask Claude to do it):

```json
{
  "mcpServers": {
    "qmd": {
      "command": "qmd",
      "args": ["mcp"]
    }
  }
}
```

The Slack integration is managed via your claude.ai organization. Authorize it yourself at **claude.ai → Settings → Connectors**. Once authorized, the Slack tools are available automatically in all Claude sessions — no local configuration needed.

The email integration uses Microsoft Power Automate to save emails to a OneDrive folder, which syncs to your local disk. Ask "fetch mail" to copy files from that folder into `raw/emails/` and queue them for ingestion.

---

## In a nutshell

- **Create and collect notes:** 
	- User produces raw notes and stores them in the `raw/notes` directory.
	- User uses the Obsidian Web Clipper to store notes in `raw/clips`.
	- User stores `.vtt` meeting transcripts in `raw/transcripts`.
	- User asks "fetch mail" to copy emails from the configured inbox to `raw/emails/`, or drags `.eml`/`.html` files there manually.
	- User stored handwritten notes or scanned pages (PDF, JPG) in `raw/scans`.
	- User fetches Slack channels and DMs by asking "fetch slack" — messages are written to `raw/slack/`.

	- **Ingest notes:**
		- User asks to "ingest new raw notes", "ingest Confluence page `<URL>`" or runs `wiki-ingest.sh`.
		- LLM converts non-Markdown inputs (`.vtt` transcripts, `.eml`/`.html` emails, `.pdf`/`.jpg` scans): the original file is moved into a `_resources/` subdirectory of its directory, and a companion `.md` note is written next to it (in the same directory as the original was).
		- Markdown notes with `ingest: false` frontmatter, plus local `raw/` files explicitly linked from them, are excluded from batch ingestion and are not logged.
		- LLM partitions files into batches and processes them (large ingests use parallel LLM sessions 2–5; single batches are handled in one session).
	- After all batches are done, user says "finalize ingest" to merge session logs, rebuild `_index.md` files, and run post-processing (QMD re-index + health check).
   
- **Query wiki:**
	- User asks a high-level question.
	- LLM queries semantic database (with the `qmd` skill) for relevant page links (fast/token-efficient).
	- LLM processes suggested pages and produces answer to user.
	- LLM stores valuable conversations in `wiki/conversations/` to extend the knowledge base.

The combination of using a semantic database to fetch relevant pages before analyzing documents and reasoning about them, makes this implementation of a knowledge significantly faster and more token efficient than when it's using Markdown files only.

## Commands and skills

These skill commands and natural-language triggers are available.

Commonly used:

| Command / phrase          | Description |
| ----------------          | ----------- |
| ask any question          | Query the knowledge base (default behavior) |
| "ingest new notes"        | Start a new ingest of raw notes (Session 1 — coordinator flow) |
| "fetch slack"             | Fetch Slack threads and DMs into `raw/slack/`, then run `wiki-ingest.sh` to ingest |
| "fetch mail"              | Copy emails from configured inbox to `raw/emails/`, then run `wiki-ingest.sh` to ingest |
| "health check" or "lint"  | Check for orphaned pages, broken links, contradictions |
| "freshness check"         | Run the one-command freshness/provenance/drift/coverage check |
| "curate page" or "refresh this page" | Clean up one canonical page using block provenance, raw evidence, and freshness/drift signals |
| "add missing [topic]"     | Create a new Wiki page for a missing concept, person, system, etc. |

Less common / maintenance:

| Command / phrase          | Description |
| ----------------          | ----------- |
| "ingest next batch"       | Continue ingesting the next batch (Sessions 2–N flow) |
| "finalize ingest"         | Finalize the ingest: merge logs, rebuild indexes, run post-processing |
| freshness query packet    | Rank retrieved canonical blocks for one query using provenance freshness metadata |
| provenance coverage backlog | List canonical Wiki pages that still lack block provenance |
| minimal provenance stamp  | Add a query-time caution block to classifier-approved low-risk legacy pages |
| "clear ingest batches"    | Remove incomplete batch files to restart a failed ingest |
| "ground this conversation" or "wiki-ground [topic]" | Treat the KB as source of truth for this conversation; optionally front-load a topic. |

The `ingest next batch` and `finalize ingest` commands are only needed for importing large amounts of notes. LLM will notify you when you `ingest new notes` and it sees it requires batched importing.

### Pro-tip 1: use `wiki-ingest.sh` to ingest multiple files

You can use the script "scripts/wiki-ingest.sh" to start ingesting new notes. The advantage of this script is that it will try to ingest new notes in batches, and wait if your 5h limit has been reached. It will first execute "ingest new notes" followed by as many "ingest next batch" prompts as necessary (up to a specified maximum). Use "--help" for help for this script.

By default, the script reads `config/settings.md` and uses its `ai_backend`
frontmatter value. You can override it for a single run like this:
```
scripts/wiki-ingest.sh [--agent claude|vibe|codex|junie]
```

Use `wiki-ingest.sh --help` for more options.

### Pro-tip 2: use `wiki-doctor.py` to health-check your knowledge base

After each ingestion, the system can automatically run a health check on the knowledge base. It performs an automated, basic health-check and will check for missing topics, inconsistencies etc. using the LLM (takes time and tokens).

You can also run the basic health-check (which does not use the LLM) manually, by simply executing:
```
scripts/wiki-doctor.py
```

This opens an interactive TUI to deal with:
- Broken links: these can be removed, flagged or simply replaced with plain text.
- Orphaned pages: these can be deleted, or kept (marked with `orphan: false`).
- Stub pages (that were identified by the LLM but never filled in): these can be deleted, or kept (no longer marked as `stub: true`).

Using this interactive mode, you should be able to keep your knowledge base 100% free of false positive alerts so it's easy to see if the knowledge base is still sound or not. Use `--batch-mode` to suppress the TUI and get text/JSON output only.

### Pro-tip 3: run `qmd-full-reindex.sh` to re-index the semantic database

After running ingestion of notes (e.g. by `scripts/wiki-ingest.sh`), you are advised to run:
```
scripts/qmd-full-reindex.sh
```
This makes sure the sematic database (QMD) is fully up-to-date again. The LLM skill `wiki-query` makes use of the semantic database, so make sure it's up-to-date.

Instead of running a full re-index, you can also execute `qmd embed`. This is useful if you only ingested a couple of new notes, for example.

### Pro-tip 3b: use freshness tools to migrate gradually

Canonical pages can opt into block-level provenance using stable Obsidian block IDs plus a compact `kb-prov-v1` provenance callout. The easy command is:

```
scripts/wiki-freshness.sh --root .
```

The ingest loop also runs this automatically after finalization. `wiki-doctor.py` reminds you about it in its recommendations. You can run it manually any time you want to refresh the queues, especially after fixing doctor findings or before freshness-sensitive query work. The `.wiki-scratch/` queue files are generated local working state and are ignored by Git.

There are two different queues:

- `wiki-drift-detect.py` finds pages where related raw evidence, newer raw notes, or freshness statuses suggest a real query-time risk.
- `wiki-provenance-coverage.py` lists every canonical Wiki page that still lacks block provenance, even when no freshness risk has been detected yet.

Use the drift queue first for answer-quality improvements. Use the coverage backlog for gradual migration planning.

Classifier-reviewed legacy pages may receive a minimal status stamp instead of a full rewrite. This adds a `## Freshness Status` block plus `migration_status: legacy-inferred-minimal`, reducing query-time risk while keeping the page in the coverage backlog as `minimal-stamp`. The provenance metadata includes a `review_mode` such as `historical`, `source-mismatch`, `needs-currentness-answer`, or `sensitive-review`:

```
python3 scripts/system/wiki-provenance-stamp-status.py \
  --root . \
  .wiki-scratch/freshness-auto-ok.json
```

Use this only with a reviewed manifest. It is not a substitute for detailed block-level curation.

Use `wiki-curate-page` for one-page cleanup when drift detection shows that newer raw notes may affect a canonical page. To prepare a read-only packet for one target page:

```
python3 scripts/system/wiki-curate-page.py --page "wiki/concepts/Some Concept.md" --format json
```

To let the helper run QMD candidate discovery and then rank block-level claims before answering:

```
python3 scripts/system/wiki-freshness-query.py \
  --query "What is current?" \
  --qmd \
  --format text
```

With `--qmd`, raw-note hits are preserved too: raw hits that link to or title-match a canonical page are mapped into `raw_mappings` and can pull that canonical page into the ranked block packet; raw hits without a canonical match remain visible as `raw_evidence`.

If candidate pages were already retrieved by another search path, pass them explicitly with repeated `--page` arguments instead of `--qmd`.

Do not bulk rewrite `wiki/`.

### Pro-tip 4: Storing draft notes in `inbox` (not for ingestion yet)

You can store notes in `/inbox` while you're working on then and you don't want them ingested yet. Move them manually to `/raw/notes` once you think they are ready for ingestion. Then run `scripts/wiki-ingest.sh`.

### Pro-tip 5: Use Obsidian CLI

You can use the Obsidian CLI to interact with Obsidian on the command-line. Or, even better, have Claude interact with Obsidian using a CLI. For example, take a look at [https://github.com/kepano/obsidian-skills](Obsidian skills for Claude) to install skills for Claude on how to use Obsidian.

## Configuration

### Personalizing your setup

Provide personal info on who you are, what you do, and what your focus is, in `config/personal_info.md`:

```markdown
# Personal Info
My name is ...
I am ...

# My Main Focus
- Strategic decision making on technology choices.
- ...
```

If the file is missing, or it contains no info topics, default topics will be used.

### Configuring the local AI backend

Set the local LLM CLI used by scripts in `config/settings.md`:

```yaml
---
ai_backend: claude
---
```

Supported values are `claude` (`claude -p ...`), `vibe` (`vibe -p ...`), and
`codex` (`codex exec ...`). If the selected CLI is missing or fails, scripts
keep deterministic state intact and stop before consuming LLM-backed batches.

### Configuring Slack sources

Add a `# Slack` section to `config/personal_info.md` to configure which channels and DMs to fetch:

| Channel / DM            | Days | Mode                      |
|-------------------------|------|---------------------------|
| #architecture-decisions | 14   | signal                    |
| #team-platform          |      | all                       |
| @Alice van Dijk         | 7    | software design decisions |

- `#channel-name` — a public or private Slack channel
- `@Person Name` — a direct message thread with that person
- **Days** — how many calendar days back to fetch conversation updates (default: 7)
- **Mode** — `signal` filters out noise (absences, bot messages, bare acks); `all` includes everything; any other text is treated as a topic filter (only threads directly about that topic are included)

### Capturing emails automatically with Microsoft Power Automate

You can use [Microsoft Power Automate](https://make.powerautomate.com/) to automatically save incoming emails as `.html` files so they are picked up by the ingestion pipeline.

Create a flow with these steps:

1. **Trigger:** *When a new email arrives (V3)*
2. **Action:** *Get emails (V3)* — to retrieve the full email details
3. **Action:** *Get email (V3)* — to get the email body
4. **Action:** *Create file* (OneDrive for Business) — save to a dedicated OneDrive inbox folder (e.g. `KnowledgeSystem/inbox`). This folder syncs to your local disk; configure its local path in `config/personal_info.md` and ask "fetch mail" to copy files to `raw/emails/`.
   - **File name:** `@{outputs('Get_email_(V2)')?['body/receivedDateTime']}.html`
   - **File content:**
     ```
     FROM:@{outputs('Get_email_(V2)')?['body/from']},TO:@{outputs('Get_email_(V2)')?['body/toRecipients']},CC:@{outputs('Get_email_(V2)')?['body/ccRecipients']},BCC:@{outputs('Get_email_(V2)')?['body/bccRecipients']},SUBJECT:@{outputs('Get_email_(V2)')?['body/subject']},BODY:@{outputs('Get_email_(V2)')?['body/body']}
     ```

The resulting filename looks like `2026-05-13T08_32_05+00_00.html` — the date is extracted from it automatically. The `FROM`, `TO`, `CC`, `BCC`, and `SUBJECT` fields become YAML frontmatter; `BODY` is converted from HTML to Markdown. Once the OneDrive folder syncs to your local disk, ask "fetch mail" to pull the files into `raw/emails/` and drain the inbox.

### Configuring email fetch

Add an `# Email` section to `config/personal_info.md` to configure where "fetch mail" copies files from:

```markdown
# Email
| Setting | Value                        |
|---------|------------------------------|
| Inbox   | /path/to/your/onedrive/inbox |
```

Set `Inbox` to the local path of the folder that contains your exported email files (`.html` and `.eml`) from for example, the Power Automate flow. Files are copied to `raw/emails/` and deleted from the inbox on each fetch.

### Running Claude within Obsidian

You can run Claude from within Obsidian using the Claudian plugin. Install it by asking Claude:
```
Claude, I want you to install the following Obsidian plugin from Github. First, I want you to review
the plugin and make sure it is safe to install. And if it is safe, install it.
This is the repo: https://github.com/YishenTu/claudian
```

## Re-creating the Wiki from Scratch

To re-create the entire Wiki, remove the `wiki/` directory, `/clear` the LLM conversation and ask it to `ingest new raw notes`. Note that for large amounts of notes this may be expensive and take a long time.

**Note:** The `wiki/log.jsonl` file tracks which notes have already been ingested. If you share the `wiki/` directory across machines, any client can run incremental ingestions without re-processing everything.

## Checking Your Database

The database is automatically checked for errors after ingesting new notes. To check manually:
```bash
# Basic check (no LLM, fast):
./scripts/wiki-doctor.py --batch-mode --format text

# Interactive TUI (deal with broken links, orphans, stubs):
./scripts/wiki-doctor.py
```

---

## Directory structure (condensed)

```
<root>/
├── .import/             ← in-progress batch import state (gitignored)
├── _resources/          ← vault-level attachments (images, screenshots)
├── config/              ← settings.md, personal_info.md, web clipper template
├── docs/                ← design docs and migration notes
├── templates/           ← Obsidian note templates
├── scripts/             ← helper scripts (see Scripts section)
│   ├── lib/             ← wiki-doctor package (checks, fixers, tui)
│   ├── system/          ← scripts invoked by skills (not run directly)
│   └── tests/           ← unit tests
├── INBOX/               ← folder for draft notes (review/finish before ingestions)
├── raw/
│   ├── clips/           ← web articles and saved pages (web clipper)
│   ├── confluence/      ← pages fetched from Atlassian Confluence (fetch cache)
│   ├── diary/           ← dated personal/work diary notes
│   ├── emails/          ← email threads (.eml/.html → .md, originals in _resources/)
│   ├── notes/           ← notes, 1:1s, and people-specific files
│   ├── scans/           ← handwritten pages, whiteboards (→ .md, originals in _resources/)
│   ├── slack/           ← Slack channel and DM threads (fetched by "fetch slack")
│   └── transcripts/     ← meeting transcripts (.vtt → .md, originals in _resources/)
├── wiki/
│   ├── index.md         ← top-level navigation to section indexes
│   ├── log.jsonl        ← append-only ingest log (JSON Lines)
│   ├── concepts/        ← mental models and domain concepts
│   │   └── _index.md    ← alphabetical index of concept pages
│   ├── competition/     ← competitor profiles
│   ├── conversations/   ← interesting and valuable conversations (query results)
│   ├── decisions/       ← decision records
│   ├── people/          ← people and team pages
│   ├── problems/        ← living problem tracking pages
│   ├── projects/        ← living project tracking pages
│   └── systems/         ← living system reference pages
├── AGENTS.md            ← shared agent instructions
├── CLAUDE.md            ← schema and workflow instructions for Claude Code
├── index.md            ← vault entry point
└── README.md            ← this file
```

When a non-Markdown file is converted, the original is moved into a `_resources/`
subdirectory of its directory and a companion `.md` note is written alongside it
(in the directory the original came from). For example, `raw/transcripts/foo.vtt`
becomes `raw/transcripts/_resources/foo.vtt` plus `raw/transcripts/foo.md`.
The directories `raw` and `wiki` are not stored in Git. Create them manually before first use.

## Wiki topic types

| Type              | Purpose                                                    |
| ----------------- | ---------------------------------------------------------- |
| **competition**   | Competing companies, products, and approaches              |
| **concepts**      | Technologies, standards, mental models, domain vocabulary  |
| **conversations** | Valuable results of earlier queries/conversations          |
| **decisions**     | Why decisions were taken, on what basis, by whom, and when |
| **people**        | Colleagues, contacts, external stakeholders, teams         |
| **problems**      | Active and past problems                                   |
| **projects**      | Active and past initiatives                                |
| **systems**       | System, products, platforms, and services                  |

## Key rules

- `raw/` is immutable — LLM never writes there (except `raw/confluence/` as a fetch cache).
- `wiki/` is LLM-owned — LLM writes, the user reads.
- The relevant `wiki/<type>/_index.md` files are rebuilt and `wiki/log.jsonl` is updated on every finalized ingest.
- Hand-curated content in Wiki pages is never deleted or overwritten.

## Scripts

### Regular use

| Script | Purpose |
| ------ | ------- |
| `wiki-ingest.sh` | Main ingestion pipeline: converts raw files (VTT, EML), creates batches if needed, and runs ingestion sessions in a loop until all notes are processed. The normal way to ingest new notes. |
| `wiki-doctor.py` | Health-check for the wiki: broken internal/external links, orphan pages, and unfilled stub pages. Runs as an interactive TUI by default, or in `--batch-mode` for text/JSON output. Run periodically to keep the wiki healthy. |
| `wiki-freshness.sh` | One-command freshness check: provenance lint, freshness inventory, drift queue, and provenance coverage backlog. Run after ingest/finalize, or ask "freshness check". |

### Occasional use

| Script | Purpose |
| ------ | ------- |
| `qmd-full-reindex.sh` | Reset and fully re-index the QMD database. |

### For use by skills (not normally run directly)

| Script | Purpose |
| ------ | ------- |
| `system/wiki-create-import-batches.sh` | Partitions un-ingested notes into batch files for parallel import sessions. Called automatically by `wiki-ingest.sh` and the `wiki-ingest` skill. |
| `system/wiki-create-index-pages.py` | Rebuilds `_index.md` files for each wiki section. Called by the `wiki-finalize-ingest` skill after a completed ingest run. |
| `system/wiki-freshness-query.py` | Builds a query-time packet from retrieved pages, ranking canonical blocks by provenance freshness and explaining demoted legacy evidence. |
| `system/wiki-provenance-stamp-status.py` | Applies a minimal `Freshness Status` provenance block to reviewed legacy pages from a JSON manifest. |
| `system/convert-eml-to-md.py` | Converts `.eml` email files to Markdown with YAML frontmatter. Called by `wiki-ingest.sh` before ingestion. |
| `system/convert-html-to-md.py` | Converts `.html` email exports (e.g. from Microsoft Power Automate) to Markdown with YAML frontmatter. Called by `wiki-ingest.sh` before ingestion. |
| `system/convert-vtt-to-md.py` | Converts `.vtt` transcript files to readable Markdown with YAML frontmatter. Called by `wiki-ingest.sh` before ingestion. |
| `system/wiki-assign-dates.py` | Infers and assigns dates to wiki pages that are missing them (uses the configured `ai_backend` for smart inference). |
| `system/wiki-supersession-lint.py` | Checks decision/project pages for supersession consistency (e.g. superseded pages correctly linked). |
| `system/migrate-converted-to-resources.py` | One-time migration from the legacy `converted/` layout to the current `_resources/` layout. Dry-run by default; pass `--apply` to modify files. |
| `system/copy-claude-skills-to-other-agents.sh` | Copies `.claude/skills/` to other AI agent config directories and generates Codex TOML agent definitions so all agents share the same skill set. |
| `system/qmd-reset-collections.sh` | Removes all QMD collections and wipes the search index database. Use before a full re-sync. |
| `system/qmd-sync-collections.sh` | Registers the vault root as the QMD collection `tomtom` (idempotent) and re-indexes it. Called by the `wiki-finalize-ingest` skill. |

## Recognition

- Andrej Karpathy - for his original idea for the [LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).
- Rob van der Most - for brainstorming and experimenting with this idea.
- Christian Rexwinkel - for creating the Slack and Outlook extensions.
# knowledge-base-wiki
