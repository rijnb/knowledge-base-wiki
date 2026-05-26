#!/usr/bin/env bash
# Autonomous wiki ingestion pipeline:
#   0. Convert raw files to Markdown (VTT transcripts, EML emails).
#   1. If no batch-import files exist, run scripts/wiki-create-import-batches.sh
#      directly to partition new notes. If the script exits with code 3
#      ("nothing to ingest"), the pipeline stops cleanly with exit 0 — no
#      LLM calls are made and no finalization is run.
#   2. Loop /wiki-ingest-next-batch until all batches are consumed.
#   3. Run /wiki-finalize-ingest to wrap up.
#
# Pauses 30 minutes whenever the 5-hour Claude usage is at or above the
# threshold, then retries automatically. Usage tracking is Claude-only;
# for --agent junie, get_usage always returns 0 so the
# throttling loop is effectively disabled.
#
# The 5-hour usage percentage is fetched from the Anthropic API using the
# OAuth token stored in the macOS Keychain (Claude Code-credentials).
# Falls back to the HUD usage cache (~/.claude/plugins/claude-hud/.usage-cache.json)
# if the API is unreachable.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HUD_CACHE="$HOME/.claude/plugins/claude-hud/.usage-cache.json"
CACHE_TTL_SECONDS=120
THRESHOLD=85
WAIT_SECS=1800
MAX_ERRORS=5
MAX_BATCHES=50
MAX_BATCHES_EXPLICIT=false
MAX_FILES_PER_BATCH=""
WAIT_BETWEEN_BATCHES=60
ERROR_COUNT=0
CURRENT_BATCH=0
AGENT=claude
DRY_RUN=false

check_dependencies() {
    local missing=()

    command -v python3 &>/dev/null || \
        missing+=("python3  →  brew install python3      (or https://www.python.org/downloads/)")
    command -v curl &>/dev/null || \
        missing+=("curl     →  brew install curl")

    case "$AGENT" in
        claude)
            command -v claude &>/dev/null || \
                missing+=("claude   →  npm install -g @anthropic-ai/claude-code  (or https://claude.ai/code)")
            command -v jq &>/dev/null || \
                missing+=("jq       →  brew install jq")
            ;;
        junie)
            command -v junie &>/dev/null || \
                missing+=("junie    →  install from JetBrains: https://www.jetbrains.com/junie/")
            ;;
    esac

    if [ "${#missing[@]}" -gt 0 ]; then
        echo "" >&2
        echo "ERROR: The following required tool(s) are not installed:" >&2
        for item in "${missing[@]}"; do
            echo "  • $item" >&2
        done
        echo "" >&2
        exit 1
    fi
}

usage() {
    cat <<EOF
Usage: $(basename "$0") [--agent AGENT] [--threshold N] [--max-errors N] [--max-batches N] [--max-files-per-batch N] [--wait-between-batches N] [--dry-run] [--help]

Autonomous wiki ingestion pipeline. Runs /wiki-ingest (if needed), then loops
/wiki-ingest-next-batch until all batches are done, then finalizes. Pauses
30 minutes whenever the 5-hour Claude usage is at or above the threshold.
Throttling applies only to --agent claude; for junie, usage is reported as
0% (no throttling) since junie doesn't expose a quota API.

Options:
  --agent AGENT              LLM agent command to use (default: claude).
                             Allowed values: claude (Anthropic Claude),
                                             junie  (JetBrains Junie).
  --threshold N              Usage percentage ceiling (default: 85). Each phase starts only
                             when current usage is strictly below this value.
  --max-errors N             Maximum number of LLM agent command errors before the script
                             exits (default: 5). Each error pauses for confirmation first.
  --max-batches N            Maximum number of batches to process (default: 50).
                             The script exits cleanly after this many batches.
  --max-files-per-batch N    Maximum number of files per batch (default: 10 for claude,
                             3 for junie). Passed to wiki-create-import-batches.sh when
                             partitioning notes.
  --wait-between-batches N   Seconds to wait between batches (default: 60). The countdown
                             can be skipped with Enter or cancelled with ESC.
  --dry-run                  Show what would be done without making any changes. No files
                             are converted, no LLM calls are made, and no notes are ingested.
  --help                     Show this help and exit.

Data sources (in order of preference):
  1. Anthropic API  https://api.anthropic.com/api/oauth/usage  (OAuth token
                    read from macOS Keychain: "Claude Code-credentials")
  2. HUD cache      ~/.claude/plugins/claude-hud/.usage-cache.json
                    (used when API is unreachable; max age: ${CACHE_TTL_SECONDS}s)

Exit codes:
  0  Full pipeline complete (ingest → batches → finalize), or cleanly
     paused at --max-batches limit (not all batches consumed; finalize skipped).
  1  Interrupted or unexpected error.
EOF
}

