#!/usr/bin/env python3
"""
Backfill freshness metadata into wiki pages AND raw source pages.

Resolved fields written to frontmatter:
  date:            YYYY-MM-DD        # best content date
  date_span:       YYYY | YYYY-YYYY  # min..max year (flags era-mixing)
  date_confidence: high|medium|low   # basis of the (newest) date

WIKI pages: aggregate the content dates of every linked source
  (annotation date > filename date > parent-folder date > raw frontmatter
   content fields > capture fields), then take the NEWEST as `date`.
RAW pages: resolve the file's own content date directly. A date or year-range in
  the filename (YYYY-MM-DD, DD-MM-YYYY, a bare year YYYY, or a range YYYY-YYYY)
  wins at HIGH confidence; a range sets a multi-year date_span. Otherwise date_span
  is just the resolved year.

`date` overwrites any pre-existing `date` field. Old field names from the
earlier run (latest_source / source_span / source_date_confidence) are stripped.

Run from the vault root (or anywhere — the vault is auto-detected).

Usage:
  python3 scripts/system/wiki-assign-dates.py            # dry-run: report only
  python3 scripts/system/wiki-assign-dates.py --apply    # write frontmatter
  python3 scripts/system/wiki-assign-dates.py --revert   # strip all managed keys

Run automatically by wiki-finalize-ingest after index rebuild.
"""
import os, re, sys, glob
from collections import Counter

