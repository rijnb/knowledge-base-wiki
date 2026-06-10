---
ai_backend: claude
---

# Settings

Configuration for the knowledge-base scripts under `scripts/`.

## ai_backend

`ai_backend` selects which local LLM CLI the scripts shell out to for
LLM-backed tasks (e.g. smart date inference in wiki-doctor). Set it to one of:

| Value    | Provider    | Command run        |
|----------|-------------|--------------------|
| `claude` | Anthropic   | `claude -p ...`    |
| `vibe`   | Mistral AI  | `vibe -p ...`      |
| `codex`  | OpenAI      | `codex exec ...`   |

Change the value in the frontmatter above and save -- no code changes needed.
If the chosen CLI is not installed (or fails), the scripts fall back to their
deterministic behaviour instead of erroring.
