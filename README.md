# Provenance-Aware Knowledge Base Wiki

_Copyright (C) 2026, Rijn Buve_

This repository started as an implementation of [Andrej Karpathy's idea](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) for an LLM-maintained knowledge base: keep source notes in a folder, let an LLM maintain a Wiki on top of them, and use the Wiki as the practical interface for remembering and reasoning. This implementation keeps that core idea, but goes considerably further. It is designed for long-lived work knowledge, where old notes do not merely accumulate; they need to be curated, checked, superseded, and sometimes deliberately ranked lower when answering current questions.

The knowledge base is structured as an [Obsidian](https://obsidian.md) vault, assisted by the semantic database [QMD](https://github.com/tobi/qmd). Raw evidence lives in `raw/`; canonical pages live in `wiki/`. Ingestion adds and updates canonical pages, while curation improves selected pages over time using source evidence, page-level provenance, and freshness metadata. Provenance-aware query tooling can explain when a page is current, stale, unverified, or superseded, so outdated information is not silently treated as equally reliable.

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

# 2. Create the raw/ subdirectories (raw/ is not stored in git; wiki/ is created empty by the clone)
cd ~/my-knowledge-base
mkdir -p raw/{notes,clips,confluence,diary,emails,transcripts,scans,slack}

# 3. Install QMD (the semantic search engine; it runs on the Bun runtime)
npm install -g bun
npm install -g @tobilu/qmd

# 4. Register the vault as a QMD collection and build the index
./scripts/qmd-full-reindex.sh

# 5. Register QMD as an MCP server for Claude Code (user scope, so it works in every project)
claude mcp add --scope user qmd -- qmd mcp
#    Or just ask Claude: "read this README.md and install QMD as an MCP server"

# 6. (Optional) Install the QMD skill globally, for use in other projects.
#    This repo already ships the skill in .claude/skills/qmd, so this step is not needed here.
qmd skill install --global --yes

# 7. Open this directory as an Obsidian vault: File → Open Folder as Vault
```

If you use the Obsidian Web Clipper, import `config/obsidian_webclipper_template.json` as a clipper template so clips land in `raw/clips/` with the expected frontmatter.

After setup, put your notes in `raw/` and tell Claude: **"ingest new notes"**.
Alternatively, run:

```bash
./scripts/wiki-ingest.sh
```

After ingesting notes, run the doctor regularly to keep your knowledge base clean by telling Claude **"health check"** (or "lint"):

```bash
./scripts/wiki-doctor.py
```

Freshness checks are the third regular maintenance action, alongside ingest and doctor. This check validates the provenance frontmatter of generated notes and builds the curation queues that improve search relevance later. You can ask for a **"freshness check"**, or run:

```bash
./scripts/wiki-freshness.sh
```

You can keep notes that you do not want to be ingested yet (like drafts) in `INBOX`. The inbox is not part of the ingestion process, and (apart from `INBOX/RELEASE-NOTES.md`) it is not stored in git.

For sensitive Markdown notes that should remain in `raw/` but never be ingested, add frontmatter:

```yaml
---
ingest: false
---
```

The batch importer skips that note and any local `raw/` files explicitly linked from it with wikilinks, embeds, or Markdown links/images. It prints the skipped note basename with the number of linked files skipped, and it does not write a skip entry to `wiki/log.jsonl`. Remove the field later to make the note eligible for ingestion again.

## Some background on provenance

Provenance data is used to better establish the relevance of a page with respect to a query. It is more powerful than just looking at the "note creation date". It records, per canonical page, which raw notes the page was built from, who (or which agent) generated it and when, who verified it since, and optionally when it should be considered stale. Using this data, the `wiki-query` skill is much better able to establish the relevance of pages for a specific query.

The provenance data is stored directly in the YAML frontmatter of generated canonical notes under `wiki/`, not in a hidden sidecar database. That keeps each page readable in Obsidian, reviewable in Git, and usable by LLMs even when only the Markdown file is available. The format is called OKF v0.2.

A canonical page with full provenance has:

- a `sources:` list in the frontmatter, one entry per raw note the page draws on, each with an `id` (`s1`, `s2`, ...) and a `resource` path;
- a `generated:` mapping (`by`, `at`) recording who created the content and when;
- an append-only `verified:` list of `{by, at}` entries recording later checks;
- an optional `stale_after:` date, after which the page is treated as stale;
- per-claim attribution in the body via Markdown footnotes `[^s1]`, keyed to `sources[].id`, with the footnote definitions at the end of the page.

Example:

```markdown
---
type: system
description: "Ownership and status of the map enrichment flow."
sources:
  - id: s1
    resource: "raw/notes/2026-06-02 Meeting map enrichment.md"
generated:
  by: "agent:wiki-ingest"
  at: 2026-06-02
verified:
  - by: "human:rijn.buve"
    at: 2026-06-20
---

Current ownership sits with the map enrichment flow.[^s1] ^claim-owner-01

[^s1]: [[raw/notes/2026-06-02 Meeting map enrichment.md]]
```

Trust tiers come from the `by:` prefix of `verified:` entries: `human:*` is the human-reviewed tier (strongest); `agent:*` is the machine tier; a page with only `generated:` is unverified (weakest). Freshness is derived from `generated.at` and the latest `verified.at`. Query tooling derives a page status (`current`, `stale`, or `unknown` when no provenance is present) and a confidence (`high` for human-verified, `medium` otherwise) and uses these to rank current, verified evidence higher and to explain when older or unverified evidence is being demoted rather than silently ignored.

Pages that are explicitly replaced carry `superseded_by:` (and the replacement carries `supersedes:`) in their frontmatter; a superseded page is never used as the main current answer unless you ask for history.

Stable Obsidian block IDs such as `^claim-owner-01` remain allowed as plain anchors for citation, but they carry no metadata. The earlier `kb-prov-v1` provenance callout format is abolished; the linter flags any page that still contains it. Validate provenance with:

```bash
python3 scripts/system/wiki-provenance-lint.py --root .
```

## Migrating an Existing Knowledge Base

If you already have a large `raw/` corpus and existing generated or curated `wiki/` pages, migrate it instead of bulk re-ingesting it.

Start with a dry-run:

```bash
scripts/wiki-migrate-existing.sh --root .
```

Then apply the migration:

```bash
scripts/wiki-migrate-existing.sh --root . --apply
```

The migration script defaults to the safe behavior: existing raw files are baselined in `wiki/log.jsonl`, so a later `scripts/wiki-ingest.sh` run will not re-ingest the whole historical corpus. It still respects `ingest: false` protected notes and their explicitly linked local raw files, so private opt-out material is not logged.

Use the full re-ingestion option only when you intentionally want old raw files to be eligible for fresh ingestion - this may be expensive and take a long time:

```bash
scripts/wiki-migrate-existing.sh --root . --apply --allow-reingest-existing
```

The migration flow checks structural health, optionally migrates legacy `converted/` layouts, assigns freshness dates, rebuilds index pages, syncs QMD (text index only; add `--qmd-embed` for vector embeddings), runs the freshness/provenance queues, and writes `.wiki-scratch/migration-report.md`. Use `--help` for the remaining options (`--skip-legacy-layout`, `--skip-qmd`, `--limit`, `--no-report`, `--strict`).

## Update the framework regularly

The framework is updated regularly, so it's wise to `git pull` every now and then:

```bash
cd ~/my-knowledge-base && git pull
```

## Prerequisites

**Required:**
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (CLI) — or Codex, Vibe, Junie (experimental)
- [Node.js / npm](https://nodejs.org/) — for installing bun and qmd
- [QMD](https://github.com/tobi/qmd) — local semantic search engine (`npm install -g @tobilu/qmd`)
- [Obsidian](https://obsidian.md) — vault UI (free, Mac/Windows/Linux)
- `git`
- Python 3 — for the scripts under `scripts/`

**Optional:**
- [pdftotext](https://poppler.freedesktop.org/) — faster/cheaper PDF extraction (`brew install poppler`); LLM vision is the fallback
- [Obsidian Web Clipper](https://obsidian.md/clipper) — one-click web article saving to `raw/clips/` (template in `config/obsidian_webclipper_template.json`)
- [Claudian](https://github.com/YishenTu/claudian) — run Claude from within Obsidian (ask Claude to install it safely)
- [Amphetamine](https://apps.apple.com/app/amphetamine/id937984704) (Mac App Store) — prevents Mac sleep during long overnight ingests

## MCP Server Setup

Register QMD as an MCP server for Claude Code (or ask Claude to do it):

```bash
claude mcp add --scope user qmd -- qmd mcp
```

This writes the server into `~/.claude.json`. If you prefer a project-scoped server, create a `.mcp.json` in the vault root instead:

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

Claude Desktop uses a different file (`~/Library/Application Support/Claude/claude_desktop_config.json`) with the same JSON shape.

The Slack integration is managed via your claude.ai organization. Authorize it yourself at **claude.ai → Settings → Connectors**. Once authorized, the Slack tools are available automatically in all Claude sessions — no local configuration needed.

The email integration uses Microsoft Power Automate to save emails to a OneDrive folder, which syncs to your local disk. Ask "fetch mail" to copy files from that folder into `raw/emails/` and queue them for ingestion.

---

## Your note-keeping routine in a nutshell

- **Create and collect notes:**
	- User produces raw notes and stores them in the `raw/notes` directory.
	- User uses the Obsidian Web Clipper to store notes in `raw/clips`.
	- User stores `.vtt` meeting transcripts in `raw/transcripts`.
	- User asks "fetch mail" to copy emails from the configured inbox to `raw/emails/`, or drags `.eml`/`.html` files there manually.
	- User stores handwritten notes or scanned pages (PDF, JPG) in `raw/scans`.
	- User fetches Slack channels and DMs by asking "fetch slack" — messages are written to `raw/slack/<channel>/` and `raw/slack/DM-<Name>/`.

- **Ingest notes:**
	- User asks to "ingest new notes", "ingest Confluence page `<URL>`" or runs `wiki-ingest.sh`.
	- Non-Markdown inputs are converted first: `.vtt` transcripts and `.eml`/`.html` emails deterministically by the ingest script, `.pdf`/`.jpg` scans by the LLM. The original file is moved into a `_resources/` subdirectory of its directory, and a companion `.md` note is written next to it (in the same directory as the original was).
	- Markdown notes with `ingest: false` frontmatter, plus local `raw/` files explicitly linked from them, are excluded from batch ingestion and are not logged.
	- LLM partitions files into batches and processes them (large ingests use N parallel LLM sessions; a single batch is handled in one session).
	- After all batches are done, the coordinator session finalizes (or you say "finalize ingest"): merge session logs, assign freshness dates, rebuild `index.md` files, and run post-processing (QMD re-index, health check, freshness check).

- **Query wiki:**
	- User asks a high-level question.
	- LLM queries the semantic database (QMD, via MCP or CLI) for relevant page links (fast/token-efficient).
	- LLM builds a freshness packet over the retrieved pages, processes them, and produces an answer to the user.
	- LLM proposes to store valuable conversations in `wiki/conversations/` to extend the knowledge base.

- **Maintenance:**
	- Every now and then ask for a **"health check"** and a **"freshness check"** to fix broken links and validate provenance, which increases search relevance over time.

The combination of using a semantic database to fetch relevant pages before analyzing documents and reasoning about them makes this implementation of a knowledge base significantly faster and more token efficient than one that uses Markdown files only.

## Commands and skills

The skills live in `.claude/skills/` (one `SKILL.md` per skill) and are mirrored to `.agents/`, `.codex/` and `.junie/` for other agents (see [Development](#development)). These skill commands and natural-language triggers are available.

**Commonly used:**

| Command / phrase                     | Skill                | Description                                                                                   |
| ------------------------------------ | -------------------- | --------------------------------------------------------------------------------------------- |
| ask any question                     | `wiki-query`         | Query the knowledge base (default behavior)                                                   |
| "ingest new notes"                   | `wiki-ingest`        | Start a new ingest of raw notes or a Confluence page (Session 1 — coordinator flow)           |
| "fetch slack"                        | `wiki-fetch-slack`   | Fetch Slack channels and DMs into `raw/slack/`; ingest afterwards                             |
| "fetch mail"                         | `wiki-fetch-mail`    | Copy emails from the configured inbox to `raw/emails/`; ingest afterwards                     |
| "health check" or "lint"             | `wiki-doctor`        | Check for broken links, orphaned pages, stubs, loose files, and frontmatter problems          |
| "freshness check"                    | `wiki-freshness`     | Run the one-command provenance lint / drift queue / coverage backlog check                    |
| "curate page" or "refresh this page" | `wiki-curate-page`   | Clean up one canonical page using raw evidence and freshness/drift signals                    |
| "add missing [topic]"                | `wiki-add-missing`   | Create a new Wiki page for a missing concept, person, system, etc.                            |
| "write an article about [topic]"     | `write-article`      | Draft a footnoted, publication-quality article from vault knowledge plus web research         |

**Less common / maintenance:**

| Command / phrase                                    | Skill                        | Description                                                                                 |
| --------------------------------------------------- | ---------------------------- | ------------------------------------------------------------------------------------------- |
| "ingest next batch"                                 | `wiki-ingest-next-batch`     | Continue ingesting the next batch (Sessions 2–N flow)                                       |
| "finalize ingest"                                   | `wiki-finalize-ingest`       | Finalize the ingest: merge logs, assign dates, rebuild indexes, run post-processing         |
| "clear ingest batches"                              | `wiki-clear-ingest-batches`  | Remove incomplete batch files to restart a failed ingest                                    |
| "migrate existing knowledge base"                   | `wiki-migrate-existing`      | Prepare an existing `raw/` + `wiki/` corpus without bulk re-ingesting historical raw notes  |
| "ground this conversation" or "wiki-ground [topic]" | `wiki-ground`                | Treat the KB as source of truth for this conversation; optionally front-load a topic        |

**Background skills** (loaded by other skills, not invoked directly):

| Skill                  | Description                                                                                    |
| ---------------------- | ---------------------------------------------------------------------------------------------- |
| `wiki-ingest-per-note` | Per-note processing rules: file conversion, topic assignment, wikilinks, provenance frontmatter |
| `wiki-templates`       | Page structure and frontmatter for each topic type; used whenever a Wiki page is created         |
| `qmd`                  | How to search the QMD semantic database (upstream skill, with a Codex sandbox note added)       |

`.claude/agents/` holds two sub-agent definitions (`wiki-ingest-next-batch`, `wiki-finalize-ingest`) that the `wiki-ingest` skill dispatches during large imports.

The `ingest next batch` and `finalize ingest` commands are only needed for importing large amounts of notes. The LLM will notify you when you `ingest new notes` and it sees that batched importing is required.

### Pro-tip 1: use `wiki-ingest.sh` to ingest multiple files

You can use the script `scripts/wiki-ingest.sh` to start ingesting new notes. The advantage of this script is that it runs unattended: it converts raw files, partitions new notes into batches (without calling the LLM), runs one `ingest next batch` session per batch, runs `finalize ingest`, and finishes with the doctor, a QMD re-sync, and a freshness check. When the backend is Claude, it pauses for 30 minutes whenever your 5-hour usage window is at or above the threshold (default 85%) and then resumes.

By default, the script reads `config/settings.md` and uses its `ai_backend`
frontmatter value. You can override it for a single run like this:
```
scripts/wiki-ingest.sh [--agent claude|vibe|codex|junie]
```

Other options include `--threshold`, `--max-batches`, `--max-files-per-batch`, `--wait-between-batches`, `--max-errors`, and `--dry-run`. Use `wiki-ingest.sh --help` for details.

### Pro-tip 2: use `wiki-doctor.py` to health-check your knowledge base

The ingest script runs the doctor automatically at the end of each run. The doctor itself never calls an LLM; it is a fast, deterministic check for:

- broken internal links and embeds (optionally external HTTP links with `--external`);
- orphaned pages (no incoming links) and stub pages (identified by the LLM but never filled in);
- frontmatter problems, such as a missing `description:` or leftover legacy provenance markup;
- files whose names differ only in accents (duplicates created by syncing between file systems);
- loose non-Markdown files and misplaced or orphaned attachments;
- footnote references without a definition (and vice versa);
- leftover legacy `converted/` directories.

You can run it manually by simply executing:
```
scripts/wiki-doctor.py
```

This opens an interactive TUI to deal with:
- Broken links: these can be removed, flagged, replaced with plain text, or retargeted.
- Orphaned pages: these can be deleted, or kept (marked with `orphan: false`).
- Stub pages: these can be deleted, or kept and acknowledged in their frontmatter.
- Orphaned attachments: these can be previewed and deleted.

Using this interactive mode, you should be able to keep your knowledge base 100% free of false positive alerts so it's easy to see if the knowledge base is still sound or not. Use `--batch-mode` to suppress the TUI and get text/JSON output only (`--format text|json`). `--fix-simple-errors` repairs broken links that have a unique normalized match, prunes `wiki/log.jsonl`, and relocates loose files into `_resources/` using the Obsidian CLI (Obsidian must be running). `--fix-orphans` turns plain-text mentions of orphaned pages into wikilinks. See `--help` for the full list.

### Pro-tip 3: run `qmd-full-reindex.sh` to re-index the semantic database

After running ingestion of notes (e.g. by `scripts/wiki-ingest.sh`), you are advised to run:
```
scripts/qmd-full-reindex.sh
```
This registers the vault root as a single QMD collection (named `tomtom`; the name is hard-coded in `scripts/system/qmd-sync-collections.sh`), removes any stale per-subdirectory collections, runs `qmd update` (text index), and then `qmd embed` (vector embeddings). Pass `--skip-embed` to skip the slow embedding step, or `--reset` to drop all collections and the index database first. The LLM skill `wiki-query` makes use of the semantic database, so make sure it's up-to-date.

Instead of running a full re-index, you can also execute `qmd embed`. This is useful if you only ingested a couple of new notes, for example.

### Pro-tip 4: use the freshness tools to keep provenance healthy

Canonical pages carry OKF v0.2 provenance frontmatter (see [Some background on provenance](#some-background-on-provenance)). The easy command is:

```
scripts/wiki-freshness.sh --root .
```

It runs the provenance lint, builds a freshness inventory, and writes two queues under `.wiki-scratch/` (generated local working state, ignored by Git):

- `freshness-curation-candidates.md`, produced by `wiki-drift-detect.py`: pages where related raw evidence, newer raw notes, or freshness statuses suggest a real query-time risk.
- `provenance-coverage-backlog.md`, produced by `wiki-provenance-coverage.py`: every canonical Wiki page whose provenance is missing (`no-provenance`) or invalid (`invalid-provenance`), even when no freshness risk has been detected yet.

Use the drift queue first for answer-quality improvements. Use the coverage backlog for gradual migration planning. The ingest script runs this automatically after finalization, and `wiki-doctor.py` reminds you about it in its recommendations. You can run it manually any time, especially after fixing doctor findings or before freshness-sensitive query work.

Classifier-reviewed legacy pages can receive a minimal provenance stamp instead of a full rewrite. This writes `sources:`, `generated:`, and (optionally) `verified:` frontmatter from a reviewed JSON manifest, which moves the page from the backlog to `covered`:

```
python3 scripts/system/wiki-provenance-stamp-status.py \
  --root . \
  .wiki-scratch/freshness-auto-ok.json
```

Use this only with a reviewed manifest. It is not a substitute for detailed per-claim curation.

#### Use `wiki-curate-page` to clean up canonical pages

Use `wiki-curate-page` for one-page cleanup when drift detection shows that newer raw notes may affect a canonical page. Just ask **"curate this page"**. Under the hood, the skill prepares a read-only packet for the target page:

```
python3 scripts/system/wiki-curate-page.py --page "wiki/concepts/Some Concept.md" --format json
```

The `wiki-query` skill uses a related helper to rank retrieved pages by provenance freshness before answering. With `--qmd` it runs QMD candidate discovery itself:

```
python3 scripts/system/wiki-freshness-query.py \
  --query "What is current?" \
  --qmd \
  --format text
```

With `--qmd`, raw-note hits are preserved too: raw hits that link to or title-match a canonical page are mapped into `raw_mappings` and can pull that canonical page into the ranked packet; raw hits without a canonical match remain visible as `raw_evidence`. If candidate pages were already retrieved by another search path, pass them explicitly with repeated `--page` arguments instead of `--qmd`.

None of these tools bulk-rewrite `wiki/`.

### Pro-tip 5: storing draft notes in `INBOX` (not for ingestion yet)

You can store notes in `INBOX` while you're working on them and you don't want them ingested yet. Move them manually to `raw/notes` once you think they are ready for ingestion. Then run `scripts/wiki-ingest.sh`.

### Pro-tip 6: use the Obsidian CLI

You can use the Obsidian CLI to interact with Obsidian on the command-line. Or, even better, have Claude interact with Obsidian using the CLI: the skills use it to move, rename, and delete notes so that Obsidian updates all internal links. Take a look at [Obsidian skills for Claude](https://github.com/kepano/obsidian-skills) to install skills for Claude on how to use Obsidian.

## Configuration

### Personalizing your setup

Provide personal info on who you are, what you do, and what your focus is, in `config/personal_info.md` (this file is gitignored):

```markdown
# Personal Info
My name is ...
I am ...

# My Main Focus
- Strategic decision making on technology choices.
- ...
```

If the file is missing, or it contains no info topics, default topics will be used. The same file holds the `# Slack` and `# Email` sections described below.

### Configuring the local AI backend

Set the local LLM CLI used by `scripts/wiki-ingest.sh` in `config/settings.md`:

```yaml
---
ai_backend: claude
---
```

Supported values are `claude` (`claude -p ...`), `vibe` (`vibe -p ...`),
`codex` (`codex exec ...`), and `junie` (experimental; the script asks for
confirmation and uses smaller batches). Usage throttling only works for
`claude`. If the selected CLI is missing or fails, the script keeps
deterministic state intact and stops before consuming LLM-backed batches.

### Configuring Slack sources

Add a `# Slack` section to `config/personal_info.md` to configure which channels and DMs to fetch:

| Channel / DM            | Days | Mode                      |
|-------------------------|------|---------------------------|
| #architecture-decisions | 14   | signal                    |
| #team-platform          |      | all                       |
| @Alice van Dijk         | 7    | software design decisions |

- `#channel-name` — a public or private Slack channel
- `@Person Name` — a direct message thread with that person
- **Days** — how many calendar days back to fetch conversation updates (default: 7; say "fetch slack last N days" to override once)
- **Mode** — `signal` filters out noise (absences, bot messages, bare acks); `all` includes everything; any other text is treated as a topic filter (only threads directly about that topic are included)

### Capturing emails automatically with Microsoft Power Automate

You can use [Microsoft Power Automate](https://make.powerautomate.com/) to automatically save incoming emails as `.html` files so they are picked up by the ingestion pipeline.

Create a flow with these steps:

1. **Trigger:** *When a new email arrives (V3)*
2. **Action:** *Get email (V2)* — to get the full email details and body
3. **Action:** *Create file* (OneDrive for Business) — save to a dedicated OneDrive inbox folder (e.g. `KnowledgeSystem/inbox`). This folder syncs to your local disk; configure its local path in `config/personal_info.md` and ask "fetch mail" to copy files to `raw/emails/`.
   - **File name:** `@{outputs('Get_email_(V2)')?['body/receivedDateTime']}.html`
   - **File content:**
     ```
     FROM:@{outputs('Get_email_(V2)')?['body/from']},TO:@{outputs('Get_email_(V2)')?['body/toRecipients']},CC:@{outputs('Get_email_(V2)')?['body/ccRecipients']},BCC:@{outputs('Get_email_(V2)')?['body/bccRecipients']},SUBJECT:@{outputs('Get_email_(V2)')?['body/subject']},BODY:@{outputs('Get_email_(V2)')?['body/body']}
     ```

The `Get_email_(V2)` in the expressions must match the name of the action in your flow. The resulting filename looks like `2026-05-13T08_32_05+00_00.html` — the date is extracted from it automatically. The `FROM`, `TO`, `CC`, `BCC`, and `SUBJECT` fields become YAML frontmatter; `BODY` is converted from HTML to Markdown. Once the OneDrive folder syncs to your local disk, ask "fetch mail" to pull the files into `raw/emails/` and drain the inbox.

### Configuring email fetch

Add an `# Email` section to `config/personal_info.md` to configure where "fetch mail" copies files from:

```markdown
# Email
| Setting | Value                        |
|---------|------------------------------|
| Inbox   | /path/to/your/onedrive/inbox |
```

Set `Inbox` to the local path of the folder that contains your exported email files (`.html` and `.eml`) from, for example, the Power Automate flow. Files are copied to `raw/emails/` (duplicates already present are skipped) and deleted from the inbox on each fetch.

### Running Claude within Obsidian

You can run Claude from within Obsidian using the Claudian plugin. Install it by asking Claude:
```
Claude, I want you to install the following Obsidian plugin from Github. First, I want you to review
the plugin and make sure it is safe to install. And if it is safe, install it.
This is the repo: https://github.com/YishenTu/claudian
```

## Re-creating the Wiki from Scratch

To re-create the entire Wiki, remove the `wiki/` directory, `/clear` the LLM conversation and ask it to `ingest new notes`. Note that for large amounts of notes this may be expensive and take a long time.

**Note:** The `wiki/log.jsonl` file tracks which notes have already been ingested, including a content hash so that renamed raw notes are recognized as already ingested. If you share the `wiki/` directory across machines, any client can run incremental ingestions without re-processing everything.

## Checking Your Database

The database is automatically checked for errors at the end of each `wiki-ingest.sh` run. To check manually:
```bash
# Basic check (fast, no TUI):
./scripts/wiki-doctor.py --batch-mode --format text

# Interactive TUI (deal with broken links, orphans, stubs, attachments):
./scripts/wiki-doctor.py
```

---

## Directory structure (condensed)

```
<root>/
├── .claude/
│   ├── skills/          ← the wiki skills (source of truth; one SKILL.md per skill)
│   └── agents/          ← sub-agent definitions used by wiki-ingest for large imports
├── .agents/, .codex/, .junie/  ← mirrors of the skills for other agents (generated; .agents and .junie gitignored)
├── .import/             ← in-progress batch import state (gitignored)
├── .wiki-scratch/       ← freshness queues and migration report (gitignored)
├── _resources/          ← Obsidian's default paste folder for attachments (gitignored)
├── config/              ← settings.md, personal_info.md (gitignored), web clipper template
├── templates/           ← Obsidian note templates (daily note, broken-link marker)
├── scripts/             ← helper scripts (see Scripts section)
│   ├── lib/             ← shared Python package: doctor checks/fixers/TUI, provenance, freshness, drift, curation
│   ├── system/          ← scripts invoked by skills and wrapper scripts (not normally run directly)
│   └── tests/           ← unit tests
├── INBOX/               ← draft notes (review/finish before ingestion); gitignored except RELEASE-NOTES.md
│   └── RELEASE-NOTES.md ← changelog of script and skill changes
├── raw/                 ← not stored in git
│   ├── clips/           ← web articles and saved pages (web clipper)
│   ├── confluence/      ← pages fetched from Atlassian Confluence (fetch cache)
│   ├── diary/           ← dated personal/work diary notes
│   ├── emails/          ← email threads (.eml/.html → .md, originals in _resources/)
│   ├── notes/           ← notes, 1:1s, and people-specific files
│   ├── scans/           ← handwritten pages, whiteboards (→ .md, originals in _resources/)
│   ├── slack/           ← Slack channel and DM threads (fetched by "fetch slack")
│   └── transcripts/     ← meeting transcripts (.vtt → .md, originals in _resources/)
├── wiki/                ← not stored in git (only an empty placeholder)
│   ├── index.md         ← top-level navigation to section indexes
│   ├── log.jsonl        ← append-only ingest log (JSON Lines)
│   ├── concepts/        ← mental models and domain concepts
│   │   └── index.md     ← alphabetical index of concept pages
│   ├── competition/     ← competitor profiles
│   ├── conversations/   ← interesting and valuable conversations (query results)
│   ├── decisions/       ← decision records
│   ├── people/          ← people and team pages
│   ├── problems/        ← living problem tracking pages
│   ├── projects/        ← living project tracking pages
│   └── systems/         ← living system reference pages
├── AGENTS.md            ← workflow and rules for all agents (skills, topic types, naming, linking)
├── CLAUDE.md            ← one-liner pointing Claude Code at AGENTS.md
├── index.md             ← vault entry point
├── LICENSE
└── README.md            ← this file
```

When a non-Markdown file is converted, the original is moved into a `_resources/`
subdirectory of its directory and a companion `.md` note is written alongside it
(in the directory the original came from). For example, `raw/transcripts/foo.vtt`
becomes `raw/transcripts/_resources/foo.vtt` plus `raw/transcripts/foo.md`.
The `raw/` directory is not stored in Git; create it (and its subdirectories) before first use.

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
| **systems**       | Our products, platforms, and services                      |

## Key rules

- `raw/` is human territory — the LLM never edits the content of your notes. The only writes are the deterministic conversions described above (moving originals into `_resources/`, writing companion `.md` notes, adding a `date` prefix/frontmatter) and the `raw/confluence/` fetch cache.
- `wiki/` is LLM-owned — LLM writes, the user reads. Hand-curated content in Wiki pages is never deleted or overwritten.
- Pages live exactly one level deep: `wiki/<topic>/<page>.md`, each with `type:` and `description:` frontmatter.
- The relevant `wiki/<type>/index.md` files are rebuilt and `wiki/log.jsonl` is updated on every finalized ingest.
- File names are plain readable text: no slugs (spaces, not hyphens), no accents or diacritics, no characters with file-system meaning (`:`, `/`, `\`, `*`, `?`, `"`, `<`, `>`, `|`).
- Wikilinks target the exact filename, with spaces: `[[Real-Time Map]]`, never `[[Real-Time-Map]]`.
- Moving, renaming, or deleting notes goes through the Obsidian CLI so that Obsidian updates all internal links.
- Every change to `scripts/` or the skills gets an entry in `INBOX/RELEASE-NOTES.md`.

## Scripts

### Regular use

| Script | Purpose |
| ------ | ------- |
| `wiki-ingest.sh` | Main ingestion pipeline: converts raw files (VTT, EML, HTML), partitions new notes into batches, runs one LLM session per batch, finalizes, and then runs the doctor, QMD sync, and freshness check. The normal way to ingest new notes. |
| `wiki-migrate-existing.sh` | Safe migration wrapper for existing raw/ + wiki/ corpora. Dry-run by default; with `--apply`, baselines existing raw files so they are not re-ingested wholesale. |
| `wiki-doctor.py` | Deterministic health check for the vault: broken links, orphans, stubs, frontmatter, accent duplicates, loose files, attachments, footnotes. Runs as an interactive TUI by default, or in `--batch-mode` for text/JSON output. |
| `wiki-freshness.sh` | One-command freshness check: provenance lint, freshness inventory, drift queue, and provenance coverage backlog. Run after ingest/finalize, or ask "freshness check". |

### Occasional use

| Script | Purpose |
| ------ | ------- |
| `qmd-full-reindex.sh` | Register the vault as a QMD collection, run the text re-index and vector embeddings. `--skip-embed` for text only; `--reset` to wipe and rebuild from scratch. |

### For use by skills and wrapper scripts (not normally run directly)

| Script | Purpose |
| ------ | ------- |
| `system/wiki-create-import-batches.sh` | Partitions un-ingested notes into batch files for parallel import sessions, honouring `ingest: false`. Called by `wiki-ingest.sh` and the `wiki-ingest` skill. |
| `system/wiki-merge-batch-logs.py` | Merges `.import/batch-log-*.jsonl` into `wiki/log.jsonl`, validating every line and quarantining malformed ones. Called by `wiki-finalize-ingest`. |
| `system/wiki-stamp-log-hashes.py` | Stamps a content hash and mtime onto every `wiki/log.jsonl` entry so renamed raw notes are recognized as already ingested. Called by `wiki-finalize-ingest`. |
| `system/wiki-relink-log-renames.py` | Repoints `wiki/log.jsonl` entries whose source note was renamed. Called by `wiki-finalize-ingest` and `wiki-doctor`. |
| `system/wiki-clear-ingest-batches.py` | Lists (`--list`) or deletes (`--apply`) the batch files under `.import/`. Called by the `wiki-clear-ingest-batches` skill. |
| `system/wiki-create-index-pages.py` | Rebuilds `index.md` files for each wiki section from the pages' `description:` frontmatter. Called by `wiki-finalize-ingest` and `wiki-migrate-existing.sh`. |
| `system/wiki-backfill-descriptions.py` | Adds a derived `description:` to wiki pages that lack one. |
| `system/wiki-assign-dates.py` | Deterministically infers `date`, `date_span`, and `date_confidence` frontmatter for raw and wiki pages from filenames, folders, and existing frontmatter. `--apply` to write, `--revert` to undo. Called by `wiki-finalize-ingest` and `wiki-migrate-existing.sh`. |
| `system/wiki-baseline-raw-log.py` | Adds migration-baseline entries to `wiki/log.jsonl` for existing raw files, while respecting `ingest: false`. Called by `wiki-migrate-existing.sh`. |
| `system/wiki-provenance-lint.py` | Validates OKF v0.2 provenance frontmatter and `[^sN]` footnotes; flags legacy `kb-prov-v1` markup. Called by `wiki-freshness.sh` and `wiki-curate-page`. |
| `system/wiki-freshness-inventory.py` | Builds a read-only freshness inventory over `raw/` and `wiki/`. Called by `wiki-freshness.sh`. |
| `system/wiki-drift-detect.py` | Finds canonical pages that deserve one-page curation because newer raw evidence may affect them. Called by `wiki-freshness.sh`. |
| `system/wiki-provenance-coverage.py` | Lists every canonical page with missing or invalid provenance (`no-provenance`, `invalid-provenance`). Called by `wiki-freshness.sh`. |
| `system/wiki-freshness-query.py` | Builds a query-time packet from retrieved pages, ranking them by provenance freshness and explaining demoted legacy evidence. `--qmd` runs candidate discovery first. Called by `wiki-query`. |
| `system/wiki-curate-page.py` | Prepares a read-only curation packet for one canonical page. Called by `wiki-curate-page`. |
| `system/wiki-provenance-stamp-status.py` | Writes minimal provenance frontmatter to reviewed legacy pages from a JSON manifest. |
| `system/wiki-restore-source-footnotes.py` | One-time helper: restores `[^sN]` footnotes from a pre-OKF vault backup. |
| `system/wiki-supersession-lint.py` | Checks that `superseded_by` / `supersedes` frontmatter pairs are consistent. |
| `system/convert-eml-to-md.py` | Converts `.eml` email files to Markdown with YAML frontmatter. Called by `wiki-ingest.sh` before ingestion. |
| `system/convert-html-to-md.py` | Converts `.html` email exports (e.g. from Microsoft Power Automate) to Markdown with YAML frontmatter. Called by `wiki-ingest.sh` before ingestion. |
| `system/convert-vtt-to-md.py` | Converts `.vtt` transcript files to readable Markdown with YAML frontmatter. Called by `wiki-ingest.sh` before ingestion. |
| `system/migrate-converted-to-resources.py` | One-time migration from the legacy `converted/` layout to the current `_resources/` layout. Dry-run by default; pass `--apply` to modify files. |
| `system/copy-claude-skills-to-other-agents.sh` | Copies `.claude/skills/` and `.claude/agents/` to `.agents/`, `.codex/`, and `.junie/`, and generates Codex TOML agent definitions, so all agents share the same skill set. |
| `system/qmd-reset-collections.sh` | Removes all QMD collections and wipes the search index database. Used by `qmd-full-reindex.sh --reset`. |
| `system/qmd-sync-collections.sh` | Registers the vault root as the QMD collection `tomtom` (idempotent), removes stale per-subdirectory collections, and re-indexes. Called by `qmd-full-reindex.sh`, `wiki-ingest.sh`, and `wiki-finalize-ingest`. |

## Development

- **Tests** live in `scripts/tests/`. Run them with:
  ```bash
  python3 -m unittest discover -s scripts/tests -v
  ```
- **Skills** are edited in `.claude/skills/` only. After changing a skill or agent definition, run `bash scripts/system/copy-claude-skills-to-other-agents.sh` from the vault root to refresh the `.agents/`, `.codex/`, and `.junie/` mirrors; `test_skill_mirrors.py` fails while they are out of sync.
- **Release notes**: append a short entry to `INBOX/RELEASE-NOTES.md` after any change to `scripts/` or the skills.

## Recognition

- Andrej Karpathy - for his original idea for the [LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).
- Rob van der Most - for brainstorming and experimenting with this idea.
- Christian Rexwinkel - for creating the Slack and Outlook extensions.