def _find_vault(start):
    """Walk up from `start` to the dir containing both wiki/ and raw/."""
    d = start
    while True:
        if os.path.isdir(os.path.join(d, "wiki")) and os.path.isdir(os.path.join(d, "raw")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.getcwd()
        d = parent

VAULT = _find_vault(os.path.dirname(os.path.abspath(__file__)))
WIKI = os.path.join(VAULT, "wiki")
RAW = os.path.join(VAULT, "raw")
APPLY = "--apply" in sys.argv
REVERT = "--revert" in sys.argv

def _arg_paths():
    """--paths a.md b.md ... : restrict to these files (relative to vault or absolute)."""
    if "--paths" not in sys.argv:
        return None
    i = sys.argv.index("--paths")
    return [a for a in sys.argv[i+1:] if not a.startswith("--")]

PATHS = _arg_paths()

# keys we write
WRITE_KEYS = ("date", "date_span", "date_confidence")
# keys we remove before writing / on revert (new names + legacy names)
STRIP_KEYS = ("date", "date_span", "date_confidence",
              "latest_source", "source_span", "source_date_confidence")

ISO_FULL = re.compile(r"\b((?:19|20)\d{2})-(0[1-9]|1[0-2])-([0-3]\d)\b")
# digit-lookarounds (not \b): matches 2021 in '2021_Workshop' but rejects
# JIRA ticket numbers like GOSDK-196636 (digit-adjacent).
YEAR = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")
MONTHS = {m: i+1 for i, m in enumerate(
    ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"])}
MONTH_YEAR = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+((?:19|20)\d{2})\b", re.I)
# ISO date with digit-lookarounds (not \b): matches 2024-03-14 even when followed
# by '_' (a word char), e.g. 2024-03-14_notes.md, where ISO_FULL's \b would fail.
ISO_FN = re.compile(r"(?<!\d)((?:19|20)\d{2})-(0[1-9]|1[0-2])-([0-3]\d)(?!\d)")
# DD-MM-YYYY (day-month-year) in a filename, e.g. 14-03-2024
DMY = re.compile(r"(?<!\d)([0-3]\d)-(0[1-9]|1[0-2])-((?:19|20)\d{2})(?!\d)")
# year range, e.g. 2020-2023 / 2020–2023 (en-dash) -> flags a multi-year span
YEAR_RANGE = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*[-–]\s*((?:19|20)\d{2})(?!\d)")

CONTENT_FIELDS = ["sent", "published", "when", "date"]   # high
EDIT_FIELDS    = ["last_modified"]                        # medium
CAPTURE_FIELDS = ["created_date", "created"]              # low
# `fetched` is a pure sync timestamp (never a content date) -> tried LAST,
# below body-text dates, in resolve_page.
SYNC_FIELDS    = ["fetched"]                              # lowest

CONF = {"high": 3, "medium": 2, "low": 1}

def norm_date(s):
    if s is None:
        return None
    s = str(s).strip().strip('"').strip("'")
    m = ISO_FULL.search(s)
    if m:
        return (f"{m.group(1)}-{m.group(2)}-{m.group(3)}", "day")
    m = MONTH_YEAR.search(s)
    if m:
        return (f"{m.group(2)}-{MONTHS[m.group(1)[:3].lower()]:02d}-01", "month")
    m = YEAR.search(s)
    if m:
        return (f"{m.group(0)}-07-01", "year")
    return None

def filename_date(name):
    """Date encoded in a filename -> (date, span, conf) or None. Always HIGH
    confidence. Recognised, in priority order:
      1. year RANGE  YYYY-YYYY  -> date = latest year, span = earliest–latest
      2. ISO YYYY-MM-DD         -> full day date (robust to '_' separators)
      3. DD-MM-YYYY             -> full day date
      4. via norm_date(): 'Mon YYYY' or a bare year YYYY (19xx/20xx)
    """
    base = os.path.basename(name)
    m = YEAR_RANGE.search(base)
    if m:
        ey, ly = sorted((m.group(1), m.group(2)))
        span = ey if ey == ly else f"{ey}–{ly}"
        return (f"{ly}-07-01", span, "high")
    m = ISO_FN.search(base)
    if m:
        date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        return (date, date[:4], "high")
    m = DMY.search(base)
    if m:
        date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        return (date, date[:4], "high")
    d = norm_date(base)
    if d:
        return (d[0], d[0][:4], "high")
    return None

def read_frontmatter(path):
    fm = {}
    try:
        with open(path, encoding="utf-8") as f:
            txt = f.read()
    except Exception:
        return fm, ""
    if not txt.startswith("---"):
        return fm, txt
    end = txt.find("\n---", 3)
    if end == -1:
        return fm, txt
    for line in txt[3:end].splitlines():
        m = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", line)
        if m:
            fm[m.group(1).lower()] = m.group(2).strip()
    return fm, txt

def file_content_date(rawpath, linkpath=None, skip_date_field=False):
    """Best content date for a single file -> (date, conf) or None.

    skip_date_field: when resolving a RAW file's OWN date, ignore a pre-existing
    `date` frontmatter field (we are about to overwrite it) to avoid circularity.
    """
    fd = filename_date(os.path.basename(rawpath))
    if fd:
        return (fd[0], fd[2])
    if linkpath:
        fd = filename_date(os.path.basename(linkpath))
        if fd:
            return (fd[0], fd[2])
        # year anywhere in the link path (e.g. a parent folder: raw/2021/...)
        if YEAR.search(linkpath):
            d = norm_date(linkpath)
            if d: return (d[0], "high")
    if os.path.isfile(rawpath):
        fm, _ = read_frontmatter(rawpath)
        # If the source already carries OUR managed freshness, inherit it verbatim
        # (date + its real confidence) — prevents laundering a low-confidence source
        # date into a high-confidence content date on the consuming page.
        if not skip_date_field and fm.get("date_confidence") and fm.get("date"):
            d = norm_date(fm["date"])
            if d:
                c = fm["date_confidence"] if fm["date_confidence"] in CONF else "low"
                return (d[0], c)
        content = [f for f in CONTENT_FIELDS if not (skip_date_field and f == "date")]
        for fld in content:
            if fm.get(fld):
                d = norm_date(fm[fld])
                if d: return (d[0], "high")
        for fld in EDIT_FIELDS:
            if fm.get(fld):
                d = norm_date(fm[fld])
                if d: return (d[0], "medium")
        for fld in CAPTURE_FIELDS:
            if fm.get(fld):
                d = norm_date(fm[fld])
                if d: return (d[0], "low")
    return None

def body_date(txt):
    """Scan body text (after frontmatter) for the latest plausible date.
    Low-confidence fallback for raw artifacts that carry dates only in prose
    (e.g. converted emails: 'Sent: 14 Mar 2024'). Returns (date, 'low') or None."""
    body = txt
    if txt.startswith("---"):
        end = txt.find("\n---", 3)
        if end != -1:
            body = txt[end+4:]
    cands = []
    for m in ISO_FULL.finditer(body):
        cands.append(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")
    for m in MONTH_YEAR.finditer(body):
        cands.append(f"{m.group(2)}-{MONTHS[m.group(1)[:3].lower()]:02d}-01")
    # sanity bound: ignore absurd future years
    cands = [c for c in cands if "1990" <= c <= "2035-12-31"]
    if not cands:
        return None
    return (max(cands), "low")

def resolve_raw_path(linktext):
    target = linktext.split("|")[0].strip()
    if not target.startswith("raw/"):
        return None
    cand = os.path.join(VAULT, target)
    if not cand.lower().endswith(".md") and os.path.isfile(cand + ".md"):
        return cand + ".md"
    if os.path.isfile(cand):
        return cand
    if target.endswith("..."):
        matches = [m for m in glob.glob(os.path.join(VAULT, glob.escape(target[:-3]) + "*"))
                   if m.lower().endswith(".md")]
        if matches:
            return matches[0]
    return cand

SRC_HDR = re.compile(r"^#{2,}\s+Sources\s*$", re.I)
LINK = re.compile(r"\[\[([^\]]+)\]\]")
ITALIC = re.compile(r"\*([^*]+)\*")
BARE = re.compile(r"(raw/[^\s\]|*]+(?:\s+[^\s\]|*]+)*?\.md)")

def _extract_raw_path(ln):
    """Return the raw/... path referenced on a Sources line, across formats:
    [[raw/...]] wikilinks (prefer the raw-targeted one, ignore [[Person]] links),
    *raw/...* italics, or a bare raw/... path. Returns None if none."""
    for m in LINK.finditer(ln):
        tgt = m.group(1).split("|")[0].strip()
        if tgt.startswith("raw/"):
            return tgt
    m = ITALIC.search(ln)
    if m and m.group(1).strip().startswith("raw/"):
        return m.group(1).strip()
    m = BARE.search(ln)
    if m:
        return m.group(1).strip()
    return None

def page_source_dates(txt):
    in_src = False
    for ln in txt.splitlines():
        if SRC_HDR.match(ln):
            in_src = True; continue
        if in_src and re.match(r"^#{1,6}\s+\S", ln):
            break
        if not in_src:
            continue
        pathtext = _extract_raw_path(ln)
        # Consider any source bullet — sources are sometimes referenced by bare
        # filename/description (no raw/ path), but still carry a date in the line.
        is_bullet = re.match(r"^\s*[-*+]\s+\S", ln)
        if not pathtext and "raw/" not in ln and not is_bullet:
            continue
        # 1) full ISO date anywhere on the line (filename or annotation) -> high.
        #    Robust to bracketed filenames ([Bi-Weekly]) and [[Person]] links in the annotation.
        if ISO_FULL.search(ln):
            d = norm_date(ln)
            if d:
                yield (d[0], "high"); continue
        # 2) resolve via the raw file (parent-folder year / frontmatter dates)
        rawpath = resolve_raw_path(pathtext) if pathtext else None
        r = file_content_date(rawpath, pathtext) if rawpath else None
        if r:
            yield r; continue
        # 3) month-year / year anywhere on the line -> high
        if MONTH_YEAR.search(ln) or YEAR.search(ln):
            d = norm_date(ln)
            if d:
                yield (d[0], "high"); continue

def is_managed_page(path):
    """Only files under wiki/ or raw/ get managed dates. Top-level vault files
    (CLAUDE.md, AGENTS.md, README.md, index.md, …) are never touched, even when
    passed explicitly via --paths."""
    ap = os.path.abspath(path)
    return ap.startswith(WIKI + os.sep) or ap.startswith(RAW + os.sep)

def is_content_page(path):
    return is_managed_page(path) and os.path.basename(path) not in ("_index.md", "index.md")

def upsert_frontmatter(txt, fields):
    if txt.startswith("---"):
        end = txt.find("\n---", 3)
        if end != -1:
            head = txt[3:end].strip("\n")
            rest = txt[end+4:]
            kept = [l for l in head.splitlines()
                    if not any(re.match(rf"^{re.escape(k)}\s*:", l) for k in STRIP_KEYS)]
            for k, v in fields.items():
                kept.append(f"{k}: {v}")
            return "---\n" + "\n".join(kept) + "\n---" + rest
    fm = "---\n" + "\n".join(f"{k}: {v}" for k, v in fields.items()) + "\n---\n"
    return fm + txt

def strip_managed(txt):
    if not txt.startswith("---"):
        return txt
    end = txt.find("\n---", 3)
    if end == -1:
        return txt
    head = txt[3:end].rstrip("\n")
    rest = txt[end+4:]
    kept = [l for l in head.splitlines()
            if not any(re.match(rf"^{re.escape(k)}\s*:", l) for k in STRIP_KEYS)]
    return "---\n" + "\n".join(kept) + "\n---" + rest

def all_pages():
    if PATHS:
        out = []
        for p in PATHS:
            ap = p if os.path.isabs(p) else os.path.join(VAULT, p)
            if os.path.isfile(ap) and is_content_page(ap):
                out.append(ap)
        return out
    # raw FIRST so raw pages get their managed dates written before wiki pages
    # (which may source them) are resolved within the same single pass.
    pages = glob.glob(os.path.join(RAW, "**", "*.md"), recursive=True)
    pages += glob.glob(os.path.join(WIKI, "**", "*.md"), recursive=True)
    return [p for p in pages if is_content_page(p)]

def do_revert():
    n = 0
    for p in all_pages():
        _, txt = read_frontmatter(p)
        new = strip_managed(txt)
        if new != txt:
            with open(p, "w", encoding="utf-8") as f:
                f.write(new)
            n += 1
    print(f"REVERTED managed keys from {n} pages")

def resolve_page(p):
    """Return (fields_dict, confidence, mixed_era) or (None, None, None)."""
    is_raw = p.startswith(RAW + os.sep)
    fm, txt = read_frontmatter(p)
    if is_raw:
        # a date/range in the filename wins outright (high confidence). Resolved
        # here too — not just in file_content_date — so a YYYY-YYYY range can set
        # a multi-year date_span and the era-mixing flag.
        fd = filename_date(os.path.basename(p))
        if fd:
            date, span, conf = fd
            return {"date": date, "date_span": span, "date_confidence": conf}, conf, ("–" in span)
        rel = os.path.relpath(p, VAULT)
        r = file_content_date(p, rel, skip_date_field=True)
        if not r:
            d = norm_date(os.path.splitext(os.path.basename(p))[0])
            r = (d[0], "medium") if d else None
        if not r:
            r = body_date(txt)   # low-confidence prose-date fallback (raw only)
        if not r:
            # last resort: pure sync timestamp (e.g. Confluence `fetched`)
            for fld in SYNC_FIELDS:
                if fm.get(fld):
                    d = norm_date(fm[fld])
                    if d:
                        r = (d[0], "low"); break
        if not r:
            return None, None, None
        date, conf = r
        return {"date": date, "date_span": date[:4], "date_confidence": conf}, conf, False
    # wiki page: aggregate linked sources
    dates = list(page_source_dates(txt))
    if not dates:
        title = os.path.splitext(os.path.basename(p))[0]
        d = norm_date(title) if YEAR.search(title) else None
        if d:
            dates = [(d[0], "medium")]
        else:
            return None, None, None
    only = [d for d, _ in dates]
    latest, earliest = max(only), min(only)
    ly, ey = latest[:4], earliest[:4]
    span = ly if ly == ey else f"{ey}–{ly}"
    conf = max((c for d, c in dates if d == latest), key=lambda c: CONF[c])
    return {"date": latest, "date_span": span, "date_confidence": conf}, conf, (ly != ey)

def main():
    if REVERT:
        do_revert(); return
    pages = all_pages()
    stats = Counter(); conf_dist = Counter(); span_mix = 0
    examples = []; unresolved = []
    for p in pages:
        fields, conf, mixed = resolve_page(p)
        scope = "raw" if p.startswith(RAW + os.sep) else "wiki"
        if not fields:
            stats[f"{scope}_no_date"] += 1
            unresolved.append(os.path.relpath(p, VAULT))
            continue
        stats[f"{scope}_resolved"] += 1
        conf_dist[conf] += 1
        if mixed:
            span_mix += 1
        if APPLY:
            _, txt = read_frontmatter(p)
            new_txt = upsert_frontmatter(txt, fields)
            if new_txt != txt:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(new_txt)
        if scope == "wiki" and len(examples) < 8:
            examples.append((os.path.relpath(p, VAULT), fields))

    print(f"{'APPLIED' if APPLY else 'DRY-RUN'} — total pages: {len(pages)}")
    print(f"  wiki resolved : {stats['wiki_resolved']}   wiki no-date : {stats['wiki_no_date']}")
    print(f"  raw  resolved : {stats['raw_resolved']}   raw  no-date : {stats['raw_no_date']}")
    print(f"  era-mixing (wiki span>1yr): {span_mix}")
    print(f"  confidence dist : {dict(conf_dist)}")
    print("\nExamples (wiki):")
    for rel, fl in examples:
        print(f"  {rel}\n      {fl}")
    outdir = os.path.join(VAULT, ".wiki-scratch")
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, "wiki-undated-pages.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(unresolved))
    print(f"\nUnresolved pages ({len(unresolved)}) listed in: {os.path.relpath(out, VAULT)}")

if __name__ == "__main__":
    main()
