#!/usr/bin/env bash
# Registers the vault root as a single QMD collection named "tomtom", then re-indexes and embeds.
# Removes stale wiki-* and raw-* subdirectory collections if present.
#
# Usage: qmd-sync-collections.sh [--skip-embed]
#   --skip-embed  Skip the vector embedding step (text re-index only).
set -euo pipefail

SKIP_EMBED=false
for arg in "$@"; do
  case "$arg" in
    --skip-embed) SKIP_EMBED=true ;;
    *) echo "ERROR: unknown arg: $arg" >&2; exit 2 ;;
  esac
done

REPO="$(cd "$(dirname "$0")/../.." && pwd)"

existing=$(qmd collection list 2>/dev/null | awk '/^[^ ]/ && NR>1 { sub(/ \(.*/, ""); print }')

echo "=== Removing stale subdirectory collections ==="
while IFS= read -r name; do
  [[ -z "$name" ]] && continue
  if [[ "$name" == wiki-* || "$name" == raw-* ]]; then
    echo "  [remove] $name"
    qmd collection remove "$name"
  fi
done <<< "$existing"

echo ""
echo "=== Registering vault root ==="
if echo "$existing" | grep -qx "tomtom"; then
  echo "  [skip] tomtom (already registered)"
else
  echo "  [add]  tomtom → $REPO"
  qmd collection add "$REPO" --name "tomtom"
fi

echo ""
echo "=== Re-indexing ==="
qmd update

echo ""
if ! $SKIP_EMBED; then
  echo "=== Embedding (vector embeddings) ==="
  while true; do
    _embed_start=$(date +%s)
    _embed_exit=0
    qmd embed || _embed_exit=$?
    _embed_elapsed=$(( $(date +%s) - _embed_start ))
    if [ $_embed_exit -eq 0 ]; then
      break
    elif [ $_embed_elapsed -ge 1500 ]; then
      echo "qmd embed timed out after ${_embed_elapsed}s, retrying..."
    else
      echo "ERROR: qmd embed failed (exit $_embed_exit) after ${_embed_elapsed}s" >&2
      exit $_embed_exit
    fi
  done
  echo ""
else
  echo "=== Embedding: skipped (--skip-embed) ==="
  echo ""
fi

echo "Done."
