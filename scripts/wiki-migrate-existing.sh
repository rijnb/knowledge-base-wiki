#!/usr/bin/env bash
# Safe migration wrapper for an existing raw/ + wiki/ knowledge base.
#
# Default mode is a dry-run. With --apply, the script prepares the existing
# corpus for provenance-aware use without bulk re-ingesting historical raw
# files. To allow a future ingest to process every old raw file again, pass
# --allow-reingest-existing explicitly.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$PROJECT_DIR"
APPLY=false
BASELINE_EXISTING=true
SKIP_LEGACY_LAYOUT=false
SKIP_QMD=false
QMD_EMBED=false
WRITE_REPORT=true
LIMIT=25

usage() {
    cat <<EOF
Usage: $(basename "$0") [--root DIR] [--apply] [--allow-reingest-existing] [--skip-legacy-layout] [--skip-qmd] [--qmd-embed] [--limit N] [--no-report] [--help]

Migrates an existing knowledge base into the provenance/freshness workflow.

Default behavior:
  - dry-run only; raw/wiki content is not modified
  - existing raw files are planned as migration-baselined, so future ingest will
    not re-ingest the historical corpus after --apply
  - QMD is text-indexed only during --apply (unless --skip-qmd or --qmd-embed)

With --apply, the script:
  1. verifies raw/ and wiki/ exist
  2. reports wiki-doctor structural health
  3. migrates legacy converted/ layout unless skipped
  4. baselines existing raw files in wiki/log.jsonl unless --allow-reingest-existing
  5. assigns freshness dates
  6. rebuilds wiki index pages
  7. syncs QMD unless skipped
  8. runs the freshness/provenance queues
  9. writes .wiki-scratch/migration-report.md unless --no-report

Options:
  --root DIR                 Vault root to migrate (default: this repository)
  --apply                    Modify files/logs instead of dry-running
  --allow-reingest-existing  Do NOT baseline existing raw files; a later ingest
                             may process the historical raw corpus
  --skip-legacy-layout       Do not run migrate-converted-to-resources.py
  --skip-qmd                 Do not run qmd sync
  --qmd-embed                Run QMD vector embedding too; default is text only
  --limit N                  Number of freshness entries to print (default: 25)
  --no-report                Do not write .wiki-scratch/migration-report.md
  --help                     Show this help and exit
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --root)
            ROOT="$2"
            shift 2
            ;;
        --apply)
            APPLY=true
            shift
            ;;
        --allow-reingest-existing)
            BASELINE_EXISTING=false
            shift
            ;;
        --skip-legacy-layout)
            SKIP_LEGACY_LAYOUT=true
            shift
            ;;
        --skip-qmd)
            SKIP_QMD=true
            shift
            ;;
        --qmd-embed)
            QMD_EMBED=true
            shift
            ;;
        --limit)
            [[ "$2" =~ ^[0-9]+$ ]] || { echo "--limit must be a non-negative integer" >&2; exit 2; }
            LIMIT="$2"
            shift 2
            ;;
        --no-report)
            WRITE_REPORT=false
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

ROOT="$(cd "$ROOT" && pwd)"
REPORT_PATH="$ROOT/.wiki-scratch/migration-report.md"
declare -a REPORT_LINES=()
declare -a STEP_STATUSES=()

record() {
    REPORT_LINES+=("$1")
}

say() {
    echo "$1"
    record "$1"
}

section() {
    echo ""
    say "## $1"
}

run_step() {
    local label="$1"
    shift
    section "$label"
    echo "+ $*"
    set +e
    "$@"
    local rc=$?
    set -e
    STEP_STATUSES+=("$label: $rc")
    if [ "$rc" -eq 0 ]; then
        say "status: ok"
    else
        say "status: warning/error ($rc)"
    fi
    return 0
}

