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
FAILED=0

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
            [[ $# -ge 2 ]] || { echo "ERROR: --root requires a directory argument" >&2; exit 2; }
            ROOT="$2"
            shift 2
            ;;
        --limit)
            [[ $# -ge 2 ]] || { echo "ERROR: --limit requires a value" >&2; exit 2; }
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

run_step() {
    local label="$1"
    shift
    echo "$label"
    set +e
    "$@"
    local rc=$?
    set -e
    if [ "$rc" -ne 0 ]; then
        FAILED=1
        echo "WARN: $label exited with status $rc" >&2
    fi
    echo ""
}

run_step "1/4 Provenance lint" \
    python3 "$PROJECT_DIR/scripts/system/wiki-provenance-lint.py" --root "$ROOT" --format text

run_step "2/4 Freshness inventory" \
    python3 "$PROJECT_DIR/scripts/system/wiki-freshness-inventory.py" --root "$ROOT" --format text

drift_args=(--root "$ROOT" --limit "$LIMIT" --format text)
if [ "$WRITE" = true ]; then
    drift_args+=(--write-queue)
fi
run_step "3/4 Freshness drift queue" \
    python3 "$PROJECT_DIR/scripts/system/wiki-drift-detect.py" "${drift_args[@]}"

coverage_args=(--root "$ROOT" --limit "$LIMIT" --format text)
if [ "$WRITE" = true ]; then
    coverage_args+=(--write-backlog)
fi
run_step "4/4 Provenance coverage backlog" \
    python3 "$PROJECT_DIR/scripts/system/wiki-provenance-coverage.py" "${coverage_args[@]}"

echo "Freshness check complete."
if [ "$WRITE" = true ]; then
    echo "Queue files:"
    echo "  $ROOT/.wiki-scratch/freshness-curation-candidates.md"
    echo "  $ROOT/.wiki-scratch/provenance-coverage-backlog.md"
fi
exit "$FAILED"