# Parse flags
while [[ $# -gt 0 ]]; do
    case "$1" in
        --agent)
            case "$2" in
                claude|junie) AGENT="$2" ;;
                *) echo "Unknown agent: $2 (allowed: claude, junie)" >&2; usage >&2; exit 1 ;;
            esac
            shift 2 ;;
        --threshold)
            [[ "$2" =~ ^[0-9]+$ ]] || { echo "--threshold must be a non-negative integer" >&2; exit 1; }
            THRESHOLD="$2"; shift 2 ;;
        --max-errors)
            [[ "$2" =~ ^[0-9]+$ ]] || { echo "--max-errors must be a non-negative integer" >&2; exit 1; }
            MAX_ERRORS="$2"; shift 2 ;;
        --max-batches)
            [[ "$2" =~ ^[0-9]+$ ]] || { echo "--max-batches must be a non-negative integer" >&2; exit 1; }
            MAX_BATCHES="$2"; MAX_BATCHES_EXPLICIT=true; shift 2 ;;
        --max-files-per-batch)
            [[ "$2" =~ ^[0-9]+$ ]] || { echo "--max-files-per-batch must be a non-negative integer" >&2; exit 1; }
            MAX_FILES_PER_BATCH="$2"; shift 2 ;;
        --wait-between-batches)
            [[ "$2" =~ ^[0-9]+$ ]] || { echo "--wait-between-batches must be a non-negative integer" >&2; exit 1; }
            WAIT_BETWEEN_BATCHES="$2"; shift 2 ;;
        --dry-run)             DRY_RUN=true; shift ;;
        --help|-h)             usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
done

# Apply agent-specific defaults for options not explicitly set by the user.
if [ "$AGENT" = "junie" ]; then
    MAX_FILES_PER_BATCH=${MAX_FILES_PER_BATCH:-3}
else
    MAX_FILES_PER_BATCH=${MAX_FILES_PER_BATCH:-10}
fi

check_dependencies

# Warn when Junie is selected: the integration is experimental and untested.
if [ "$AGENT" = "junie" ]; then
    echo ""
    echo "────────────────────────────────────────────────────────────────────"
    echo "⚠️  WARNING: --agent junie is currently EXPERIMENTAL and has not been fully"
    echo "            tested. Behaviour may be unreliable or produce unexpected results."
    echo "────────────────────────────────────────────────────────────────────"
    echo ""
    echo -n "Press Enter to continue, or Ctrl-C to abort... "
    read -r _junie_confirm
    echo ""
fi

