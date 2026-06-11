#!/usr/bin/env bash
# Partitions un-ingested notes into batch files for parallel import sessions.
#
# Usage:
#   bash scripts/wiki-create-import-batches.sh [--max-files-per-batch N] [--force] [--help]
#
# Options:
#   --max-files-per-batch N   Maximum number of files per batch (default: 10)
#   --force                   Remove existing batch/log files before running
#   --help                    Print this help and exit
#
# Output files:
#   .import/batch-import-1.txt, .import/batch-import-2.txt, …
#   Each file contains one file path per line.
#
# Exit codes:
#   0  Success (batches created)
#   1  Invalid argument
#   2  Existing batch or log files found (use --force to override)
#   3  Nothing to ingest (no new notes found)
#
# Machine-readable summary line (always last):
#   RESULT: total=<N> new=<N> already_imported=<N> batches=<N> max_files_per_batch=<N> status=<ready|empty>
set -euo pipefail

usage() {
    grep '^#' "$0" | grep -v '^#!/' | sed 's/^# \{0,1\}//'
    exit 0
}

MAX_FILES_PER_BATCH=10
FORCE=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --max-files-per-batch) MAX_FILES_PER_BATCH="$2"; shift 2 ;;
        --force)    FORCE=true; shift ;;
        --help|-h)  usage ;;
        *) echo "ERROR: Unknown argument: $1" >&2; echo "Run with --help for usage." >&2; exit 1 ;;
    esac
done

NOTES_DIR="raw"
LOG="wiki/log.jsonl"
IMPORT_DIR=".import"

existing_batches=( $IMPORT_DIR/batch-import-*.txt )
existing_logs=( $IMPORT_DIR/batch-log-*.jsonl )
has_batches=false
has_logs=false
[[ -e "${existing_batches[0]}" ]] && has_batches=true
[[ -e "${existing_logs[0]}" ]]   && has_logs=true

if $has_batches || $has_logs; then
    if ! $FORCE; then
        echo "ERROR: Existing files found:" >&2
        $has_batches && printf '  %s\n' "${existing_batches[@]}" >&2
        $has_logs    && printf '  %s\n' "${existing_logs[@]}"    >&2
        echo "" >&2
        echo "Execute /wiki:ingest-next-batch to continue processing and" >&2
        echo "execute /wiki:finalize-ingest when all batches are done." >&2
        echo "Or use the option --force to remove the files and continue." >&2
        exit 2
    fi
    $has_batches && rm -f "${existing_batches[@]}"
    $has_logs    && rm -f "${existing_logs[@]}"
fi

log_sources=()
if [[ -f "$LOG" ]]; then
    log_sources+=("$LOG")
    log_status="found"
else
    log_status="missing (no prior imports recorded)"
fi
shopt -s nullglob
batch_logs=( "$IMPORT_DIR"/batch-log-*.jsonl )
shopt -u nullglob
log_sources+=( ${batch_logs[@]+"${batch_logs[@]}"} )

