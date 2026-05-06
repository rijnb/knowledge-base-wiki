# Knowledge base Wiki

(C) 2026, Rijn Buve

This repository contains a solid implementation of [Andrej Karpathy's idea](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) for a LLM-maintained knowledge base, based on a Wiki. This implementation is meant for work-related notes, structured as an [Obsidian](https://obsidian.md) vault, assisted by the semantic database [QMD](https://github.com/tobi/qmd).

The implementation supports Anthropic Claude and Jetbrains Junie (both CLI) to ingest notes into the knowledge base.

## Purpose

The primary goal is **efficient decision intelligence**: understanding why decisions were taken, on what basis, by whom, and when. Secondary goals include mapping how technologies and systems relate, who is involved in what, and how competitors compare. And 'efficient', because the mechanism needs to be token (and environmentally) efficient.

**Division of labor:** 
- The user curates source files in `raw/`.
- LLM does all writing, cross-referencing, and bookkeeping in `wiki/`.
- Obsidian is the UI for entering/accessing notes and asking questions (e.g. through `Claudian`).

## In a nutshell

- **Create and collect notes:** 
	- User produces raw notes and stores them in the `raw/notes` directory.
	- User uses the Obsidian Web Clipper to store notes in `raw/clips`.
	- User stores `.vtt` meeting transcripts in `raw/transcripts`.
	- User drags `.eml` emails to `raw/emails`.
	- User stored handwritten notes or scanned pages (PDF, JPG) in `raw/scans`.

- **Ingest notes:**
	- User asks to "ingest new raw notes", "ingest Confluence page `<URL>`" or runs `wiki-ingest.loop.sh`.
	- LLM converts non-Markdown inputs: `.vtt` transcripts → `raw/transcripts/converted/`, `.eml` emails → `raw/emails/converted/`, `.pdf/.jpg` scans → `raw/scans/converted/`.
	- LLM partitions files into batches and processes them (large ingests use parallel LLM sessions 2–5; single batches are handled in one session).
	- After all batches are done, user says "finalize ingest" to merge session logs, rebuild `_index.md` files, and run post-processing (QMD re-index + health check).
   
- **Query wiki:**
	- User asks a high-level question.
	- LLM queries semantic database (with the `qmd` skill) for relevant page links (fast/token-efficient).
	- LLM processes suggested pages and produces answer to user.
	- LLM stores valuable conversations in `wiki/conversations/` to extend the knowledge base.

The combination of using a semantic database to fetch relevant pages before analyzing documents and reasoning about them, makes this implementation of a knowledge significantly faster and more token efficient than when it's using Markdown files only.

## Commands and skills

These skills commands and natural-language triggers are available:

| Command / phrase          | Description |
| ----------------          | ----------- |
| "ingest new notes"        | Start a new ingest of raw notes (Session 1 — coordinator flow) |
| "fetch slack"             | Fetch Slack threads and DMs into `raw/slack/`, then run `wiki-ingest-loop.sh` to ingest |
| "ingest next batch"       | Continue ingesting the next batch (Sessions 2–N flow) |
| "finalize ingest"         | Finalize the ingest: merge logs, rebuild indexes, run post-processing |
| "health check" or "lint"  | Check for orphaned pages, broken links, contradictions |
| "add missing [topic]"     | Create a new Wiki page for a missing concept, person, system, etc. |
| "clear ingest batches"    | Remove incomplete batch files to restart a failed ingest |
| ask any question          | Query the knowledge base (default behavior) |

The `ingest next batch` and `finalize ingest` commands are only needed for importing large amounts of notes. LLM will notify you when you `ingest new notes` and it sees it requires batched importing.

### Pro-tip 1: use `wiki-ingest-loop.sh` to ingest multiple files

You can use the script "scripts/wiki-ingest-loop.sh" to start ingesting new notes. The advantage of this script is that it will try to ingest new notes in batches, and wait if your 5h limit has been reached. It will first execute "ingest new notes" followed by as many "ingest next batch" prompts as necessary (up to a specified maximum). Use "--help" for help for this script.

You start it for a specific agent (Claude CLI or Junie CLI), like this
```
scripts/wiki-ingest.loop.sh [--agent claude|junie]    
```

Use `wiki-ingest.loop.sh --help` for more options.

### Pro-tip 2: use `wiki-lint-check.py` to health-check your knowledge base

After each ingestion, the system can automatically run a health check on the knowledge base. It performs an automated, basic health-check and will check for missing topics, inconsistencies etc. using the LLM (takes time and tokens).

You can also run the basic health-check (which does not use the LLM) manually, by simply executing:
```
scripts/wiki-lint-check.py
```

This opens an interactive TUI to deal with:
- Broken links: these can be removed, flagged or simply replaced with plain text.
- Orphaned pages: these can be deleted, or kept (marked with `orphan: false`).
- Stub pages (that were identified by the LLM but never filled in): these can be deleted, or kept (no longer marked as `stub: true`).

Using this interactive mode, you should be able to keep your knowledge base 100% free of false positive alerts so it's easy to see if the knowledge base is still sound or not. Use `--batch-mode` to suppress the TUI and get text/JSON output only.

## Getting started

This knowledge base setup uses a combination of Obsidian (front-end), LLM and QMD (database) to create that knowledge base. It consists of:

- A `raw` directory, which is my territory: You put all my notes there; AI can only read this, not write.
- A `wiki` directory, which is consolidated information about the raw notes; this is almost exclusively AI territory.

After putting all your notes in the raw directories, the magic words for LLM are: “ingest new raw notes”. That will create the Wiki and update the semantic database (QMD). After that you can ask all sorts of questions to LLM and it can efficiently reason over 100s or 1000s of pages (I’m using 2700 pages now and it seems to work just fine).

The keyword here is AI efficiency: if you have 10s of notes, you don’t need any of this. If you have 100s, you’re already burning tokens. If you have 1000s of notes, LLM won’t handle this well without a semantic database backing the search.

The directory is readable as an Obsidian vault. This is on purpose. Obsidian makes it really easy to add Markdown notes and read them, or do simple searches. You can use a LLM CLI next to it to query the same directory. Alternatively, you can run the whole thing in VS Code. 

I’ve tried to make this pretty user-friendly, so putting stuff in the ‘raw’ directory is as easy as:
- Using Obsidian to create Markdown notes, and storing PDF or JPG attachments in the ‘\_resources’ directory (LLM will parse those and recognize handwriting and convert those to Markdown as well).
- Using the Obsidian Web Clipper to automatically clip articles to ‘raw/clips’ (clipper template provided in repo); this means it’s just one Shift-Cmd-O press to store an article in the right location.
- Using drag-and-drop from Outlook to the ‘raw/emails’ directory to store ‘.eml’ files (LLM will use the provided conversion script to create perfect Markdowns of these); putting an alias to the email directory on your desktop makes it easy to find that directory for drag-and-drop 😊.
- Storing meeting transcripts (‘.vtt’) in ‘raw/transcripts’ (LLM will convert those to Markdown as well).

### Ingesting notes for the first time

If you have pre-existing notes and you want to ingest them into the knowledge base, make sure they are located in the correct `raw/*` directories first. See the directory structure below. Then run:
```
scripts/wiki-ingest-loop.sh [--agent claude|junie]
```

This starts the ingestion loop and tries to deal with rate limiting (e.g. the Claude 5-hour token limit).

### Personalizing your setup

You can provide personal info on who you are, what you do and what your focus is, in `config/personal_info.md`. This could be something like this:

```
# Personal Info
My name is ...
I am ...

# My Main Focus
- Strategic decision making on technology choices.
- ...
```

If the file is missing, or it contains no info topics, default topics will be used.

### Re-creating the Wiki from Scratch

To re-create the entire Wiki, you can simply remove the `wiki/` directory, `/clear` the LLM conversations and ask it to `ingest new raw notes`. This will restart the entire ingestion process. Note that for large amounts of notes, this may be expensive and take a long time.

**Important:* The ingesting notes is a relatively expensive operation (as the LLM necessasrily needs to relate many notes to distill and create Wiki topics). If you are using the knowledge base on multipl client you _can_ recreate the entire Wiki from scratch if you just share the `raw/` directory, but it may be more cost effective to simply share the `wiki/` directory as well. The file `wiki/log.jsonl` keeps track of which notes have been ingested, so anhy client can run ingestions to keep the Wiki up to date.

### Checking Your Database

The database is automatically checked for errors after ingesting new notes, but sometimes the errors cannot be fixed automatically. You are advised to sometimes run:
```
./scripts/wiki-lint-check.py --batch-mode --format text
```
This checks the consistency of your entire database without opening the TUI. For interactive review, simply run:
```
./scripts/wiki-lint-check.py
```
This provides a TUI to deal with broken links by
- removing them, 
- simply marking them as broken, or 
- allowing you to search for the proper target link in `raw` and `wiki` and replacing it with that.
Try it out. It's quite user-friendly.

## Installation

### Obsidian

Download and install [Obsidian](https://obsidian.md) (free, Mac/Windows/Linux). Open this directory as a vault: **Open folder as vault** → select the repo root. Obsidian reads the `wiki/` pages with WikiLink navigation, graph view, and backlinks out of the box — no plugins required for basic use.

For web clipping, install the [Obsidian Web Clipper](https://obsidian.md/clipper) browser extension and import `obsidian_webclipper_template.json` from this repo as a clipper template.

### QMD

QMD is the local semantic search engine that lets LLM query thousands of notes efficiently without reading every file.

Install via Homebrew:

```sh
npm install -g bun
npm install -g @tobilu/qmd
```

Register all `raw/` and `wiki/` subdirectories as QMD collections:

```sh
./scripts/qmd-sync-collections.sh
```

Then build the index (this can take a while!):

```sh
qmd update && qmd embed   
```

Register QMD as a MCP server (simply ask LLM to read this `README.md` and install it for you):

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

Installing the LLM skill isn't needed - it's part of this repo. But if you want to do it manually (again):
```sh
qmd skill install --global --yes   # or omit --global if you want it local-omly
```
Re-run `qmd update` (and `qmd embed`) after each ingest to keep the index current. LLM will prompt you to do this at the end of every ingest.

### Install `pdftotext`

The LLM can convert PDFs to text, but that's quite expensive. If you have `pdftotext` installed, the ingest skill will first try that and only fall back to LLM vision if the result is not looking good (e.g. for handwritten notes). Install `pdftotext` using:
```
brew install poppler
```

### Tip: Install Amphetamine (to avoid your Mac going to sleep)

Long ingest runs may cause your Mac to fall asleep when waiting for your Claude grace-period to pass ("the 5h window"). You may want to install a tool like Amphetamine from the AppStore to keep your Mac awake during the night...

### Running Claude within Obsidian

You can run Claude from within Obsidian using the Claudian plugin. Install the plugin simply by asking Claude to do so with the following prompt:
```
Claude, I want you to install the following Obsidian plugin from Github. First, I want you to review ihe plugin
and make sure it is safe to install. And if it is safe, install it. This is the repo: https://github.com/YishenTu/claudian
```

## Directory structure (condensed)

```
<root>/
├── .import/             ← in-progress batch import state (gitignored)
├── config/              ← config file for Obsidian web clipper
├── scripts/             ← helper scripts for CLAUDE.md
├── raw/
│   ├── clips/           ← web articles and saved pages (web clipper)
│   ├── confluence/      ← pages fetched from Atlassian Confluence (fetch cache)
│   ├── emails/          ← email threads (.eml)
│   │   └── converted/   ← LLM generated: emails converted to Markdown
│   ├── scans/           ← handwritten pages, whiteboards
│   │   └── converted/   ← LLM generated: scans converted to Markdown
│   ├── notes/           ← notes, 1:1s, and people-specific files
│   └── transcripts/     ← meeting and conversation transcripts (.vtt)
│       └── converted/   ← LLM generated: transcripts converted to Markdown
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
├── CLAUDE.md            ← schema and workflow instructions for Claude Code
└── README.md            ← this file
```
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
| `wiki-ingest-loop.sh` | Main ingestion pipeline: converts raw files (VTT, EML), creates batches if needed, and runs ingestion sessions in a loop until all notes are processed. The normal way to ingest new notes. |
| `wiki-lint-check.py` | Scans wiki Markdown files for broken internal and external links. Outputs structured JSON for AI consumption. Run periodically to keep the wiki healthy. |

### Occasional use

| Script | Purpose |
| ------ | ------- |
| `wiki-remove-all-generated-files.sh` | Deletes all LLM-generated wiki files and batch state, resetting the wiki to a clean slate. Use when you want to re-ingest everything from scratch. |
| `wiki-remove-large-attachments.py` | Interactive TUI for browsing and removing large Obsidian attachments. Navigate with ↑↓, press `d`/`D` to move files to `.trash/`. Useful for reclaiming disk space. |
| `qmd-reset-collections.sh` | Removes all QMD collections and wipes the search index database. Use before a full re-sync. |
| `copy-claude-skills-to-other-agents.sh` | Copies `.claude/skills/` to other AI agent config directories (Junie, Gemini, Codex, etc.) so all agents share the same skill set. |

### For use by skills (not normally run directly)

| Script | Purpose |
| ------ | ------- |
| `wiki-create-import-batches.sh` | Partitions un-ingested notes into batch files for parallel import sessions. Called automatically by `wiki-ingest-loop.sh` and the `wiki-ingest` skill. |
| `wiki-create-index-pages.py` | Rebuilds `_index.md` files for each wiki section. Called by the `wiki-finalize-ingest` skill after a completed ingest run. |
| `qmd-sync-collections.sh` | Adds all `raw/` and `wiki/` subdirectories as QMD collections (idempotent) and re-indexes them. Called by the `wiki-finalize-ingest` skill. |
| `convert-eml-to-md.py` | Converts `.eml` email files to Markdown with YAML frontmatter. Called by `wiki-ingest-loop.sh` before ingestion. |
| `convert-vtt-to-md.py` | Converts `.vtt` transcript files to readable Markdown with YAML frontmatter. Called by `wiki-ingest-loop.sh` before ingestion. |

## Recognition

- Andrej Karpathy - for his original idea for the [LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).
- Rob van der Most - for brainstorming and experimenting with this idea.
