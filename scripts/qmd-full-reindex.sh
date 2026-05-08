#!/usr/bin/env bash
# Full qmd reindex: register collections + text re-index + vector embeddings.
# Use this after every ingest phase.
#
# Usage:
#   bash scripts/qmd-full-reindex.sh [--skip-embed] [--reset]
#
# Flags:
#   --skip-embed  Run text re-index only (skip the slow vector embedding step).
#                 Use when iterating quickly; embeddings can be regenerated later.
#   --reset       Drop ALL collections and the index DB first (destructive),
#                 then re-register and re-index everything from scratch.
#
# Exit codes:
#   0  success
#   1  qmd CLI not available
#   2  bad arguments
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

SKIP_EMBED=false
DO_RESET=false
for arg in "$@"; do
  case "$arg" in
    --skip-embed) SKIP_EMBED=true ;;
    --reset)      DO_RESET=true ;;
    -h|--help)
      sed -n '2,/^set -euo/p' "$0" | sed 's/^# \{0,1\}//' | head -n -1
      exit 0
      ;;
    *) echo "ERROR: unknown arg: $arg" >&2; exit 2 ;;
  esac
done

if ! command -v qmd >/dev/null 2>&1; then
  echo "ERROR: qmd CLI not on PATH." >&2
  exit 1
fi

echo "qmd full reindex"
echo "  repo:        $REPO_ROOT"
echo "  skip-embed:  $SKIP_EMBED"
echo "  reset:       $DO_RESET"
echo ""

if $DO_RESET; then
  echo "=== reset: removing collections and index db ==="
  bash "$REPO_ROOT/scripts/system/qmd-reset-collections.sh" --force
  echo ""
fi

echo "=== sync: register raw/* and wiki/* collections + qmd update ==="
bash "$REPO_ROOT/scripts/system/qmd-sync-collections.sh"
echo ""

if ! $SKIP_EMBED; then
  echo "=== embed: vector embeddings (this may take several minutes) ==="
  qmd embed
  echo ""
else
  echo "=== embed: skipped (--skip-embed) ==="
  echo ""
fi

echo "=== final status ==="
qmd status
echo ""
echo "Done. Run 'qmd query <text>' for combined BM25+vector search."