all_files=$(find "$NOTES_DIR" \( -name "*.md" -o -name "*.pdf" -o -name "*.doc" -o -name "*.docx" -o -name "*.txt" -o -name "*.vtt" -o -name "*.eml" \) | \
    python3 -c "
import sys, os, re, datetime
# Matches YYYY, YYYY-MM, or YYYY-MM-DD at the start of a path component,
# followed by a non-digit separator (space, underscore, hyphen, dot) or end of string.
DATE_RE = re.compile(r'^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?(?=[\s_\-.]|$)')
def sort_key(f):
    # Walk path components from leaf (basename) to root.
    # Use the first dated component found, so files inside e.g. '2014-06-01_Foo.resources/'
    # inherit that parent's date when their own basename has none.
    for part in reversed(f.split(os.sep)):
        m = DATE_RE.match(part)
        if m:
            year  = m.group(1)
            month = m.group(2) or '12'
            day   = m.group(3) or '31'
            return f'{year}-{month}-{day}T23:59:59'
    try:
        st = os.stat(f)
        ts = st.st_mtime or getattr(st, 'st_birthtime', None) or st.st_ctime
    except OSError:
        ts = 0
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
lines = sys.stdin.read().splitlines()
lines.sort(key=sort_key, reverse=True)
print('\n'.join(lines))
")

# Filter candidates: include if (a) not in log, or (b) mtime is newer than last import date
_py=$(mktemp /tmp/wiki-filter.XXXXXX.py)
cat > "$_py" << 'PYEOF'
import sys, json, os, re

# Non-Markdown extensions that get moved into _resources/ and replaced by a
# companion .md (current layout), or converted to a converted/<stem>.md
# sibling (legacy layout). If agents fail to log the source file, we infer
# its state from the companion / converted entry.
_SOURCE_EXTS = {'.eml', '.vtt', '.pdf', '.doc', '.docx', '.txt'}
_DATE_PREFIX_RE = re.compile(r'^\d{4}-\d{2}-\d{2}')


def _is_companion_for(md_path, src_name):
    """True if md_path is a companion .md whose `source:` references src_name."""
    try:
        with open(md_path, encoding='utf-8', errors='replace') as f:
            for i, line in enumerate(f):
                if i > 20:
                    break
                if line.startswith('source:') and src_name in line:
                    return True
    except OSError:
        pass
    return False


def _has_companion(fp):
    """True if a companion .md exists for non-Markdown source file fp.

    The companion lives in the directory above _resources/ (or fp's own
    directory when fp has not been moved yet), named <stem>.md or <name>.md.
    """
    parent = os.path.dirname(fp)
    base = os.path.dirname(parent) if os.path.basename(parent) == '_resources' else parent
    name = os.path.basename(fp)
    stem = os.path.splitext(name)[0]
    for cand in (os.path.join(base, stem + '.md'), os.path.join(base, name + '.md')):
        if os.path.isfile(cand) and _is_companion_for(cand, name):
            return True
    return False

log_files = sys.argv[1:]
files_db = set()
# (grandparent_dir, date_prefix) pairs seen in logged converted/*.md entries.
# Allows matching source files even when sanitization changed the stem slightly.
converted_date_db = set()

for logfile in log_files:
    if not os.path.isfile(logfile):
        continue
    try:
        with open(logfile) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    fp = d.get('file', '')
                    if not fp:
                        continue
                    files_db.add(fp)
                    # If this is a converted/<stem>.md, record (grandparent, date_prefix)
                    # so we can skip the source .eml/.vtt/etc. even when only the .md was logged.
                    if fp.endswith('.md') and os.path.basename(os.path.dirname(fp)) == 'converted':
                        stem = os.path.splitext(os.path.basename(fp))[0]
                        m = _DATE_PREFIX_RE.match(stem)
                        if m:
                            grandparent = os.path.dirname(os.path.dirname(fp))
                            converted_date_db.add((grandparent, m.group(0)))
                except Exception:
                    pass
    except Exception:
        pass

for line in sys.stdin:
    fp = line.rstrip('\n')
    if not fp:
        continue
    if fp in files_db:
        continue
    ext = os.path.splitext(fp)[1].lower()
    if ext in _SOURCE_EXTS:
        # Skip non-Markdown sources that already have a companion .md — the
        # companion is what gets ingested (and its log entry covers the source).
        if _has_companion(fp):
            continue
        # Legacy layout: for date-prefixed names, also check whether the
        # corresponding converted/.md was logged (agents sometimes omitted
        # the source entry).
        stem = os.path.splitext(os.path.basename(fp))[0]
        m = _DATE_PREFIX_RE.match(stem)
        if m:
            parent = os.path.dirname(fp)
            if (parent, m.group(0)) in converted_date_db:
                continue
    print(fp)
PYEOF

remaining=()
# Always run the filter: even without log files it skips non-Markdown sources
# that already have a companion .md.
filtered=$(echo "$all_files" | python3 "$_py" ${log_sources[@]+"${log_sources[@]}"})
rm -f "$_py"

while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    remaining+=("$line")
done <<< "$filtered"

scanned=$(printf '%s\n' "$all_files" | grep -c . || true)
total=${#remaining[@]}
already_imported=$(( scanned - total ))
num_batches=$(( (total + MAX_FILES_PER_BATCH - 1) / MAX_FILES_PER_BATCH ))
[[ $total -eq 0 ]] && num_batches=0

echo "wiki/log.jsonl    : $log_status"
echo "Files scanned     : $scanned"
echo "Already imported  : $already_imported"
echo "New (un-ingested) : $total"
echo "Max files/batch   : $MAX_FILES_PER_BATCH (--max-files-per-batch)"
echo "Batches to create : $num_batches"

if [[ $total -eq 0 ]]; then
    echo "Nothing to ingest."
    echo "RESULT: total=0 new=0 already_imported=$already_imported batches=0 max_files_per_batch=$MAX_FILES_PER_BATCH status=empty"
    exit 3
fi

mkdir -p "$IMPORT_DIR"

echo ""
for idx in "${!remaining[@]}"; do
    batch=$(( idx / MAX_FILES_PER_BATCH + 1 ))
    echo "${remaining[$idx]}" >> "$IMPORT_DIR/batch-import-$batch.txt"
    printf "\r  Writing batch files... %d / %d files" $(( idx + 1 )) "$total" >&2
done
printf "\r  Writing batch files... done (%d files in %d batches)\n" "$total" "$num_batches"

echo ""
echo "RESULT: total=$total new=$total already_imported=$already_imported batches=$num_batches max_files_per_batch=$MAX_FILES_PER_BATCH status=ready"
