#!/usr/bin/env python3
"""convert-html-to-md — convert exported HTML email files to Markdown for wiki ingestion.

Expected input format (Teams/Outlook export):
  FROM:<email>;TO:<email1>;<email2>;...;SUBJECT:<text>;BODY:<html>

If the header prefix is absent the entire file is treated as the HTML body.
The date is extracted from an ISO-style filename (YYYY-MM-DDTHH_MM_SS±HH_MM),
falling back to file mtime.

Each .html is moved into a _resources/ subdirectory of its directory, and a
companion .md with the same stem is written where the .html used to live.
The companion contains YAML frontmatter, an ![[embed]] of the original file,
and the converted body inside a collapsed "Extracted text" callout.

EXIT CODES
  0  all files converted successfully (or nothing to do)
  1  one or more files failed or an argument error occurred

OUTPUT FORMAT (for AI tools)
  Each action is prefixed with a tag:
    [OK]    successful step
    [WARN]  non-fatal issue (e.g. missing header, fallback used)
    [ERROR] file skipped due to unrecoverable error
    [INFO]  informational (rename, summary)

EXAMPLES
  # Convert all new .html in a directory
  python3 convert-html-to-md.py --input-dir raw/emails

  # Re-convert all including those already converted
  python3 convert-html-to-md.py --input-dir raw/emails --force

  # Dry run
  python3 convert-html-to-md.py --input-dir raw/emails --dry-run
"""

import argparse
import re
import sys
import textwrap
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import html2text as _html2text_mod
    _HAS_HTML2TEXT = True
except ImportError:
    _HAS_HTML2TEXT = False


# ---------------------------------------------------------------------------
# Logging helpers (same conventions as convert-eml-to-md.py)
# ---------------------------------------------------------------------------

_WARNINGS: list[str] = []
_ERRORS: list[str] = []


def _log(tag: str, msg: str, file=None) -> None:
    print(f"  {tag} {msg}", file=file or sys.stdout)


def warn(msg: str) -> None:
    _log("[WARN]", msg)
    _WARNINGS.append(msg)


def error(msg: str) -> None:
    _log("[ERROR]", msg, file=sys.stderr)
    _ERRORS.append(msg)


def ok(msg: str) -> None:
    _log("[OK]", msg)


def info(msg: str) -> None:
    _log("[INFO]", msg)


# ---------------------------------------------------------------------------
# Header parsing
# ---------------------------------------------------------------------------

# Matches the structured prefix: FROM:...,TO:...,[CC:...,][BCC:...,]SUBJECT:...,BODY:<html
# Also accepts the legacy semicolon-separated format.
_HEADER_RE = re.compile(
    r"^FROM:(?P<from>[^,;]*)"
    r"[,;]TO:(?P<to>.*?)"
    r"(?:[,;]CC:(?P<cc>.*?))?"
    r"(?:[,;]BCC:(?P<bcc>.*?))?"
    r"[,;]SUBJECT:(?P<subject>.*?)"
    r"[,;]BODY:(?P<body>.*)$",
    re.DOTALL,
)


def parse_header(text: str) -> tuple[str, str, str, str, str, str] | None:
    """Return (from, to, cc, bcc, subject, body_html) or None if no structured header."""
    m = _HEADER_RE.match(text.strip())
    if not m:
        return None
    return (
        m.group("from").strip(),
        m.group("to").strip(),
        (m.group("cc") or "").strip(),
        (m.group("bcc") or "").strip(),
        m.group("subject").strip(),
        m.group("body").strip(),
    )


# ---------------------------------------------------------------------------
# Date extraction
# ---------------------------------------------------------------------------

# Matches filenames like 2026-05-13T08_32_05+00_00 or 2026-05-13T08_32_05-05_00
_FILENAME_DATE_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T(?P<time>\d{2}_\d{2}_\d{2})(?P<tz>[+-]\d{2}_\d{2})"
)


def _parse_filename_date(stem: str) -> datetime | None:
    m = _FILENAME_DATE_RE.match(stem)
    if not m:
        return None
    try:
        date_s = m.group("date")
        time_s = m.group("time").replace("_", ":")
        tz_s = m.group("tz").replace("_", ":")  # e.g. +00:00
        dt = datetime.fromisoformat(f"{date_s}T{time_s}{tz_s}")
        return dt
    except ValueError:
        return None