# Fetch utilization % from Anthropic API using the keychain OAuth token.
# Prints an integer 0-100 on success, or returns non-zero on failure.
fetch_from_api() {
    local keychain_json
    keychain_json=$(/usr/bin/security find-generic-password \
        -s "Claude Code-credentials" -w 2>/dev/null) || return 1

    local access_token
    access_token=$(echo "$keychain_json" | python3 -c "
import json, sys
d = json.load(sys.stdin)
token = d.get('claudeAiOauth', {}).get('accessToken', '')
if not token:
    raise SystemExit(1)
print(token)
") || return 1

    local response
    response=$(curl -sf --max-time 8 \
        -H "Authorization: Bearer $access_token" \
        -H "anthropic-beta: oauth-2025-04-20" \
        "https://api.anthropic.com/api/oauth/usage") || return 1

    echo "$response" | python3 -c "
import json, sys
d = json.load(sys.stdin)
util = d.get('five_hour', {}).get('utilization')
if util is None:
    raise SystemExit(1)
print(round(max(0, min(100, float(util)))))
"
}

# Read utilization % from the HUD file cache if fresh enough.
# Prints an integer 0-100 on success, or returns non-zero if stale/missing.
read_from_cache() {
    [ -f "$HUD_CACHE" ] || return 1
    HUD_CACHE_PATH="$HUD_CACHE" python3 -c "
import json, time, os
d = json.load(open(os.environ['HUD_CACHE_PATH']))
age_sec = (time.time() * 1000 - d['timestamp']) / 1000
if age_sec > $CACHE_TTL_SECONDS:
    raise SystemExit(1)
v = d.get('data', {}).get('fiveHour')
if v is None:
    raise SystemExit(1)
print(int(v))
"
}

# Resolve current 5-hour usage % for Claude, preferring a fresh API call.
# Returns non-zero (and prints nothing) if usage cannot be determined.
# Not applicable to Junie — callers must skip throttling for non-Claude agents.
get_usage() {
    local pct
    if pct=$(fetch_from_api 2>/dev/null); then
        echo "$pct"
        return 0
    fi
    echo "API unavailable, checking cache..." >&2
    if pct=$(read_from_cache 2>/dev/null); then
        echo "$pct"
        return 0
    fi
    return 1
}

# Print the clock time WAIT_SECS from now.
next_attempt_time() {
    date -v +${WAIT_SECS}S '+%H:%M' 2>/dev/null \
        || date -d "+${WAIT_SECS} seconds" '+%H:%M' 2>/dev/null \
        || echo "in 30 minutes"
}

# Block until 5-hour usage is below THRESHOLD.
# Prints the usage percentage to stdout once cleared; all other output to stderr.
# For non-Claude agents, usage cannot be retrieved — throttling is skipped entirely.
wait_for_capacity() {
    local context="$1"

    if [ "$AGENT" != "claude" ]; then
        echo "Usage throttling not available for agent '$AGENT' — skipping check." >&2
        return 0
    fi

    while true; do
        local pct
        if ! pct=$(get_usage); then
            echo "Could not retrieve usage data ($context) — continuing anyway." >&2
            return 0
        fi
        echo "5-hour usage: ${pct}%  (threshold: ${THRESHOLD}%)" >&2
        if [ "$pct" -lt "$THRESHOLD" ]; then
            echo "$pct"
            return 0
        fi
        echo "At or above ${THRESHOLD}% — waiting 30 minutes ($context). Next attempt at $(next_attempt_time)." >&2
        sleep "$WAIT_SECS"
    done
}

# Wait up to TIMEOUT seconds, allowing ESC to cancel or Enter to continue immediately.
# $1 = timeout in seconds; $2 = label (e.g. "next batch" or "finalize the ingest")
# Returns 0 to continue, 1 if the user pressed ESC.
wait_with_cancel() {
    local timeout="$1"
    local label="${2:-next batch}"

    [ -t 0 ] || { sleep "$timeout"; return 0; }

    local saved_tty
    saved_tty=$(stty -g 2>/dev/null) || { sleep "$timeout"; return 0; }
    stty -echo 2>/dev/null

    # Flush any characters buffered in stdin while the LLM was running
    # (e.g. accidental Enter presses), so they don't trigger instant continuation.
    while IFS= read -r -s -n 1 -t 0 _flush_ch 2>/dev/null; do :; done

    printf "\n  Pausing %ds before %s — press Enter to continue now, ESC to stop.\n" "$timeout" "$label"

    local elapsed=0
    local cancelled=false

    while [ "$elapsed" -lt "$timeout" ]; do
        local remaining=$(( timeout - elapsed ))
        printf "\r  Continuing in %2ds  (Enter = now, ESC = skip to finalize)" "$remaining"

        local ch
        IFS= read -r -s -n 1 -t 1 ch 2>/dev/null
        local read_rc=$?

        if [ "$read_rc" -ne 0 ]; then
            # Timed out — no key was pressed, just advance the clock
            elapsed=$(( elapsed + 1 ))
            continue
        fi

        if [[ "$ch" == $'\x1b' ]]; then
            cancelled=true
            break
        elif [[ "$ch" == '' || "$ch" == $'\n' || "$ch" == $'\r' ]]; then
            break
        fi

        elapsed=$(( elapsed + 1 ))
    done

    stty "$saved_tty" 2>/dev/null
    printf "\r%80s\r\n" ""

    if [ "$cancelled" = true ]; then
        echo "  Loop stopped by user (ESC)."
        return 1
    fi
    return 0
}

# Format an elapsed-seconds value as "X seconds" or "X minutes and Y seconds".
format_duration() {
    local secs="$1"
    if [ "$secs" -lt 60 ]; then
        echo "${secs} seconds"
    else
        local m=$(( secs / 60 ))
        local s=$(( secs % 60 ))
        if [ "$s" -eq 0 ]; then
            echo "${m} minutes"
        else
            echo "${m} minutes and ${s} seconds"
        fi
    fi
}

# Count unclaimed batch-import-*.txt files.
count_batch_files() {
    local -a files
    shopt -s nullglob
    files=("$PROJECT_DIR/.import"/batch-import-*.txt)
    shopt -u nullglob
    echo "${#files[@]}"
}

# Count batch-log-*.jsonl files (present when all batches consumed but not yet finalized).
count_batch_log_files() {
    local -a files
    shopt -s nullglob
    files=("$PROJECT_DIR/.import"/batch-log-*.jsonl)
    shopt -u nullglob
    echo "${#files[@]}"
}

# Return the numeric suffix of the lowest-numbered batch file, or "" if none.
get_first_batch_number() {
    local first
    first=$(ls "$PROJECT_DIR/.import"/batch-import-*.txt 2>/dev/null | sort -V | head -1) || true
    [ -z "$first" ] && return 0
    basename "$first" | grep -oE '[0-9]+' | head -1
}

# Invoke the selected LLM agent with a slash-command prompt.
# Usage: run_llm "<slash-command>"
run_llm() {
    local prompt="$1"
    case "$AGENT" in
        claude) claude --dangerously-skip-permissions --output-format stream-json --verbose \
            --include-partial-messages --print "$prompt" \
            | jq -rj '
              if .type == "stream_event" then
                if .event.delta.type? == "text_delta" then
                  .event.delta.text
                elif .event.type? == "content_block_start" and .event.content_block.type? == "tool_use" then
                  "\n⚙ \(.event.content_block.name)…\n"
                elif .event.type? == "message_stop" then
                  "\n"
                else empty
                end
              else empty
              end
            ' ;;
        junie)  junie --brave --skip-update-check --output-format=text --task "$prompt" ;;
    esac
}

