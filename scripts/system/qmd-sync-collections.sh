#!/usr/bin/env bash
# Registers the vault root as a single QMD collection named "tomtom", then re-indexes and embeds.
# Removes stale wiki-* and raw-* subdirectory collections if present.
#
# Usage: qmd-sync-collections.sh [--root DIR] [--skip-embed]
#   --root DIR    Vault root to register (default: this repository)
#   --skip-embed  Skip the vector embedding step (text re-index only).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
SKIP_EMBED=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --root)
      REPO="$(cd "$2" && pwd)"
      shift 2
      ;;
    --skip-embed)
      SKIP_EMBED=true
      shift
      ;;
    *) echo "ERROR: unknown arg: $1" >&2; exit 2 ;;
  esac
done

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
    _embed_exit=0
    qmd embed || _embed_exit=$?
    if [ $_embed_exit -ne 0 ]; then
      echo "ERROR: qmd embed failed (exit $_embed_exit)" >&2
      exit $_embed_exit
    fi
    # qmd prints "<N> need embedding" (plural) or "1 needs embedding" (singular);
    # match both forms, case-insensitively, so the loop continues until done.
    qmd status | grep -iqE "needs? embedding" || break
    echo "qmd status still shows pending embeddings, retrying..."
  done
  echo ""
else
  echo "=== Embedding: skipped (--skip-embed) ==="
  echo ""
fi

echo "Done."