def get_date(html_path: Path) -> tuple[datetime, str]:
    dt = _parse_filename_date(html_path.stem)
    if dt:
        return dt, "filename"
    stat = html_path.stat()
    ts = getattr(stat, "st_birthtime", None) or stat.st_mtime
    return datetime.fromtimestamp(ts, tz=timezone.utc), "file mtime (fallback)"


# ---------------------------------------------------------------------------
# HTML → Markdown
# ---------------------------------------------------------------------------

def html_to_markdown(html: str) -> str:
    if not _HAS_HTML2TEXT:
        text = re.sub(r"<[^>]+>", "", html)
        return re.sub(r"\n{3,}", "\n\n", text).strip()
    h = _html2text_mod.HTML2Text()
    h.ignore_links = False
    h.body_width = 0
    h.protect_links = False
    h.wrap_links = False
    return h.handle(html).strip()


# ---------------------------------------------------------------------------
# YAML helpers
# ---------------------------------------------------------------------------

def yaml_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


# ---------------------------------------------------------------------------
# Filename helpers
# ---------------------------------------------------------------------------

_FILENAME_CHAR_MAP = str.maketrans({
    # Curly / smart single quotes
    "‘": "'",    # '  left single quotation mark
    "’": "'",    # '  right single quotation mark / apostrophe
    "‚": "'",    # ‚  single low-9 quotation mark
    "‹": "<",    # ‹  single left-pointing angle quotation mark
    "›": ">",    # ›  single right-pointing angle quotation mark
    "′": "'",    # ′  prime
    "‵": "'",    # ‵  reversed prime
    # Curly / smart double quotes
    "“": '"',    # "  left double quotation mark
    "”": '"',    # "  right double quotation mark
    "„": '"',    # „  double low-9 quotation mark
    "‟": '"',    # ‟  double high-reversed-9 quotation mark
    "«": '"',    # «  left-pointing double angle quotation mark
    "»": '"',    # »  right-pointing double angle quotation mark
    "″": '"',    # ″  double prime
    "‶": '"',    # ‶  reversed double prime
    # Dashes
    "–": "-",    # –  en dash
    "—": "-",    # —  em dash
    "―": "-",    # ―  horizontal bar
    "−": "-",    # −  minus sign
    # Arrows
    "←": "<-",   # ←  leftwards arrow
    "→": "->",   # →  rightwards arrow
    "↔": "<->",  # ↔  left right arrow
    "⇐": "<=",   # ⇐  leftwards double arrow
    "⇒": "=>",   # ⇒  rightwards double arrow
    "⇔": "<=>",  # ⇔  left right double arrow
    "↖": "^",    # ↖  north west arrow
    "↗": "^",    # ↗  north east arrow
    "↘": "v",    # ↘  south east arrow
    "↙": "v",    # ↙  south west arrow
    # Ellipsis
    "…": "...",  # …  horizontal ellipsis
    # Bullets / dots
    "•": "-",    # •  bullet
    "·": ".",    # ·  middle dot
    "‣": "-",    # ‣  triangular bullet
    # Spaces
    " ": " ",    # non-breaking space
    " ": " ",    # narrow no-break space
    " ": " ",    # thin space
    "​": "",     # zero-width space
    # Misc
    "×": "x",    # ×  multiplication sign
    "÷": "-",    # ÷  division sign  (/ is path separator — use -)
    "⁄": "-",    # ⁄  fraction slash (/ is path separator — use -)
})


def sanitize_filename(name: str) -> str:
    return name.translate(_FILENAME_CHAR_MAP)


# ---------------------------------------------------------------------------
# _resources layout helpers (same conventions as convert-eml-to-md.py)
# ---------------------------------------------------------------------------