show_plan() {
    local needs_ingest="$1"
    local batch_count="$2"
    local first_batch_num="${3:-}"

    echo ""
    if [ "$DRY_RUN" = true ]; then
        echo "=== Wiki Ingest Pipeline  [DRY-RUN — no changes will be made] ==="
    else
        echo "=== Wiki Ingest Pipeline ==="
    fi
    echo ""
    printf "LLM agent: %s\n" "$AGENT"
    echo ""
    echo "────────────────────────────────────────────────────────────────────"
    case "$AGENT" in
        claude)
            cat <<'BANNER'
    ██████╗ ██╗      █████╗ ██╗   ██╗ ██████╗ ███████╗
   ██╔════╝ ██║     ██╔══██╗██║   ██║ ██╔══██╗██╔════╝
   ██║      ██║     ███████║██║   ██║ ██║  ██║█████╗
   ██║      ██║     ██╔══██║██║   ██║ ██║  ██║██╔══╝
   ╚██████╗ ███████╗██║  ██║╚██████╔╝ ██████╔╝███████╗
    ╚═════╝ ╚══════╝╚═╝  ╚═╝ ╚═════╝  ╚═════╝ ╚══════╝
BANNER
            ;;
        junie)
            cat <<'BANNER'
        ██╗ ██╗   ██╗ ███╗   ██╗ ██╗ ███████╗
        ██║ ██║   ██║ ████╗  ██║ ██║ ██╔════╝
        ██║ ██║   ██║ ██╔██╗ ██║ ██║ █████╗
   ██   ██║ ██║   ██║ ██║╚██╗██║ ██║ ██╔══╝
   ╚█████╔╝ ╚██████╔╝ ██║ ╚████║ ██║ ███████╗
    ╚════╝   ╚═════╝  ╚═╝  ╚═══╝ ╚═╝ ╚══════╝
BANNER
            ;;
    esac
    echo "────────────────────────────────────────────────────────────────────"
    echo ""

    if [ "$needs_ingest" = true ]; then
        echo "  ► FRESH INGEST — starting from scratch"
        echo ""
        echo "  Phase 0  convert raw files         (VTT transcripts → MD, EML/HTML emails → MD)"
        echo "  Phase 1  partition new notes       (wiki-create-import-batches.sh — may exit early if nothing to ingest)"
        echo "  Phase 2  /wiki-ingest-next-batch   (batch count determined after phase 1)"
    else
        if [ -n "$first_batch_num" ]; then
            printf "  ► CONTINUING EXISTING INGEST — resuming from batch %s  (%s batch(es) remaining)\n" \
                "$first_batch_num" "$batch_count"
        else
            printf "  ► CONTINUING EXISTING INGEST — %s batch(es) remaining\n" "$batch_count"
        fi
        echo ""
        echo "  Phase 1  partition new notes       (skipped — ${batch_count} batch file(s) already exist)"
        echo "  Phase 2  /wiki-ingest-next-batch   ${batch_count} batch(es)"
    fi

    echo "  Phase 3  /wiki-finalize-ingest"
    echo ""
    printf "Pauses 30 min if 5-hour usage ≥ %s%%.\n" "$THRESHOLD"
    printf "Max batches: %s  |  Max errors: %s  |  Max files/batch: %s  |  Wait between batches: %ss\n" "$MAX_BATCHES" "$MAX_ERRORS" "$MAX_FILES_PER_BATCH" "$WAIT_BETWEEN_BATCHES"
    echo ""
}

# Prompt Y/n with Enter=Yes, Escape=No.
# Auto-advances to Yes after 60 seconds, showing a live countdown.
# Returns 0 to continue, 1 if the user declined.
confirm_yn() {
    local prompt="${1:-Continue?}"
    local timeout=60

    [ -t 0 ] || return 0   # non-interactive: default Yes

    local saved_tty
    saved_tty=$(stty -g 2>/dev/null) || { return 0; }
    stty -echo -icanon min 1 time 0 2>/dev/null

    local elapsed=0 result=0 decided=false

    while [ "$elapsed" -le "$timeout" ]; do
        local remaining=$(( timeout - elapsed ))
        printf "\r%s [Y/n] (continuing in %2ds) " "$prompt" "$remaining"

        local ch
        if IFS= read -r -s -n 1 -t 1 ch 2>/dev/null; then
            # A key was pressed
            case "$ch" in
                ''|$'\n'|$'\r'|y|Y)   # Enter or Y → Yes
                    printf "\r%s [Y/n] Yes%-30s\n" "$prompt" ""
                    result=0; decided=true
                    break
                    ;;
                n|N)
                    printf "\r%s [Y/n] No%-30s\n" "$prompt" ""
                    result=1; decided=true
                    break
                    ;;
                $'\x1b')              # Escape → No
                    printf "\r%s [Y/n] No%-30s\n" "$prompt" ""
                    result=1; decided=true
                    break
                    ;;
            esac
        fi
        # Timed out waiting for a key (or unrecognised key) — advance counter
        elapsed=$(( elapsed + 1 ))
    done

    if [ "$decided" = false ]; then
        printf "\r%s [Y/n] Yes (auto-advanced after %ds)%-10s\n" "$prompt" "$timeout" ""
        result=0
    fi

    stty "$saved_tty" 2>/dev/null
    return "$result"
}

