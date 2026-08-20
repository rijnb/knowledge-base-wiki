#!/usr/bin/env python3
"""
wiki-create-index-pages.py — Rebuild wiki index pages.

Creates:
  wiki/index.md         — root index (bundle root) linking to all topic sections
  wiki/<topic>/index.md — per-topic index listing all pages in that section

Format follows OKF v0.2 progressive disclosure (§8):
  - Only the bundle-root wiki/index.md carries frontmatter, and only okf_version.
  - Topic indexes carry no frontmatter; the rebuild date lives in the byline.
  - Topics with more than LETTER_BUCKET_THRESHOLD pages are grouped under
    letter headings with a jump line, so a consumer can read one section
    instead of the whole file.
  - Entry summaries are capped at SUMMARY_MAX_CHARS characters.
  - Topics with at least RECENT_MIN_DATED dated pages get a
    "Recently updated" block (top RECENT_COUNT by frontmatter date).

Run from any directory; the wiki path is resolved relative to this script's
parent by default, or override with --wiki-dir.
"""
import argparse
import unicodedata
import datetime
import os
import re
import sys

TOPIC_DIRS: dict[str, tuple[str, str]] = {
    "competition":   ("Competitors",   "Competing companies, products, and approaches."),
    "concepts":      ("Concepts",      "Technologies, standards, mental models, and domain vocabulary."),
    "conversations": ("Conversations", "Valuable results of earlier queries and conversations."),
    "decisions":     ("Decisions",     "Why decisions were taken, on what basis, by whom, and when."),
    "people":        ("People",        "Colleagues, contacts, external stakeholders, and teams."),
    "problems":      ("Problems",      "Active and past problems."),
    "projects":      ("Projects",      "Active and past initiatives."),
    "systems":       ("Systems",       "Our products, platforms, and services."),
}

OKF_VERSION = "0.2"
SUMMARY_MAX_CHARS = 160
LETTER_BUCKET_THRESHOLD = 100
RECENT_COUNT = 10
RECENT_MIN_DATED = 10

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _balance_wikilinks(text: str) -> str:
    """Trim a truncated string so it never ends inside an unclosed [[wikilink."""
    while text.count("[[") != text.count("]]"):
        cut = text.rfind("[[")
        if cut < 0:
            break
        text = text[:cut].rstrip()
    return text


def _cap_summary(summary: str) -> str:
    """Truncate a summary to SUMMARY_MAX_CHARS without breaking wikilinks."""
    if len(summary) <= SUMMARY_MAX_CHARS:
        return summary
    cut = summary.rfind(" ", 0, SUMMARY_MAX_CHARS)
    if cut <= 0:
        cut = SUMMARY_MAX_CHARS
    return _balance_wikilinks(summary[:cut].rstrip(" ,;:—-")) + " …"


def get_page_info(filepath: str) -> tuple[str, str, str | None]:
    """Return (h1 title, first-sentence summary, frontmatter date) from a markdown file."""
    stem = os.path.splitext(os.path.basename(filepath))[0]
    try:
        with open(filepath, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as exc:
        print(f"WARNING: cannot read {filepath}: {exc}", file=sys.stderr)
        return stem, "No summary available.", None

    # Scan (and skip) YAML front matter, capturing the date field
    start = 0
    date: str | None = None
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            stripped = lines[i].strip()
            if stripped == "---":
                start = i + 1
                break
            if stripped.startswith("date:") and date is None:
                m = DATE_RE.search(stripped)
                if m:
                    date = m.group(1)

    title: str | None = None
    summary: str | None = None
    for line in lines[start:]:
        stripped = line.strip()
        if not stripped:
            continue
        if title is None and stripped.startswith("#"):
            title = re.sub(r"^#+\s*", "", stripped)
        elif title is not None and summary is None and not stripped.startswith("#"):
            summary = stripped
            break

    if title is None:
        title = stem
    if summary is None:
        summary = "No summary available."

    # Truncate to first sentence (never inside a wikilink), then cap length
    m = re.match(r"^(.+?[.!?])\s", summary + " ")
    if m:
        candidate = _balance_wikilinks(m.group(1)).rstrip()
        if candidate:
            summary = candidate
    summary = _cap_summary(summary)

    return title, summary, date


def _bucket_key(title: str) -> str:
    """Letter bucket for a title: A–Z, or 0-9 for anything else."""
    for ch in title:
        if ch.isalpha():
            folded = unicodedata.normalize("NFKD", ch.upper())
            base = next((c for c in folded if "A" <= c <= "Z"), None)
            return base if base else "0-9"
        if ch.isdigit():
            return "0-9"
    return "0-9"


def write_file(path: str, content: str, dry_run: bool) -> None:
    if not dry_run:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)


