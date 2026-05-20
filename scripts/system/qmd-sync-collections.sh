#!/usr/bin/env bash
# Adds all subdirs from raw/ and wiki/ as QMD collections (idempotent), then re-indexes and embeds.
# Collection names use the full relative path with dashes: raw-clips, wiki-people, raw-scans-transcribed.
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

# $1 = absolute path, $2 = collection name (dash-joined relative path)
add_if_missing() {
  local path="$1"
  local name="$2"

  if echo "$existing" | grep -qx "$name"; then
    echo "  [skip] $name"
  else
    echo "  [add]  $name → $path"
    qmd collection add "$path" --name "$name"
  fi
}

scan_dir() {
  local root="$1"
  local prefix="$2"
  echo "=== Scanning $prefix/ ==="
  for dir in "$root"/*/; do
    [[ -d "$dir" ]] || continue
    local dname
    dname="$(basename "${dir%/}")"
    [[ "$dname" == _* ]] && continue
    add_if_missing "${dir%/}" "$prefix-$dname"
    for subdir in "$dir"*/; do
      [[ -d "$subdir" ]] || continue
      local sname
      sname="$(basename "${subdir%/}")"
      [[ "$sname" == _* ]] && continue
      add_if_missing "${subdir%/}" "$prefix-$dname-$sname"
    done
  done
}

scan_dir "$REPO/raw"  "raw"
echo ""
scan_dir "$REPO/wiki" "wiki"

echo ""
echo "=== Re-indexing ==="
qmd update

echo ""
if ! $SKIP_EMBED; then
  echo "=== Embedding (vector embeddings) ==="
  qmd embed
  echo ""
else
  echo "=== Embedding: skipped (--skip-embed) ==="
  echo ""
fi

echo "Done."
