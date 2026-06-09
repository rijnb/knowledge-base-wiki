#!/usr/bin/env python3
"""
Supersession lint + review queue for the Wiki.

Two jobs:
  1. INTEGRITY — validate existing `superseded_by` / `supersedes` frontmatter:
       - dangling: target page does not exist
       - reciprocity: superseded_by target lacks the matching `supersedes` back-link
       - cycles: A -> B -> ... -> A
  2. REVIEW QUEUE — find pages whose BODY uses supersession language
     ("superseded by", "replaced by", "deprecated in favour of", ...) but have
     no `superseded_by` field yet, and propose a guessed successor (a WikiLink
     near the phrase). This is REVIEW-ONLY — nothing is written to pages.

Run from the vault root (vault auto-detected).

Usage:
  python3 scripts/system/wiki-supersession-lint.py            # report + write queue
  python3 scripts/system/wiki-supersession-lint.py --quiet    # summary only
"""
import os, re, sys, glob

def _find_vault(start):
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
QUIET = "--quiet" in sys.argv

# Pages the reviewer marked "not a supersession" — kept out of the review queue.
IGNORE_FILE = os.path.join(VAULT, ".wiki-scratch", "supersession-ignore.txt")
def _load_ignore():
    try:
        with open(IGNORE_FILE, encoding="utf-8") as f:
            return {ln.strip() for ln in f if ln.strip() and not ln.startswith("#")}
    except FileNotFoundError:
        return set()
IGNORE = _load_ignore()

WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")
# Past-tense / explicit phrases only — avoids gerund process-nouns like
# "service onboarding/decommissioning" that are not page supersessions.
SUPERSESSION = re.compile(
    r"\b(superseded by|replaced by|succeeded by|deprecated in favou?r of|"
    r"retired in favou?r of|phased out in favou?r of|decommissioned\b|"
    r"sunset\b|migrated to|renamed to)\b", re.I)
TOPIC_PRIORITY = {"systems": 0, "decisions": 1, "projects": 2, "concepts": 3,
                  "competition": 4, "problems": 5, "people": 6}

def read_fm(path):
    try:
        txt = open(path, encoding="utf-8").read()
    except Exception:
        return {}, ""
    if not txt.startswith("---"):
        return {}, txt
    end = txt.find("\n---", 3)
    if end == -1:
        return {}, txt
    block = txt[3:end]
    fm = {}
    lines = block.splitlines()
    i = 0
    while i < len(lines):
        m = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", lines[i])
        if m:
            key, val = m.group(1).lower(), m.group(2).strip()
            if val == "":  # possible YAML list
                items = []
                j = i + 1
                while j < len(lines) and re.match(r"^\s*-\s+", lines[j]):
                    items.append(re.sub(r"^\s*-\s+", "", lines[j]).strip())
                    j += 1
                if items:
                    fm[key] = items; i = j; continue
            fm[key] = val
        i += 1
    return fm, txt[end+4:]

def link_targets(val):
    """Extract wikilink target(s) from a frontmatter value (str or list)."""
    out = []
    vals = val if isinstance(val, list) else [val]
    for v in vals:
        m = WIKILINK.search(v)
        out.append((m.group(1) if m else v).split("|")[0].strip())
    return [t for t in out if t]

# build page index: basename(lower) -> relpath, and relpath set
PAGES = {}
REL = {}
for p in glob.glob(os.path.join(WIKI, "**", "*.md"), recursive=True):
    rel = os.path.relpath(p, VAULT)
    REL[rel] = p
    name = os.path.splitext(os.path.basename(p))[0].lower()
    PAGES.setdefault(name, []).append(rel)

def resolve(target):
    """Resolve a wikilink target (vault-relative or bare name) to a relpath, or None."""
    t = target.strip()
    # strip .md if present
    cand = t if t.endswith(".md") else t + ".md"
    if cand in REL:
        return cand
    if t.startswith("wiki/") and (t + ".md") in REL:
        return t + ".md"
    # bare name
    base = os.path.splitext(os.path.basename(t))[0].lower()
    hits = PAGES.get(base, [])
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        return hits  # ambiguous
    return None

