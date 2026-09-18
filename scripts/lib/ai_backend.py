"""LLM backend selection and invocation for the Python pipeline scripts.

Mirrors `scripts/wiki-ingest.sh`'s `read_ai_backend_setting` / `backend_command`
so both entry points obey the same `ai_backend:` value in `config/settings.md`.

Only `claude` supports `model` and `bare`; the other backends silently ignore
them, exactly as the shell pipeline does.
"""

import shutil
import subprocess
from pathlib import Path

from .frontmatter import split_frontmatter


BACKENDS = ("claude", "vibe", "codex")
DEFAULT_BACKEND = "claude"

# CLI model aliases, not API model ids.
#
# Sonnet does the taxonomy work: it needs judgement, and a weaker model
# reproduces the vocabulary's existing flatness.
#
# Sonnet also does the assignment, which was not the original plan. Measured
# A/B on two identical 50-note bundles (2026-09-17): Sonnet ran 16-17s against
# Haiku's 51-57s, kept about half the off-list rate (~3.7% vs ~7.1%), and gave
# a steadier 4.2-4.4 tags per note against Haiku's erratic 3.7-4.7. The two
# agreed on almost nothing (mean Jaccard 0.21, identical on 0 of 50 notes both
# runs), and on inspection Haiku's misses were title-word traps
# (`hr/psychology` for an article about prompt engineering) and near-miss
# entities (`tool/github` for GitNexus) — errors a closed vocabulary cannot
# catch, because the wrong tag is still a valid tag. The whole phase costs
# ~$6.81 on Sonnet against ~$3.41 on Haiku.
MODEL_TAXONOMY = "sonnet"
MODEL_ASSIGN = "sonnet"


def read_backend(root: Path) -> str:
    """The `ai_backend:` setting, defaulting to claude for missing/unknown values."""
    settings = root / "config" / "settings.md"
    if not settings.is_file():
        return DEFAULT_BACKEND
    data, _ = split_frontmatter(settings.read_text(encoding="utf-8", errors="replace"))
    value = (data.get("ai_backend") or "").strip()
    return value if value in BACKENDS else DEFAULT_BACKEND


def executable(root: Path) -> str | None:
    """Path to the configured backend's CLI, or None when it is not installed."""
    return shutil.which(read_backend(root))


def available(root: Path) -> bool:
    return executable(root) is not None


def _command(backend: str, cli: str, prompt: str, model: str | None, bare: bool) -> list[str]:
    if backend == "codex":
        return [cli, "exec", prompt]
    cmd = [cli, "-p", prompt]
    if backend == "claude":
        if model:
            cmd += ["--model", model]
        if bare:
            # Not an optimisation but a containment measure: with no tools and
            # no settings sources the subprocess cannot open a file — a PDF
            # least of all — and does not load CLAUDE.md/AGENTS.md. It also
            # drops the per-call context from ~46k tokens to ~9k.
            cmd += ["--tools", "", "--setting-sources", ""]
    return cmd


def run(
    prompt: str,
    *,
    root: Path,
    timeout: int = 300,
    model: str | None = None,
    bare: bool = True,
) -> str | None:
    """Run one completion. Returns stdout, or None on any failure.

    Failures are swallowed on purpose: callers treat a None as "this bundle
    produced no lines", record the affected items on a failed list, and carry
    on. A run of hundreds of bundles must not die on one bad response.

    `stdin` is closed deliberately — `claude -p` also reads stdin and *appends
    it to the prompt*, so an inherited stdin leaks the caller's own text into
    the question and the model answers that instead.
    """
    cli = executable(root)
    if cli is None:
        return None
    cmd = _command(read_backend(root), cli, prompt, model, bare)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None