confirm_or_exit() {
    printf "Agent: %s\n" "$AGENT"
    if ! confirm_yn "Start the wiki ingest pipeline?"; then
        echo "Stopped."
        exit 0
    fi
}

# Prompt to continue after an error; also enforces MAX_ERRORS limit.
confirm_after_error() {
    local context="$1"
    ERROR_COUNT=$(( ERROR_COUNT + 1 ))
    echo "  [Error $ERROR_COUNT of $MAX_ERRORS allowed]"
    if [ "$ERROR_COUNT" -ge "$MAX_ERRORS" ]; then
        echo ""
        echo "ERROR: Maximum error count ($MAX_ERRORS) reached after: $context" >&2
        echo "Exiting. Inspect $PROJECT_DIR/.import/ for current state." >&2
        exit 1
    fi
    if ! confirm_yn "Error in $context — continue anyway?"; then
        echo "Stopped by user after error."
        exit 1
    fi
}

ND_NOTHING_TO_INGEST=3

# Rename files in raw/ whose names contain characters that break shell scripts,
# Python path handling, or Markdown link syntax. Runs before any conversion.
sanitize_raw_filenames() {
    echo "Sanitizing raw/ filenames..."
    local raw_dir="$PROJECT_DIR/raw"
    python3 - "$raw_dir" << 'PYEOF'
import os, sys

raw_dir = sys.argv[1]
BAD = set([
    "'", '"',
    '!', '#', '$', '%', '&', '*', '<', '>', '?', '/', '\\', '|',
])

def sanitize_char(c):
    if c in BAD:
        return '_'
    if ord(c) > 127:  # any non-ASCII (including curly quotes, accented letters, etc.)
        return '_'
    return c

def strip_whitespace_before_ext(fname):
    # "foo .txt" -> "foo.txt"; "foo  .tar.gz" -> "foo.tar.gz"
    stem, dot, ext = fname.rpartition('.')
    if not dot:
        return fname
    return stem.rstrip() + dot + ext

count = 0
for dirpath, dirnames, filenames in os.walk(raw_dir, topdown=False):
    for fname in filenames:
        new_fname = ''.join(sanitize_char(c) for c in fname)
        new_fname = strip_whitespace_before_ext(new_fname)
        if new_fname != fname:
            old_path = os.path.join(dirpath, fname)
            new_path = os.path.join(dirpath, new_fname)
            os.rename(old_path, new_path)
            print(f'  Renamed: {fname} -> {new_fname}')
            count += 1

print(f'Sanitized {count} filename(s).')
PYEOF
}

# Convert raw VTT and EML files to Markdown before partitioning.
# Errors are non-fatal: a failed conversion is reported but the pipeline continues.
run_phase_convert() {
    echo "=== Phase 0 - CONVERT RAW FILES: converting raw files to Markdown ==="
    local scripts_dir="$PROJECT_DIR/scripts"
    local had_error=false

    set +e
    sanitize_raw_filenames
    local san_rc=$?
    set -e
    [ "$san_rc" -ne 0 ] && { echo "WARN: filename sanitization exited with status $san_rc" >&2; had_error=true; }
    echo ""

    echo "Converting VTT transcripts..."
    set +e
    python3 "$scripts_dir/system/convert-vtt-to-md.py" \
        --input-dir  "$PROJECT_DIR/raw/transcripts" \
        --output-dir "$PROJECT_DIR/raw/transcripts/converted"
    local vtt_rc=$?
    set -e
    [ "$vtt_rc" -ne 0 ] && { echo "WARN: convert-vtt-to-md.py exited with status $vtt_rc" >&2; had_error=true; }

    echo "Converting EML emails..."
    set +e
    python3 "$scripts_dir/system/convert-eml-to-md.py" \
        --input-dir  "$PROJECT_DIR/raw/emails" \
        --output-dir "$PROJECT_DIR/raw/emails/converted"
    local eml_rc=$?
    set -e
    [ "$eml_rc" -ne 0 ] && { echo "WARN: convert-eml-to-md.py exited with status $eml_rc" >&2; had_error=true; }

    echo "Converting HTML emails..."
    set +e
    python3 "$scripts_dir/system/convert-html-to-md.py" \
        --input-dir  "$PROJECT_DIR/raw/emails" \
        --output-dir "$PROJECT_DIR/raw/emails/converted"
    local html_rc=$?
    set -e
    [ "$html_rc" -ne 0 ] && { echo "WARN: convert-html-to-md.py exited with status $html_rc" >&2; had_error=true; }

    echo ""
    if [ "$had_error" = true ]; then
        echo "Conversion finished with warnings.  Time: $(date '+%H:%M:%S')"
    else
        echo "Conversion complete.  Time: $(date '+%H:%M:%S')"
    fi
}