def main():
    superseded = {}   # relpath -> [target relpaths/raw targets]
    supersedes = {}    # relpath -> [target relpaths]
    dangling, ambiguous, missing_recip, cycles = [], [], [], []
    candidates = []

    for p in glob.glob(os.path.join(WIKI, "**", "*.md"), recursive=True):
        rel = os.path.relpath(p, VAULT)
        if os.path.basename(p) in ("_index.md", "index.md"):
            continue
        fm, body = read_fm(p)

        if "superseded_by" in fm:
            tgts = link_targets(fm["superseded_by"])
            resolved = []
            for t in tgts:
                r = resolve(t)
                if r is None:
                    dangling.append((rel, t))
                elif isinstance(r, list):
                    ambiguous.append((rel, t, r))
                else:
                    resolved.append(r)
            superseded[rel] = resolved
        if "supersedes" in fm:
            supersedes[rel] = [r for t in link_targets(fm["supersedes"])
                               for r in [resolve(t)] if isinstance(r, str)]

        # review queue: body language but no superseded_by field (and not ignored)
        if "superseded_by" not in fm and rel not in IGNORE:
            for ln in body.splitlines():
                m = SUPERSESSION.search(ln)
                if not m:
                    continue
                # guessed successor = first wikilink after the phrase on this line
                after = ln[m.end():]
                gm = WIKILINK.search(after)
                guess = gm.group(1).split("|")[0].strip() if gm else ""
                topic = rel.split("/")[1] if rel.startswith("wiki/") and "/" in rel[5:] else "?"
                candidates.append((rel, m.group(1), guess, ln.strip()[:160], topic))
                break  # one candidate per page is enough for review
    # most-actionable first: has a guessed successor, then by topic relevance
    candidates.sort(key=lambda c: (c[2] == "", TOPIC_PRIORITY.get(c[4], 9), c[0]))

    # reciprocity: every superseded_by target should have supersedes back to source
    for src, tgts in superseded.items():
        for t in tgts:
            back = supersedes.get(t, [])
            if src not in back:
                missing_recip.append((src, t))

    # cycle detection over superseded_by graph
    def has_cycle(start):
        seen, stack = set(), [start]
        while stack:
            n = stack.pop()
            if n == start and len(seen) > 0:
                return True
            if n in seen:
                continue
            seen.add(n)
            stack.extend(superseded.get(n, []))
        return False
    for src in superseded:
        chain, n, ok = [src], src, True
        while True:
            nxt = superseded.get(n, [])
            if not nxt:
                break
            n = nxt[0]
            if n in chain:
                cycles.append(" -> ".join(chain + [n])); break
            chain.append(n)
            if len(chain) > 50:
                break

    # ---- report ----
    print("Supersession lint")
    print(f"  pages with superseded_by : {len(superseded)}")
    print(f"  pages with supersedes    : {len(supersedes)}")
    print(f"  dangling targets         : {len(dangling)}")
    print(f"  ambiguous targets        : {len(ambiguous)}")
    print(f"  missing reciprocal link  : {len(missing_recip)}")
    print(f"  cycles                   : {len(cycles)}")
    print(f"  ignored (reviewer-marked): {len(IGNORE)}")
    print(f"  review-queue candidates  : {len(candidates)}")

    if not QUIET:
        for label, items, fmt in [
            ("DANGLING superseded_by (target not found)", dangling,
             lambda x: f"    {x[0]}  ->  {x[1]}"),
            ("AMBIGUOUS target (multiple matches)", ambiguous,
             lambda x: f"    {x[0]}  ->  {x[1]}  ?  {x[2]}"),
            ("MISSING reciprocal supersedes", missing_recip,
             lambda x: f"    {x[1]} should add: supersedes: [[{x[0][:-3]}]]"),
            ("CYCLES", [(c,) for c in cycles], lambda x: f"    {x[0]}"),
        ]:
            if items:
                print(f"\n## {label} ({len(items)})")
                for it in items[:50]:
                    print(fmt(it))

    # write review queue as a reviewable markdown checklist
    outdir = os.path.join(VAULT, ".wiki-scratch")
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, "supersession-candidates.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("# Supersession review queue\n\n")
        f.write("Pages whose body suggests they were superseded but have no `superseded_by` "
                "field yet. Confirm each, then add `superseded_by` (old page) + reciprocal "
                "`supersedes` (successor). Nothing here was applied automatically.\n\n")
        with_guess = [c for c in candidates if c[2]]
        no_guess = [c for c in candidates if not c[2]]
        f.write(f"## Likely (guessed successor found) — {len(with_guess)}\n\n")
        for rel, phrase, guess, ctx, topic in with_guess:
            f.write(f"- [ ] **[[{rel[:-3]}]]** _( {topic} )_ — _{phrase}_ → guessed successor: `{guess}`"
                    f"\n      <sub>{ctx}</sub>\n")
        f.write(f"\n## Needs a successor (manual) — {len(no_guess)}\n\n")
        for rel, phrase, guess, ctx, topic in no_guess:
            f.write(f"- [ ] **[[{rel[:-3]}]]** _( {topic} )_ — _{phrase}_ → successor: _?_"
                    f"\n      <sub>{ctx}</sub>\n")
    print(f"\nReview queue ({len(candidates)}) written to: {os.path.relpath(out, VAULT)}")

if __name__ == "__main__":
    main()
