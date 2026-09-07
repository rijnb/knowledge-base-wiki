#!/usr/bin/env python3
"""
wiki-find.py — List every wiki page about a subject.

Two passes, cheapest first:
  1. `wiki/<type>/index.md` lines (title, filename, one-line description).
  2. Page frontmatter `tags:` — and, with --body, the body text too.

Terms match case-insensitively as substrings (index/body) or as normalized
tags ("agentic coding" == tag `agentic-coding`). Each page is reported once,
under its best match. Output is Markdown grouped by topic type (default) or
JSON:
  {
    "terms": [...],
    "hits": [ {"path", "title", "type", "description", "matched_in", "terms"}, ... ],
    "summary": {"index_hits": N, "page_hits": N, "total": N}
  }

Usage:
  python3 scripts/wiki-find.py [--root DIR] [--types a,b] [--body] [--format md|json] [--out FILE] TERM [TERM ...]
  python3 scripts/wiki-find.py "agentic coding, coding agent, claude code, cursor" --body
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.topic_search import (  # noqa: E402
    TOPIC_TYPES,
    expand_terms,
    format_markdown,
    search_indexes,
    search_pages,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List every wiki page about a subject.")
    parser.add_argument("terms", nargs="+", help="search terms; comma-separated lists are split")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="vault root (default: cwd)")
    parser.add_argument("--types", help=f"comma-separated topic types (default: all of {', '.join(TOPIC_TYPES)})")
    parser.add_argument("--body", action="store_true", help="also grep page bodies (slower, noisier)")
    parser.add_argument("--no-pages", action="store_true", help="index pass only; skip reading page files")
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--out", type=Path, help="write the list to this file; stdout gets only the summary line")
    args = parser.parse_args(argv)

    terms = expand_terms(args.terms)
    if not terms:
        parser.error("no search terms given")
    types = [t.strip() for t in args.types.split(",") if t.strip()] if args.types else None
    root = args.root.resolve()
    if not (root / "wiki").is_dir():
        print(f"error: no wiki/ under {root}", file=sys.stderr)
        return 2

    index_hits = search_indexes(root, terms, types)
    page_hits = [] if args.no_pages else search_pages(
        root, terms, types, exclude={h.path for h in index_hits}, body=args.body
    )
    hits = index_hits + page_hits

    if args.format == "json":
        json.dump({
            "terms": terms,
            "hits": [h.to_dict() for h in hits],
            "summary": {"index_hits": len(index_hits), "page_hits": len(page_hits), "total": len(hits)},
        }, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0

    summary = f"{len(hits)} pages — {len(index_hits)} via index, {len(page_hits)} via tags/body"
    report = f"# Pages matching: {', '.join(terms)}\n\n{summary}\n\n{format_markdown(hits)}"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        print(f"{summary} — written to {args.out}")
    else:
        print(report, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