# Run the partition script directly so we can react to its exit code,
# in particular code 3 ("nothing to ingest") — which lets us skip the
# LLM call entirely instead of paying for an /wiki-ingest round-trip.
#
# Returns:
#   0  Batches were created. Caller should proceed to Phase 2.
#   3  Nothing to ingest. Caller should stop the pipeline cleanly.
#   *  Anything else is treated as a fatal error and aborts the script.
run_phase_partition() {
    echo "=== Phase 1 - PARTITION: partitioning new notes into batches ==="
    echo "Running scripts/system/wiki-create-import-batches.sh..."
    set +e
    bash "$PROJECT_DIR/scripts/system/wiki-create-import-batches.sh" --max-files-per-batch "$MAX_FILES_PER_BATCH"
    local rc=$?
    set -e

    case "$rc" in
        0)
            echo ""
            echo "Partitioning complete.  Time: $(date '+%H:%M:%S')"
            return 0
            ;;
        "$ND_NOTHING_TO_INGEST")
            return "$ND_NOTHING_TO_INGEST"
            ;;
        *)
            echo "ERROR: wiki-create-import-batches.sh exited with status $rc.  Time: $(date '+%H:%M:%S')" >&2
            exit 1
            ;;
    esac
}

run_phase_batches() {
    local total="$1"
    local iteration=0
    local stopped_early=false
    local effective_total=$(( total < MAX_BATCHES ? total : MAX_BATCHES ))

    while compgen -G "$PROJECT_DIR/.import/batch-import-*.txt" > /dev/null 2>&1; do
        iteration=$(( iteration + 1 ))
        CURRENT_BATCH=$(( CURRENT_BATCH + 1 ))

        if [ "$iteration" -gt "$total" ]; then
            echo "WARN: Processed $iteration batches but only $total were expected." >&2
            echo "      A claimed batch file in '.import/' may not have been removed." >&2
            echo "      Stopping loop to avoid infinite loop." >&2
            stopped_early=true
            break
        fi

        local remaining
        remaining=$(count_batch_files)
        echo ""
        if [ "$MAX_BATCHES_EXPLICIT" = true ]; then
            echo "=== Phase 2 - INGEST BATCHES: batch $CURRENT_BATCH of $effective_total  ($remaining total batches remaining) ==="
        else
            echo "=== Phase 2 - INGEST BATCHES: batch $iteration of $total  ($remaining remaining, loop $CURRENT_BATCH/$effective_total) ==="
        fi

        local usage_before
        usage_before=$(wait_for_capacity "before batch $iteration of $total")

        echo "Starting /wiki-ingest-next-batch..."
        if [ "$AGENT" = "claude" ]; then
            echo "(Claude may be silent for a long time and only show output after it's done... patience...)"
        fi
        local batch_start_ts
        batch_start_ts=$(date +%s)
        if ! run_llm "/wiki-ingest-next-batch"; then
            echo ""
            echo "────────────────────────────────────────────────────────────────────"
            echo "ERROR: /wiki-ingest-next-batch failed on batch $iteration.  Current time: $(date '+%H:%M:%S')" >&2
            echo "       Check $PROJECT_DIR/.import/ for current state." >&2
            echo "────────────────────────────────────────────────────────────────────"
            confirm_after_error "/wiki-ingest-next-batch (batch $iteration)"
        fi

        echo ""
        echo "────────────────────────────────────────────────────────────────────"
        local batch_label
        if [ "$MAX_BATCHES_EXPLICIT" = true ]; then
            local remaining_after_label
            remaining_after_label=$(count_batch_files)
            batch_label="batch $CURRENT_BATCH of $effective_total ($remaining_after_label total batches remaining)"
        else
            batch_label="batch $iteration of $total"
        fi
        local batch_elapsed
        batch_elapsed=$(( $(date +%s) - batch_start_ts ))
        local batch_duration
        batch_duration=$(format_duration "$batch_elapsed")
        if [ "$AGENT" = "claude" ]; then
            local usage_after
            if usage_after=$(get_usage 2>/dev/null); then
                local delta=$(( usage_after - usage_before ))
                local sign=""; [ "$delta" -ge 0 ] && sign="+"
                echo "Completed $batch_label in $batch_duration.  5-hour usage: ${usage_after}%  (${sign}${delta}%)  Current time: $(date '+%H:%M:%S')"
            else
                echo "Completed $batch_label in $batch_duration.  Current time: $(date '+%H:%M:%S')"
            fi
        else
            echo "Completed $batch_label in $batch_duration.  Current time: $(date '+%H:%M:%S')"
        fi

        local remaining_after
        remaining_after=$(count_batch_files)
        local wait_label
        if [ "$remaining_after" -eq 0 ]; then
            wait_label="finalize the ingest"
        else
            wait_label="next batch"
        fi

        # Skip the inter-batch pause if the next iteration would immediately hit
        # the max-batches limit — no point waiting only to exit right away.
        if [ "$CURRENT_BATCH" -ge "$MAX_BATCHES" ] && [ "$remaining_after" -gt 0 ]; then
            echo "INFO: Max batches ($MAX_BATCHES) reached — stopping without waiting."
            return 2
        fi

        if ! wait_with_cancel "$WAIT_BETWEEN_BATCHES" "$wait_label"; then
            stopped_early=true
            break
        fi
    done

    echo ""
    if [ "$stopped_early" = true ]; then
        echo "$iteration batch(es) processed; remaining batches skipped by user."
        return 2
    else
        echo "All $iteration batch(es) consumed."
    fi
}

