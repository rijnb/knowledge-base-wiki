# Knowledge base wiki

(C) 2026, Rijn Buve

This repository contains a solid implementation of [Andrej Karpathy's LLM Wiki idea](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f). It is an LLM-maintained knowledge base for work-related notes, structured as an [Obsidian](https://obsidian.md) vault, assisted by the semantic database [QMD](https://github.com/tobi/qmd).
## Purpose

The primary goal is **efficient decision intelligence**: understanding why decisions were taken, on what basis, by whom, and when. Secondary goals include mapping how technologies and systems relate, who is involved in what, and how competitors compare. And 'efficient', because the mechanism needs to be token (and environmentally) efficient.

**Division of labor:** The user curates source files in `raw/`. Claude Code does all writing, cross-referencing, and bookkeeping in `wiki/`. 
## In a nutshell

Access to the knowledge base is as follows:
- **create and collect notes** 
	- user produces raw notes and stores them in the `raw/notes` directory, or
	- user uses the Obsidian Web Clipper to store notes in `raw/clips`, or
	- user stores `.vtt` meeting transcripts in `raw/transcripts`, or
	- user drags `.eml` emails to `raw/emails`, or
	- user stored handwritten notes or scanned pages (PDF, JPG) in `raw/scans`
- **ingest notes**
	- user asks to ingest (new) raw notes
	- LLM transcribes non-Markdown `raw/transcripts` (`.vtt`) and `raw/scans` (`.pdf/.jpg`) to Markdown
	- LLM ingests raw notes and updates all relevant wiki topic pages in `wiki/`
	- LLM updates the semantic database `qmd` and runs a health check to keep the knowledge base lean and clean (after user confirmation)
- **query wiki** 
	- user asks a high-level question
	- LLM queries semantic database (with the `qmd` skill) for relevant page links (fast/token-efficient)
	- LLM processes `qmd`-suggested pages and produces answer to user
	- LLM store valuable conversations in `raw/conversations` to extend the knowledge base

The combination of using a semantic database to fetch relevant pages before analyzing documents and reasoning about them, makes this implementation of a knowledge significantly faster and more token efficient than when it's using Markdown files only.
## Getting started

This knowledge base setup uses a combination of Obsidian (front-end), Claude and QMD (database) to create that knowledge base. It consists of:

- a `raw` directory, which is my territory: I put all my notes there; AI can only read this, not write
- a `wiki` directory, which is consolidated information about the raw notes; this is almost exclusively AI territory

After putting all your notes in the raw directories, the magic word for Claude is: “ingest raw notes”. That will create the wiki and update the semantic database (QMD). After that you can ask all sorts of questions to Claude and it can efficiently reason over 100s or 1000s of pages (I’m using 2700 pages now and it seems to work just fine).

The keyword here is AI efficiency: if you have 10s of notes, you don’t need any of this. If you have 100s, you’re already burning tokens. If you have 1000s of notes, Claude won’t handle this well without a semantic database backing the search.

The directory is readable as an Obsidian vault. This is on purpose. Obsidian makes it really easy to add Markdown notes and read them, or do simple searches. You can use a Claude CLI next to it to query the same directory. Alternatively, you can run the whole thing in VS Code. 

I’ve tried to make this pretty user-friendly, so putting stuff in the ‘raw’ directory is as easy as:
- using Obsidian to create Markdown notes, and storing PDF or JPG attachments in the ‘\_resources’ directory (Claude will parse those and recognize handwriting and convert those to Markdown as well)
- using the Obsidian Web Clipper to automatically clip articles to ‘raw/clips’ (clipper template provided in repo); this means it’s just one Shift-Cmd-O press to store an article in the right location
- using drag-and-drop from Outlook to the ‘raw/emails’ directory to store ‘.eml’ files (Claude will use the provided conversion script to create perfect Markdowns of these); putting an alias to the email directory on your desktop makes it easy to find that directory for drag-and-drop 😊 
- storing meeting transcripts (‘.vtt’) in ‘raw/transcripts’ (Claude will convert those to Markdown as well)
## Installation

### Obsidian

Download and install [Obsidian](https://obsidian.md) (free, Mac/Windows/Linux). Open this directory as a vault: **Open folder as vault** → select the repo root. Obsidian reads the `wiki/` pages with wikilink navigation, graph view, and backlinks out of the box — no plugins required for basic use.

For web clipping, install the [Obsidian Web Clipper](https://obsidian.md/clipper) browser extension and import `Obsidian Web Clipper Template.json` from this repo as a clipper template.
### QMD

QMD is the local semantic search engine that lets Claude query thousands of notes efficiently without reading every file.

Install via Homebrew:

```sh
brew install qmd
```

Register all `raw/` and `wiki/` subdirectories as QMD collections:

```sh
./scripts/qmd-sync-collections.sh
```

Then build the index:

```sh
qmd update                # text index (fast, ~seconds)
qmd update && qmd embed   # + vector embeddings (slow; needed for semantic search)
```

Register QMD as a Claude Code MCP server by adding the following to your `~/.claude/claude_desktop_config.json` (or equivalent Claude config):

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

Installing the Claude skill isn't needed - it's part of this repo. But if you want to do it manually (again):
```sh
qmd skill install --global --yes   # or omit --global if you want it local-omly
```
Re-run `qmd update` (and `qmd embed`) after each ingest to keep the index current. Claude will prompt you to do this at the end of every ingest.
## Directory structure (condensed)

```
<root>/
├── config/              ← config file for Obsidian web clipper
├── scripts/             ← helper scripts for CLAUDE.md
├── raw/
│   ├── clips/           ← web articles and saved pages (web clipper)
│   ├── confluence/      ← pages fetched from Atlassian Confluence (fetch cache)
│   ├── emails/          ← email threads (.eml)
│   ├── scans/           ← handwritten pages, whiteboards
│   │   └── transcribed/ ← transcribed scans (LLM-generated Markdown)
│   ├── notes/           ← notes, 1:1s, and people-specific files
│   └── transcripts/     ← meeting and conversation transcripts (.vtt)
├── wiki/
│   ├── index.md         ← top-level navigation to section indexes
│   ├── log.md           ← append-only ingest log
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
| **Concepts**      | Technologies, standards, mental models, domain vocabulary  |
| **Competitors**   | Competing companies, products, and approaches              |
| **Conversations** | Valuable results of earlier queries/conversations          |
| **Decisions**     | Why decisions were taken, on what basis, by whom, and when |
| **People**        | Colleagues, contacts, external stakeholders, teams         |
| **Problems**      | Active and past problems                                   |
| **Projects**      | Active and past initiatives                                |
| **Systems**       | System, products, platforms, and services                  |
## Key rules

- `raw/` is immutable — Claude never writes there (except `raw/confluence/` as a fetch cache).
- `wiki/` is LLM-owned — Claude writes, the user reads.
- The relevant `wiki/<type>/_index.md` and `wiki/log.md` are updated on every ingest.
- Hand-curated content in wiki pages is never deleted or overwritten.
## Recognition

- Andrej Karpathy - for his original idea for the [LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).
- Rob van der Most - for brainstorming and experimenting with this idea.
