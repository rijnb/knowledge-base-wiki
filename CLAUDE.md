# Knowledge base wiki
(C) 2026, Rijn Buve

This is an LLM-maintained knowledge base for work. The primary goal is **decision intelligence**: understanding why decisions were taken, on what basis, by whom, and when. 

Secondary goals are mapping how technologies and systems relate, who is involved in what, and how competitors compare. 

The user curates the 'raw' source files; the LLM never changes the 'raw' files. The LLM maintains the wiki, does all writing, cross-referencing, and bookkeeping. The user reads the wiki, but never, or hardly ever, touches it.
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
	- LLM transcribes non-Markdown `raw/transcripts` (`.vtt`) and `raw/scans` (`.pdf/.jpg`) to Markdown (in `transcribed` directories)
	- LLM ingests raw notes and updates all relevant wiki topic pages in `wiki/`
	- LLM updates the semantic database `qmd` and runs a health check to keep the knowledge base lean and clean (after user confirmation)
- **query wiki** 
	- user asks a high-level question
	- LLM queries semantic database (with the `qmd` skill) for relevant page links (fast/token-efficient)
	- LLM processes `qmd`-suggested pages and produces answer to user
	- LLM store valuable conversations in `raw/conversations` to extend the knowledge base (after user confirmation)

The combination of using a semantic database to fetch relevant pages before analyzing documents and reasoning about them, makes this implementation of a knowledge significantly faster and more token efficient than when it's using Markdown files only.
## Directory structure (condensed)

```
<root>/
├── config/              ← config file for Obsidian web clipper
├── scripts/             ← helper scripts for CLAUDE.md
├── raw/
│   ├── clips/           ← web articles and saved pages (web clipper)
│   ├── confluence/      ← pages fetched from Atlassian Confluence (fetch cache)
│   ├── emails/          ← email threads (.elm)
│   ├── notes/           ← notes, 1:1s, and people-specific files
│   ├── scans/           ← handwritten pages, whiteboards
│   │   └── transcribed/ ← transcribed scans (LLM-generated Markdown)
│   └── transcripts/     ← meeting and conversation transcripts (.vtt)
├── wiki/
│   ├── index.md         ← top-level navigation to section indexes
│   ├── log.md           ← append-only ingest log
│   ├── concepts/        ← mental models and domain concepts
│   │   └── _index.md    ← alphabetical index of all concept pages
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

**Rule:** `raw/` is immutable — the LLM reads from it, never writes to it (exception: `raw/confluence/` is written during Confluence fetch — treat as a fetch cache). `wiki/` is LLM-owned — the LLM writes, the user reads. Always update the relevant `wiki/<type>/_index.md` and `wiki/log.md` on every ingest. `CLAUDE.md` is co-evolved by both.

Only the Claude prompt and scripts are part of the Git repository, the raw notes and the generated wiki are not stored in Git.
## Workflows

Use the appropriate skill for each action:
- **Ingest** (notes, Confluence, bulk) — `knowledge-base-ingest` skill
- **Query** — `knowledge-base-query` skill (default: use this when the user asks any question)
- **Health check / lint** — `knowledge-base-health-check` skill
- **Creating wiki pages** — `knowledge-base-templates` skill
## Topic types in `wiki/` (priority order)

1. **Concepts** — technologies, standards, mental models, domain vocabulary
2. **Systems** — our products, platforms, and services
3. **Decisions** — why decisions were taken, on what basis, by whom, and when
4. **Projects** — active and past initiatives
5. **Problems** — active and past problems
6. **Competitors** — competing companies, products, and approaches
7. **People** — colleagues, contacts, external stakeholders, teams