run_phase_finalize() {
    echo ""
    echo "=== Phase 3 - FINALIZE: consolidate logs and created indexes ==="
    wait_for_capacity "before /wiki-finalize-ingest" > /dev/null  # usage % not needed here
    echo "Starting /wiki-finalize-ingest..."
    if ! run_llm "/wiki-finalize-ingest"; then
        echo ""
        echo "────────────────────────────────────────────────────────────────────"
        echo "ERROR: /wiki-finalize-ingest exited with an error.  Current time: $(date '+%H:%M:%S')" >&2
        echo "────────────────────────────────────────────────────────────────────"
        confirm_after_error "/wiki-finalize-ingest"
    fi
    echo ""
    echo "=== Phase 4 - POST-PROCESS: lint check and QMD sync ==="
    echo "Running wiki-lint-check.py..."
    set +e
    python3 "$PROJECT_DIR/scripts/system/wiki-lint-check.py" -- batch-mode --fix-simple-errors --fix-orphans --format text
    local lint_rc=$?
    set -e
    [ "$lint_rc" -ne 0 ] && echo "WARN: wiki-lint-check.py exited with status $lint_rc" >&2

    echo "Running qmd-sync-collections.sh..."
    set +e
    bash "$PROJECT_DIR/scripts/system/qmd-sync-collections.sh"
    local sync_rc=$?
    set -e
    [ "$sync_rc" -ne 0 ] && echo "WARN: qmd-sync-collections.sh exited with status $sync_rc" >&2

    echo ""
    echo "────────────────────────────────────────────────────────────────────"
    echo "Pipeline complete.  Current time: $(date '+%H:%M:%S')"
}

# Dry-run counterpart of run_phase_convert: lists files that would be converted.
run_phase_convert_dry() {
    echo "=== Phase 0 - CONVERT RAW FILES (dry-run): listing files that would be converted ==="

    echo "Would sanitize raw/ filenames..."

    local vtt_files=()
    while IFS= read -r -d '' f; do
        vtt_files+=("$f")
    done < <(find "$PROJECT_DIR/raw/transcripts" -name "*.vtt" -print0 2>/dev/null | sort -z)
    if [ "${#vtt_files[@]}" -gt 0 ]; then
        echo "Would convert ${#vtt_files[@]} VTT transcript(s):"
        printf "  %s\n" "${vtt_files[@]}"
    else
        echo "No VTT transcripts found."
    fi

    local eml_files=()
    while IFS= read -r -d '' f; do
        eml_files+=("$f")
    done < <(find "$PROJECT_DIR/raw/emails" -name "*.eml" -print0 2>/dev/null | sort -z)
    if [ "${#eml_files[@]}" -gt 0 ]; then
        echo "Would convert ${#eml_files[@]} EML email(s):"
        printf "  %s\n" "${eml_files[@]}"
    else
        echo "No EML emails found."
    fi

    local html_files=()
    while IFS= read -r -d '' f; do
        html_files+=("$f")
    done < <(find "$PROJECT_DIR/raw/emails" -name "*.html" -print0 2>/dev/null | sort -z)
    if [ "${#html_files[@]}" -gt 0 ]; then
        echo "Would convert ${#html_files[@]} HTML email(s):"
        printf "  %s\n" "${html_files[@]}"
    else
        echo "No HTML emails found."
    fi
    echo ""
}

# Dry-run counterpart of run_phase_batches: lists batch files that would be processed.
run_phase_batches_dry() {
    local total="$1"
    local effective_total=$(( total < MAX_BATCHES ? total : MAX_BATCHES ))
    echo "=== Phase 2 - INGEST BATCHES (dry-run): would process $effective_total of $total batch file(s) ==="
    local -a files
    shopt -s nullglob
    files=("$PROJECT_DIR/.import"/batch-import-*.txt)
    shopt -u nullglob
    for f in "${files[@]}"; do
        local line_count
        line_count=$(wc -l < "$f" 2>/dev/null | tr -d ' ')
        printf "  %-40s  (%s file(s))\n" "$(basename "$f")" "$line_count"
    done
}

