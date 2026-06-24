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
        --max-files-per-batch)
            [[ $# -ge 2 ]] || { echo "ERROR: --max-files-per-batch requires a value" >&2; exit 1; }
            MAX_FILES_PER_BATCH="$2"; shift 2 ;;
        --force)    FORCE=true; shift ;;
        --help|-h)  usage ;;
        *) echo "ERROR: Unknown argument: $1" >&2; echo "Run with --help for usage." >&2; exit 1 ;;
    esac
done

if ! [[ "$MAX_FILES_PER_BATCH" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: --max-files-per-batch must be a positive integer" >&2
    exit 1
fi

NOTES_DIR="raw"
LOG="wiki/log.jsonl"
IMPORT_DIR=".import"

shopt -s nullglob
existing_batches=( "$IMPORT_DIR"/batch-import-*.txt )
existing_logs=( "$IMPORT_DIR"/batch-log-*.jsonl )
shopt -u nullglob
has_batches=false
has_logs=false
[ ${#existing_batches[@]} -gt 0 ] && has_batches=true
[ ${#existing_logs[@]} -gt 0 ]    && has_logs=true

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

all_files=$(find "$NOTES_DIR" \( -name "*.md" -o -name "*.pdf" -o -name "*.doc" -o -name "*.docx" -o -name "*.txt" -o -name "*.vtt" -o -name "*.eml" -o -name "*.html" \) | \
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
        ts = st.st_mtime or getattr(st, 'st_birthtime', None) or st.st_ctime  # mtime wins; birthtime/ctime are fallbacks only
    except OSError:
        ts = 0
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
lines = sys.stdin.read().splitlines()
lines.sort(key=sort_key, reverse=True)
print('\n'.join(lines))
")

# Filter candidates: include if (a) not in log, or (b) mtime is newer than last import date
_py=$(mktemp /tmp/wiki-filter.XXXXXX.py)
_skip_meta=$(mktemp /tmp/wiki-skip.XXXXXX.json)
trap 'rm -f "$_py" "$_skip_meta"' EXIT
cat > "$_py" << 'PYEOF'
import sys, json, os, re, hashlib, urllib.parse

# Non-Markdown extensions that get moved into _resources/ and replaced by a
# companion .md (current layout), or converted to a converted/<stem>.md
# sibling (legacy layout). If agents fail to log the source file, we infer
# its state from the companion / converted entry.
_SOURCE_EXTS = {'.eml', '.html', '.vtt', '.pdf', '.doc', '.docx', '.txt'}
_DATE_PREFIX_RE = re.compile(r'^\d{4}-\d{2}-\d{2}')
_INGEST_FALSE_RE = re.compile(
    r'''^\s*ingest\s*:\s*(?:"false"|'false'|false)\s*(?:#.*)?$''',
    re.IGNORECASE,
)
_WIKILINK_RE = re.compile(r'!?\[\[((?:[^\]|\n\\]|\\(?!\|)|\](?!\]))+)')
_MDLINK_RE = re.compile(r'!?\[[^\]\n]*\]\(((?:[^()#\n]|\([^()\n]*\))+?)(?:#[^)]*)?\)')
_SOURCE_RE = re.compile(r'^\s*source\s*:\s*(.+?)\s*(?:#.*)?$')
_EXTERNAL_RE = re.compile(r'^[a-z][a-z0-9+.-]*:', re.IGNORECASE)


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

def _cur_mtime(fp):
    try:
        return int(os.stat(fp).st_mtime)
    except OSError:
        return None


def _content_hash(fp):
    try:
        h = hashlib.sha256()
        with open(fp, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                h.update(chunk)
        return 'sha256:' + h.hexdigest()
    except OSError:
        return None


def _frontmatter_lines(fp):
    try:
        with open(fp, encoding='utf-8', errors='replace') as f:
            first = f.readline()
            if first.strip() != '---':
                return []
            lines = []
            for line in f:
                if line.strip() in ('---', '...'):
                    return lines
                lines.append(line.rstrip('\n'))
    except OSError:
        pass
    return []


def _has_ingest_false(fp):
    if os.path.splitext(fp)[1].lower() != '.md':
        return False
    return any(_INGEST_FALSE_RE.match(line) for line in _frontmatter_lines(fp))


def _strip_target(target):
    target = target.strip()
    if not target:
        return ''
    if target.startswith('<') and target.endswith('>'):
        target = target[1:-1].strip()
    if (target.startswith('"') and target.endswith('"')) or (
        target.startswith("'") and target.endswith("'")
    ):
        target = target[1:-1].strip()
    target = urllib.parse.unquote(target).replace('\\', '/')
    if target.startswith('#'):
        return ''
    if _EXTERNAL_RE.match(target):
        return ''
    return target


def _link_targets(fp):
    try:
        text = open(fp, encoding='utf-8', errors='replace').read()
    except OSError:
        return []
    targets = []
    targets.extend(m.group(1) for m in _WIKILINK_RE.finditer(text))
    targets.extend(m.group(1) for m in _MDLINK_RE.finditer(text))
    for line in _frontmatter_lines(fp):
        m = _SOURCE_RE.match(line)
        if m:
            targets.append(m.group(1))
    return targets


def _norm_rel(path):
    return os.path.normpath(path).replace('\\', '/')


def _resolve_target(target, note_dir, candidate_set, basename_index):
    target = _strip_target(target)
    if not target:
        return set()

    variants = {target, target.split('#', 1)[0], target.split('?', 1)[0]}
    variants.add(target.split('#', 1)[0].split('?', 1)[0])
    raw_candidates = []
    for variant in sorted(v for v in variants if v):
        if os.path.isabs(variant):
            raw_candidates.append(_norm_rel(os.path.relpath(variant)))
        elif variant.startswith('raw/'):
            raw_candidates.append(_norm_rel(variant))
        else:
            raw_candidates.append(_norm_rel(os.path.join(note_dir, variant)))
            raw_candidates.append(_norm_rel(variant))
            if '/' not in variant:
                raw_candidates.extend(basename_index.get(os.path.basename(variant), []))

    resolved = set()
    for cand in raw_candidates:
        if cand.startswith('raw/') and cand in candidate_set:
            resolved.add(cand)
    return resolved


def _protected_paths(candidates):
    candidate_set = set(candidates)
    basename_index = {}
    for fp in candidates:
        basename_index.setdefault(os.path.basename(fp), set()).add(fp)

    protected = set()
    notes = []
    for fp in candidates:
        if not _has_ingest_false(fp):
            continue
        linked = set()
        note_dir = os.path.dirname(fp)
        for target in _link_targets(fp):
            linked.update(_resolve_target(target, note_dir, candidate_set, basename_index))
        linked.discard(fp)
        protected.add(fp)
        protected.update(linked)
        notes.append({
            'file': fp,
            'name': os.path.basename(fp),
            'linked_count': len(linked),
        })
    return protected, notes


meta_file = sys.argv[1]
log_files = sys.argv[2:]
files_db = set()
# Content identity added for rename/modify awareness:
#   mtime_db      : set of (logged_path, int_mtime) — fast path, skip without hashing
#   hashes_db     : set of all logged 'sha256:...' hashes — catches renames
#   stamped_paths : logged paths that carry a hash (so un-stamped legacy/pending
#                   entries keep the old "logged path = skip" behavior)
mtime_db = set()
hashes_db = set()
stamped_paths = set()
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
                    h = d.get('hash')
                    if isinstance(h, str) and h:
                        hashes_db.add(h)
                        stamped_paths.add(fp)
                    mt = d.get('mtime')
                    if isinstance(mt, int):
                        mtime_db.add((fp, mt))
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

candidates = [line.rstrip('\n') for line in sys.stdin if line.rstrip('\n')]
protected_paths, protected_notes = _protected_paths(candidates)
with open(meta_file, 'w', encoding='utf-8') as f:
    json.dump({
        'protected_notes': protected_notes,
        'skipped_total': len(protected_paths),
    }, f)

for fp in candidates:
    if not fp:
        continue
    if fp in protected_paths:
        continue
    # 1. Fast path: same path AND same mtime as a logged entry -> already
    #    ingested, no hashing needed.
    if (fp, _cur_mtime(fp)) in mtime_db:
        continue
    # 2. Content identity: same bytes as something already ingested (a rename,
    #    or a touch that left content unchanged) -> skip.
    h = _content_hash(fp)
    if h is not None and h in hashes_db:
        continue
    # 3. Logged path that has NO recorded hash yet (pre-hash legacy entry, or a
    #    pending batch-log entry the agent just wrote) -> preserve the old
    #    "logged path = already ingested" behavior. Stamped paths fall through
    #    so that a modified file (new content, no matching hash) re-ingests.
    if fp in files_db and fp not in stamped_paths:
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
filtered=$(echo "$all_files" | python3 "$_py" "$_skip_meta" ${log_sources[@]+"${log_sources[@]}"})
rm -f "$_py"

while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    remaining+=("$line")
done <<< "$filtered"

scanned=$(printf '%s\n' "$all_files" | grep -c . || true)
total=${#remaining[@]}
skipped_ingest_false=$(
    python3 -c 'import json, sys; print(len(json.load(open(sys.argv[1])).get("protected_notes", [])))' "$_skip_meta"
)
skipped_ingest_false_total=$(
    python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get("skipped_total", 0))' "$_skip_meta"
)
already_imported=$(( scanned - total - skipped_ingest_false_total ))
[[ $already_imported -lt 0 ]] && already_imported=0
num_batches=$(( (total + MAX_FILES_PER_BATCH - 1) / MAX_FILES_PER_BATCH ))
[[ $total -eq 0 ]] && num_batches=0

echo "wiki/log.jsonl    : $log_status"
echo "Files scanned     : $scanned"
echo "Already imported  : $already_imported"
if [[ $skipped_ingest_false -gt 0 ]]; then
    echo "Skipped (ingest:false): $skipped_ingest_false"
    python3 - "$_skip_meta" << 'PYEOF'
import json, sys
with open(sys.argv[1], encoding='utf-8') as f:
    data = json.load(f)
for note in data.get('protected_notes', []):
    linked = note.get('linked_count', 0)
    suffix = f" (+{linked} linked files)" if linked else ""
    print(f"  - {note.get('name', '')}{suffix}")
PYEOF
fi
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
