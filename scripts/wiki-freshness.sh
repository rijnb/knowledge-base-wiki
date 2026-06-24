#!/usr/bin/env bash
# One-command freshness health check for the knowledge base.
#
# Runs the read-only provenance/freshness checks and writes the two working
# queues under .wiki-scratch/.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$PROJECT_DIR"
LIMIT=25
WRITE=true

usage() {
    cat <<EOF
Usage: $(basename "$0") [--root DIR] [--limit N] [--no-write] [--help]

Runs the freshness checks you normally want after ingest/finalize:
  - provenance lint
  - freshness inventory
  - drift queue generation
  - provenance coverage backlog generation

By default it writes:
  .wiki-scratch/freshness-curation-candidates.md
  .wiki-scratch/provenance-coverage-backlog.md

Options:
  --root DIR   Vault root to scan (default: this repository)
  --limit N    Number of entries printed by drift/coverage scripts (default: 25)
  --no-write   Do not write queue/backlog files
  --help       Show this help and exit
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --root)
            ROOT="$2"
            shift 2
            ;;
        --limit)
            [[ "$2" =~ ^[0-9]+$ ]] || { echo "--limit must be a non-negative integer" >&2; exit 1; }
            LIMIT="$2"
            shift 2
            ;;
        --no-write)
            WRITE=false
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

ROOT="$(cd "$ROOT" && pwd)"

echo "=== Wiki Freshness Check ==="
echo "Vault root: $ROOT"
echo ""

echo "1/4 Provenance lint"
python3 "$PROJECT_DIR/scripts/system/wiki-provenance-lint.py" --root "$ROOT" --format text
echo ""

echo "2/4 Freshness inventory"
python3 "$PROJECT_DIR/scripts/system/wiki-freshness-inventory.py" --root "$ROOT" --format text
echo ""

echo "3/4 Freshness drift queue"
drift_args=(--root "$ROOT" --limit "$LIMIT" --format text)
if [ "$WRITE" = true ]; then
    drift_args+=(--write-queue)
fi
python3 "$PROJECT_DIR/scripts/system/wiki-drift-detect.py" "${drift_args[@]}"
echo ""

echo "4/4 Provenance coverage backlog"
coverage_args=(--root "$ROOT" --limit "$LIMIT" --format text)
if [ "$WRITE" = true ]; then
    coverage_args+=(--write-backlog)
fi
python3 "$PROJECT_DIR/scripts/system/wiki-provenance-coverage.py" "${coverage_args[@]}"
echo ""

echo "Freshness check complete."
if [ "$WRITE" = true ]; then
    echo "Queue files:"
    echo "  $ROOT/.wiki-scratch/freshness-curation-candidates.md"
    echo "  $ROOT/.wiki-scratch/provenance-coverage-backlog.md"
fi