write_report() {
    [ "$WRITE_REPORT" = true ] || return 0
    mkdir -p "$ROOT/.wiki-scratch"
    {
        echo "# Migration report"
        echo ""
        echo "- root: $ROOT"
        echo "- mode: $([ "$APPLY" = true ] && echo apply || echo dry-run)"
        echo "- existing raw baseline: $([ "$BASELINE_EXISTING" = true ] && echo enabled || echo disabled)"
        echo "- qmd: $([ "$SKIP_QMD" = true ] && echo skipped || { [ "$QMD_EMBED" = true ] && echo text-and-vector || echo text-only; })"
        echo ""
        printf '%s\n' "${REPORT_LINES[@]}"
        echo ""
        echo "## Step statuses"
        for status in "${STEP_STATUSES[@]}"; do
            echo "- $status"
        done
    } > "$REPORT_PATH"
    echo ""
    echo "Migration report written: $REPORT_PATH"
}

echo "=== Existing Knowledge Base Migration ==="
say "root: $ROOT"
say "mode: $([ "$APPLY" = true ] && echo apply || echo dry-run)"
say "baseline existing raw files: $([ "$BASELINE_EXISTING" = true ] && echo yes || echo no)"

if [ ! -d "$ROOT/raw" ]; then
    echo "ERROR: raw/ directory not found under $ROOT" >&2
    exit 1
fi
if [ ! -d "$ROOT/wiki" ]; then
    echo "ERROR: wiki/ directory not found under $ROOT" >&2
    exit 1
fi

run_step "Structural health report" \
    python3 "$PROJECT_DIR/scripts/wiki-doctor.py" --batch-mode --format text "$ROOT"

if [ "$SKIP_LEGACY_LAYOUT" = true ]; then
    section "Legacy converted/ layout"
    say "status: skipped"
else
    legacy_args=(--root "$ROOT")
    if [ "$APPLY" = true ]; then
        legacy_args+=(--apply)
    fi
    run_step "Legacy converted/ layout" \
        python3 "$PROJECT_DIR/scripts/system/migrate-converted-to-resources.py" "${legacy_args[@]}"
fi

if [ "$BASELINE_EXISTING" = true ]; then
    baseline_args=(--root "$ROOT")
    if [ "$APPLY" = true ]; then
        baseline_args+=(--apply)
    fi
    run_step "Migration-baseline existing raw files" \
        python3 "$PROJECT_DIR/scripts/system/wiki-baseline-raw-log.py" "${baseline_args[@]}"
else
    section "Migration-baseline existing raw files"
    say "status: skipped by --allow-reingest-existing"
    say "warning: future ingest may process the historical raw corpus"
fi

date_args=(--root "$ROOT")
if [ "$APPLY" = true ]; then
    date_args+=(--apply)
fi
run_step "Assign freshness dates" \
    python3 "$PROJECT_DIR/scripts/system/wiki-assign-dates.py" "${date_args[@]}"

index_args=(--wiki-dir "$ROOT/wiki")
if [ "$APPLY" = false ]; then
    index_args+=(--dry-run)
fi
run_step "Rebuild wiki indexes" \
    python3 "$PROJECT_DIR/scripts/system/wiki-create-index-pages.py" "${index_args[@]}"

if [ "$SKIP_QMD" = true ]; then
    section "QMD sync"
    say "status: skipped"
elif ! command -v qmd >/dev/null 2>&1; then
    section "QMD sync"
    say "status: skipped (qmd CLI not found)"
else
    qmd_args=(--root "$ROOT")
    if [ "$QMD_EMBED" = false ]; then
        qmd_args+=(--skip-embed)
    fi
    if [ "$APPLY" = true ]; then
        run_step "QMD sync" \
            bash "$PROJECT_DIR/scripts/system/qmd-sync-collections.sh" "${qmd_args[@]}"
    else
        section "QMD sync"
        say "status: dry-run would run qmd-sync-collections.sh $([ "$QMD_EMBED" = true ] || echo --skip-embed)"
    fi
fi

freshness_args=(--root "$ROOT" --limit "$LIMIT")
if [ "$APPLY" = false ]; then
    freshness_args+=(--no-write)
fi
run_step "Freshness/provenance queues" \
    bash "$PROJECT_DIR/scripts/wiki-freshness.sh" "${freshness_args[@]}"

section "Done"
if [ "$APPLY" = true ]; then
    say "Migration apply complete. Existing raw files were baselined unless --allow-reingest-existing was used."
else
    say "Dry-run complete. Re-run with --apply to write dates, indexes, freshness queues, and the migration raw baseline."
fi
write_report