# Dry-run counterpart of run_phase_finalize.
run_phase_finalize_dry() {
    echo ""
    echo "=== Phase 3 - FINALIZE (dry-run): would run /wiki-finalize-ingest ==="
    echo "=== Phase 4 - POST-PROCESS (dry-run): would run wiki-lint-check.py and qmd-sync-collections.sh ==="
    echo ""
    echo "────────────────────────────────────────────────────────────────────"
    echo "Dry-run complete — no changes were made.  Time: $(date '+%H:%M:%S')"
}

main() {
    cd "$PROJECT_DIR"

    local needs_ingest=false
    local batch_count
    batch_count=$(count_batch_files)

    local log_count
    log_count=$(count_batch_log_files)

    if [ "$DRY_RUN" = true ]; then
        if [ "$batch_count" -eq 0 ] && [ "$log_count" -gt 0 ]; then
            needs_ingest=false
        elif [ "$batch_count" -eq 0 ]; then
            needs_ingest=true
        fi

        local first_batch_num=""
        if [ "$batch_count" -gt 0 ]; then
            first_batch_num=$(get_first_batch_number)
        fi

        echo "Start time: $(date '+%H:%M:%S')"
        show_plan "$needs_ingest" "$batch_count" "$first_batch_num"

        if [ "$needs_ingest" = true ]; then
            run_phase_convert_dry
            echo "=== Phase 1 - PARTITION (dry-run): would run wiki-create-import-batches.sh ==="
            echo "  (batch count unknown until partition runs)"
            echo ""
        fi

        if [ "$batch_count" -gt 0 ]; then
            run_phase_batches_dry "$batch_count"
        elif [ "$needs_ingest" = false ] && [ "$log_count" -gt 0 ]; then
            echo "=== Phase 2 - INGEST BATCHES (dry-run): skipped — all batches already consumed ==="
        else
            echo "=== Phase 2 - INGEST BATCHES (dry-run): no batch files to process ==="
        fi

        run_phase_finalize_dry
        return 0
    fi

    if [ -f "$PROJECT_DIR/wiki/log.jsonl" ]; then
        cp "$PROJECT_DIR/wiki/log.jsonl" "$PROJECT_DIR/wiki/log.jsonl.backup"
        echo "Backed up wiki/log.jsonl → wiki/log.jsonl.backup"
    fi

    # All batches consumed but not yet finalized: only batch-log files remain.
    if [ "$batch_count" -eq 0 ] && [ "$log_count" -gt 0 ]; then
        echo "Start time: $(date '+%H:%M:%S')"
        echo ""
        echo "  All ingest batches have been processed."
        echo "  Found $log_count batch log file(s) in .import/ with no remaining batch-import files."
        echo ""
        if confirm_yn "Proceed directly to /wiki-finalize-ingest and process the batch-log files?"; then
            run_phase_finalize
            exit 0
        fi
        echo ""
        if confirm_yn "Delete the $log_count batch-log file(s) and start a new ingest instead?"; then
            rm -f "$PROJECT_DIR/.import"/batch-log-*.jsonl
            echo "Batch log files deleted — starting fresh ingest."
            echo ""
            needs_ingest=true
        else
            echo "Stopped."
            exit 0
        fi
    elif [ "$batch_count" -eq 0 ]; then
        needs_ingest=true
    fi

    local first_batch_num=""
    if [ "$batch_count" -gt 0 ]; then
        first_batch_num=$(get_first_batch_number)
    fi

    echo "Start time: $(date '+%H:%M:%S')"
    show_plan "$needs_ingest" "$batch_count" "$first_batch_num"
    confirm_or_exit

    if [ "$needs_ingest" = true ]; then
        run_phase_convert

        set +e
        run_phase_partition
        local partition_rc=$?
        set -e

        if [ "$partition_rc" -eq "$ND_NOTHING_TO_INGEST" ]; then
            echo ""
            echo "────────────────────────────────────────────────────────────────────"
            echo " Nothing to ingest."
            echo " wiki-create-import-batches.sh reported no new notes"
            echo " (exit code 3). All raw notes are already recorded in"
            echo " wiki/log.jsonl, so there is no batch to process and no"
            echo " finalization is needed."
            echo "────────────────────────────────────────────────────────────────────"
            echo "Pipeline finished cleanly.  Time: $(date '+%H:%M:%S')"
            exit 0
        fi

        batch_count=$(count_batch_files)
        echo "Phase 1 created $batch_count batch file(s)."
    fi

    local batches_rc=0
    if [ "$batch_count" -eq 0 ]; then
        echo "No batch files to process — skipping Phase 2." >&2
    else
        echo "/wiki-ingest-next-batch: $batch_count remaining to process." >&2
        set +e
        run_phase_batches "$batch_count"
        batches_rc=$?
        set -e
    fi

    if [ "$batches_rc" -eq 2 ]; then
        echo ""
        echo "Pipeline stopped before all batches were consumed — finalize skipped."
        echo "Re-run the script to continue from where it left off."
        exit 0
    fi

    run_phase_finalize
}

main