def build_topic_index(
    wiki_dir: str,
    topic_key: str,
    type_name: str,
    description: str,
    today: str,
    dry_run: bool,
    verbose: bool,
) -> int:
    """Build index.md for one topic directory. Returns number of entries written."""
    dirpath = os.path.join(wiki_dir, topic_key)
    if not os.path.isdir(dirpath):
        print(f"WARNING: directory not found, skipping: {topic_key}/", file=sys.stderr)
        return 0

    files = sorted(
        f for f in os.listdir(dirpath)
        if f.endswith(".md") and f != "index.md"
    )

    pages = []  # (title, link, entry_line, date)
    for fname in files:
        fpath = os.path.join(dirpath, fname)
        title, summary, date = get_page_info(fpath)
        stem = os.path.splitext(fname)[0]
        # Use filename stem for the link path; show title as display text
        link = f"[[wiki/{topic_key}/{stem}|{title}]]"
        pages.append((title, link, f"- {link} — {summary}", date))

    pages.sort(key=lambda p: p[0].casefold())

    parts = [
        f"# {type_name}\n\n",
        f"[[wiki/index|← Index]] · {len(pages)} pages · rebuilt {today}\n\n",
        f"{description}\n\n",
    ]

    # Recently updated block
    dated = sorted(
        ((date, title, link) for title, link, _entry, date in pages if date),
        key=lambda t: (t[0], t[1].casefold()),
        reverse=True,
    )
    if len(dated) >= RECENT_MIN_DATED:
        parts.append("## Recently updated\n\n")
        for date, _title, link in dated[:RECENT_COUNT]:
            parts.append(f"- {date} · {link}\n")
        parts.append("\n")

    if not pages:
        parts.append("_No pages yet._\n")
    elif len(pages) > LETTER_BUCKET_THRESHOLD:
        buckets: dict[str, list[str]] = {}
        for title, _link, entry, _date in pages:
            buckets.setdefault(_bucket_key(title), []).append(entry)
        ordered = sorted(buckets, key=lambda k: (k != "0-9", k))
        jump = " · ".join(f"[[#{k}|{k}]] ({len(buckets[k])})" for k in ordered)
        parts.append(f"Sections: {jump}\n\n")
        for k in ordered:
            parts.append(f"## {k}\n\n")
            parts.append("\n".join(buckets[k]) + "\n\n")
    else:
        parts.append("\n".join(entry for _title, _link, entry, _date in pages) + "\n")

    content = "".join(parts).rstrip("\n") + "\n"
    index_path = os.path.join(dirpath, "index.md")
    write_file(index_path, content, dry_run)
    verb = "would write" if dry_run else "wrote"
    print(f"{verb} {os.path.relpath(index_path)} ({len(pages)} entries)")
    return len(pages)


def build_root_index(
    wiki_dir: str,
    counts: dict[str, int],
    today: str,
    dry_run: bool,
    verbose: bool,
) -> None:
    """Build wiki/index.md linking to all topic index.md pages."""
    rows = [
        f'---\nokf_version: "{OKF_VERSION}"\n---\n',
        "# Wiki Index\n\n",
        f"Rebuilt {today}\n\n",
        "| Section | Pages | Description |\n",
        "|---------|------:|-------------|\n",
    ]
    for topic_key, (type_name, description) in TOPIC_DIRS.items():
        link = f"[[wiki/{topic_key}/index\\|{type_name}]]"
        rows.append(f"| {link} | {counts.get(topic_key, 0)} | {description} |\n")

    content = "".join(rows)
    index_path = os.path.join(wiki_dir, "index.md")
    write_file(index_path, content, dry_run)
    verb = "would write" if dry_run else "wrote"
    print(f"{verb} {os.path.relpath(index_path)}")


def resolve_wiki_dir(cli_arg: str | None) -> str:
    if cli_arg:
        return os.path.abspath(cli_arg)
    # Default: wiki/ is at the repo root (two levels above scripts/system/)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(os.path.dirname(script_dir)), "wiki")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--wiki-dir",
        metavar="PATH",
        help=(
            "Path to the wiki directory. "
            "Defaults to 'wiki/' relative to this script's parent directory."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be written without creating any files.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output (implied by --dry-run).",
    )
    args = parser.parse_args()

    wiki_dir = resolve_wiki_dir(args.wiki_dir)
    if not os.path.isdir(wiki_dir):
        print(f"ERROR: wiki directory not found: {wiki_dir}", file=sys.stderr)
        sys.exit(1)

    today = datetime.datetime.now().strftime("%Y-%m-%d")

    print(f"Rebuilding wiki index pages in {os.path.relpath(wiki_dir)}/", flush=True)
    if args.verbose or args.dry_run:
        print()

    try:
        total = 0
        counts: dict[str, int] = {}
        for topic_key, (type_name, description) in TOPIC_DIRS.items():
            n = build_topic_index(
                wiki_dir, topic_key, type_name, description,
                today, args.dry_run, args.verbose,
            )
            counts[topic_key] = n
            total += n

        build_root_index(wiki_dir, counts, today, args.dry_run, args.verbose)
    except OSError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    n_files = len(TOPIC_DIRS) + 1
    suffix = f"{total} entries" if args.verbose or args.dry_run else ""
    print(f"\nDone — {n_files} index files written." + (f" {suffix}" if suffix else ""))


if __name__ == "__main__":
    main()