def _references_source(md_path: Path, src_name: str) -> bool:
    """True if md_path's frontmatter `source:` field references src_name."""
    try:
        with md_path.open(encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i > 20:
                    break
                if line.startswith("source:") and src_name in line:
                    return True
    except OSError:
        pass
    return False


def companion_base_dir(src: Path) -> Path:
    """Directory where the companion .md lives: the directory above _resources."""
    return src.parent.parent if src.parent.name == "_resources" else src.parent


def find_companion(src: Path) -> Path | None:
    """Return the existing companion .md for src, or None."""
    base = companion_base_dir(src)
    for cand in (base / (sanitize_filename(src.stem) + ".md"),
                 base / (sanitize_filename(src.name) + ".md")):
        if cand.exists() and _references_source(cand, src.name):
            return cand
    return None


def companion_target(src: Path) -> Path:
    """Path to write the companion .md to.

    Uses <stem>.md; falls back to <full name>.md when a different note
    already owns <stem>.md.
    """
    base = companion_base_dir(src)
    stem_md = base / (sanitize_filename(src.stem) + ".md")
    if stem_md.exists() and not _references_source(stem_md, src.name):
        return base / (sanitize_filename(src.name) + ".md")
    return stem_md


def move_to_resources(src: Path, dry_run: bool) -> Path | None:
    """Move src into a _resources/ subdir of its directory; return the new path.

    Files already inside a _resources/ directory are left where they are.
    Returns None when the destination already exists (collision).
    """
    if src.parent.name == "_resources":
        return src
    dest = src.parent / "_resources" / src.name
    if dest.exists():
        error(f"cannot move {src.name!r}: {dest} already exists")
        return None
    if dry_run:
        info(f"[dry-run] would move {src.name!r} → '_resources/{src.name}'")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dest)
    info(f"moved {src.name!r} → '_resources/{src.name}'")
    return dest


def extracted_text_callout(text: str) -> str:
    """Wrap text in a collapsed Obsidian callout block."""
    lines = ["> [!ocr-extractor]- Extracted text"]
    for line in (text.splitlines() or [""]):
        lines.append(("> " + line).rstrip())
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core conversion
# ---------------------------------------------------------------------------

