---
ai_backend: claude
---

# Settings

Configuration for the knowledge-base scripts under `scripts/`.

## ai_backend

`ai_backend` selects which local LLM CLI `scripts/wiki-ingest.sh` shells out
to for the LLM-backed ingest sessions. Set it to one of:

| Value    | Provider    | Command run                          |
|----------|-------------|--------------------------------------|
| `claude` | Anthropic   | `claude -p ...`                      |
| `vibe`   | Mistral AI  | `vibe -p ...`                        |
| `codex`  | OpenAI      | `codex exec ...`                     |
| `junie`  | JetBrains   | `junie --brave ... --task` (experimental) |

Change the value in the frontmatter above and save -- no code changes needed.
Usage throttling (the 5-hour window pause) only works for `claude`. If the
chosen CLI is not installed (or fails), the script stops before consuming
LLM-backed batches; the deterministic conversion and batching steps are
unaffected.
