#!/bin/sh
# Shared allowlist for the fail-safe hooks (pre-commit, pre-push).
# Keep in sync with .gitignore. Anything NOT matching is treated as a
# personal note and blocked.
ALLOW='^(\.gitignore|AGENTS\.md|CLAUDE\.md|LICENSE|README\.md|index\.md|config/|templates/|scripts/|\.githooks/|\.(claude|agents|codex)/(skills|agents)/|INBOX/(\.gitkeep|index\.md|RELEASE-NOTES\.md)$|raw/index\.md$|raw/(clips|confluence|diary|emails|notes|scans|slack|transcripts)/(index\.md|\.gitkeep)$|wiki/\.gitkeep$|\.import/\.gitkeep$)'

# Prints blocked paths from stdin (one path per line); exit 0 if none.
# $1 = label used in the error message (e.g. "pre-commit" or "pre-push").
check_paths() {
  label="$1"
  paths=$(cat)
  [ -z "$paths" ] && return 0

  cover=$(echo "$paths" | grep -E '(^|/)index\.jpg$' || true)
  if [ -n "$cover" ]; then
    echo "$label: BLOCKED -- index.jpg cover images are per-vault, never commit/push them:" >&2
    echo "$cover" | sed 's/^/  - /' >&2
    return 1
  fi

  local_cfg=$(echo "$paths" | grep -E '(^|/)\.claude/settings[^/]*\.json$' || true)
  if [ -n "$local_cfg" ]; then
    echo "$label: BLOCKED -- Claude Code settings files are per-machine, never commit/push them:" >&2
    echo "$local_cfg" | sed 's/^/  - /' >&2
    return 1
  fi

  personal=$(echo "$paths" | grep -E '^config/personal_info\.md$' || true)
  if [ -n "$personal" ]; then
    echo "$label: BLOCKED -- config/personal_info.md is personal, never commit/push it." >&2
    return 1
  fi

  bad=$(echo "$paths" | grep -Ev "$ALLOW" || true)
  if [ -n "$bad" ]; then
    echo "$label: BLOCKED -- files outside the infrastructure allowlist:" >&2
    echo "$bad" | sed 's/^/  - /' >&2
    echo "" >&2
    echo "These may be personal notes. Only genuine infrastructure may be added," >&2
    echo "and then to BOTH .gitignore AND .githooks/allowlist.sh." >&2
    return 1
  fi
  return 0
}