def convert(html_path: Path, *, dry_run: bool) -> bool:
    if not html_path.exists():
        error(f"file not found: {html_path}")
        return False
    if not html_path.is_file():
        error(f"not a regular file: {html_path}")
        return False
    if html_path.suffix.lower() != ".html":
        error(f"not an .html file: {html_path.name!r}")
        return False

    try:
        raw_text = html_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        error(f"could not read {html_path.name!r}: {exc}")
        return False

    # --- date ---
    try:
        dt, date_source = get_date(html_path)
    except Exception as exc:
        warn(f"date extraction failed ({exc}); using today")
        dt = datetime.now(tz=timezone.utc)
        date_source = "today (fallback after error)"
    date_str = dt.strftime("%Y-%m-%d")

    if date_source != "filename":
        warn(f"date sourced from {date_source}: {date_str}")

    # --- parse structured header or fall back to body-only ---
    def _split_addresses(raw: str) -> str:
        sep = "," if "," in raw else ";"
        return ", ".join(a.strip() for a in raw.split(sep) if a.strip())

    parsed = parse_header(raw_text)
    if parsed:
        from_val, to_raw, cc_raw, bcc_raw, subject, body_html = parsed
        to_val  = _split_addresses(to_raw)
        cc_val  = _split_addresses(cc_raw)
        bcc_val = _split_addresses(bcc_raw)
        if not from_val:
            warn("FROM field is empty")
            from_val = "(unknown sender)"
        if not to_val:
            warn("TO field is empty")
            to_val = "(unknown recipient)"
        if not subject:
            warn("SUBJECT field is empty; using '(no subject)'")
            subject = "(no subject)"
    else:
        warn("no structured header found; treating entire file as HTML body")
        from_val = "(unknown sender)"
        to_val   = "(unknown recipient)"
        cc_val   = ""
        bcc_val  = ""
        subject  = "(no subject)"
        body_html = raw_text

    # --- convert body ---
    if not _HAS_HTML2TEXT:
        warn("html2text not installed; falling back to tag-stripping for HTML body")
    try:
        body_md = html_to_markdown(body_html)
    except Exception as exc:
        warn(f"HTML conversion failed ({exc}); body will be empty")
        body_md = ""

    if not body_md:
        warn("empty body after HTML conversion")

    # --- move the original into _resources/ ---
    moved = move_to_resources(html_path, dry_run)
    if moved is None:
        return False

    md_path = companion_target(moved)

    # --- assemble ---
    frontmatter = [
        "---",
        "type: email",
        f"subject: {yaml_str(subject)}",
        f"date: {date_str}",
        f"source: {yaml_str('_resources/' + moved.name)}",
        f"from: {yaml_str(from_val)}",
        f"to: {yaml_str(to_val)}",
    ]
    if cc_val:
        frontmatter.append(f"cc: {yaml_str(cc_val)}")
    if bcc_val:
        frontmatter.append(f"bcc: {yaml_str(bcc_val)}")
    frontmatter.append("---")

    header_block = [
        "```",
        f"Date: {date_str}",
        f"From: {from_val}",
        f"To: {to_val}",
    ]
    if cc_val:
        header_block.append(f"CC: {cc_val}")
    if bcc_val:
        header_block.append(f"BCC: {bcc_val}")
    header_block += [
        f"Subject: {subject}",
        "```",
    ]

    content = (
        "\n".join(frontmatter)
        + "\n\n" + f"![[{moved.name}]]"
        + "\n\n" + "\n".join(header_block)
        + "\n\n" + extracted_text_callout(body_md)
        + "\n"
    )

    if dry_run:
        info(f"[dry-run] would write {md_path.name!r} ({len(content)} bytes)")
    else:
        try:
            md_path.parent.mkdir(parents=True, exist_ok=True)
            md_path.write_text(content, encoding="utf-8")
        except Exception as exc:
            error(f"could not write {md_path}: {exc}")
            return False
        ok(f"wrote {md_path.name!r} ({len(content)} bytes, date from {date_source})")

    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="convert-html-to-md.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent("""\
            Convert exported HTML email files to Markdown (.md) for wiki ingestion.

            Supports the Teams/Outlook export format:
              FROM:<email>;TO:<email1>;...;SUBJECT:<text>;BODY:<html>

            If the header prefix is absent, the entire file is treated as HTML body.
            The date is parsed from an ISO-style filename; file mtime is the fallback.

            Output lines are prefixed with [OK], [WARN], [ERROR], or [INFO].
        """),
    )
    parser.add_argument(
        "files",
        nargs="*",
        metavar="FILE.html",
        help="one or more .html files to convert",
    )
    parser.add_argument(
        "--input-dir",
        metavar="DIR",
        help="convert all *.html files in this directory",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-convert files that already have a .md counterpart",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show what would be done without writing any files",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    paths: list[Path] = []

    if args.input_dir and args.files:
        print("[WARN] both --input-dir and explicit files given; using --input-dir", file=sys.stderr)

    if args.input_dir:
        d = Path(args.input_dir)
        if not d.exists():
            print(f"[ERROR] directory not found: {args.input_dir}", file=sys.stderr)
            sys.exit(1)
        if not d.is_dir():
            print(f"[ERROR] not a directory: {args.input_dir}", file=sys.stderr)
            sys.exit(1)
        paths = sorted(d.glob("*.html"))
        if not paths:
            print(f"[INFO] no .html files found in {args.input_dir}")
            sys.exit(0)
    elif args.files:
        paths = [Path(f) for f in args.files]
    else:
        parser.print_help()
        sys.exit(1)

    if not args.force:
        before = len(paths)
        def _md_exists(p: Path) -> bool:
            if find_companion(p):
                return True
            # Legacy layout: a converted/<stem>.md sibling from the old pipeline.
            return (p.parent / "converted" / (sanitize_filename(p.stem) + ".md")).exists()
        paths = [p for p in paths if not _md_exists(p)]
        skipped = before - len(paths)
        if skipped:
            print(f"[INFO] skipping {skipped} file(s) that already have a .md (use --force to re-convert)")

    if not paths:
        print("[INFO] nothing to convert")
        sys.exit(0)

    n_ok = n_fail = 0
    for p in paths:
        print(f"converting {p.name!r} …")
        success = convert(p, dry_run=args.dry_run)
        if success:
            n_ok += 1
        else:
            n_fail += 1

    label = "[dry-run] " if args.dry_run else ""
    total = n_ok + n_fail
    print(
        f"\n[INFO] {label}done: {n_ok}/{total} converted"
        + (f", {n_fail} failed" if n_fail else "")
        + (f", {len(_WARNINGS)} warning(s)" if _WARNINGS else "")
    )

    if n_fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
