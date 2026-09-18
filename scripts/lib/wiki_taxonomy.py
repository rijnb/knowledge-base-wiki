"""Phase 3 — turn the flat tag inventory into a curated hierarchical taxonomy.

Two LLM steps around three deterministic ones:

1. **namespaces** (1 call, sonnet) — propose the top-level namespace list from
   the most-used tags. One call, because every later chunk must map into the
   *same* list or the result is 38 private dialects.
2. **mapping** (~38 calls, sonnet) — map every tag to `namespace/term`, or to
   DROP. Chunked to bound reply length; checkpointed per chunk.
3. **collapse_rare** (deterministic) — a depth-3 tag covering ≤2 notes folds
   into its parent. Deliberately not asked of the model: hand-mapping thousands
   of rows overruns the reply budget and comes back empty.
4. **merge_cross_namespace** (deterministic) — the same final term at the same
   depth under two namespaces folds onto the more-used one, because
   `map/security` and `sw/security` are one concept split in half.
5. **resolve** — chain the tables, with cycle protection.

The model never writes `config/tags.md`. It proposes; a human approves.
"""

import datetime
import re
from collections import Counter
from typing import Iterable, Sequence

from .wiki_tags import InventoryRow, YEAR_TAG_RE, valid_tag


# Chunk size bounds the reply, not the prompt: a chunk must come back as one
# line per tag, and long replies are where truncation and drift start.
CHUNK_SIZE = 120

# How many of the most-used tags inform the namespace proposal. Enough to cover
# the vault's real subject matter, small enough for one call.
NAMESPACE_SAMPLE = 300

# A depth-3 tag this rare is noise; fold it into its parent.
RARE_MAX = 2

DROP = "DROP"

# Terms that carry no meaning on their own, so a shared one across namespaces is
# NOT a shared concept. `merge_cross_namespace` must leave these alone: folding
# on the term would collapse `ai/general`, `map/general` and `security/general`
# into whichever namespace happened to be largest, which is how 1880 notes'
# worth of correct mappings were once silently merged into `automotive/general`.
GENERIC_TERMS = frozenset({
    "general", "generic", "other", "others", "misc", "miscellaneous",
    "various", "overview", "core", "common", "basics", "intro", "introduction",
})

# Namespaces the model may never invent members of, per the plan's decision 8:
# wikilinks already index people and companies, and a tag index of proper names
# is not a taxonomy.
CLOSED_NAMESPACES = ("people", "person", "company", "companies")

# Also rejected, decided at the namespace gate on 2026-09-17:
#   `competition` — a competitor is a company; decision 24 drops pure vendors
#     and files a customer programme under `project` instead.
#   `concept` — a catch-all that competes with every domain namespace for the
#     same tags. A concept belongs under its domain: `automotive/adas`.
BANNED_NAMESPACES = CLOSED_NAMESPACES + ("competition", "concept", "concepts")

_MAPPING_LINE_RE = re.compile(r"^\s*(?:\[\d+\]\s*|\d+[.:]\s*)?(\S.*?)(?:\t+| {2,}| -> )(\S.*?)\s*$")
_NAMESPACE_LINE_RE = re.compile(r"^\s*(?:[-*]\s*)?`?([a-z][a-z0-9-]{1,30})`?\s*(?:[\t:—-]\s*(.*))?$")


# --------------------------------------------------------------------------- #
# Step 1 — namespaces
# --------------------------------------------------------------------------- #

def namespace_prompt(rows: Sequence[InventoryRow], sample: int = NAMESPACE_SAMPLE) -> str:
    """Ask for the top-level namespace list, once, from the most-used tags."""
    top = [r for r in rows if r.declared_count > 0][:sample]
    listing = "\n".join(
        f"{r.tag}\t{r.declared_count}"
        + (f"\twiki:{','.join(r.wiki_types)}" if r.wiki_types else "")
        for r in top
    )
    return "\n".join([
        "You are designing the top-level namespace list for the tag vocabulary of a",
        "work knowledge base about maps, navigation, automotive software and the",
        "engineering organisation that builds them.",
        "",
        "Below are the most-used tags in the vault today, as `tag<TAB>note count`",
        "with the wiki topic type of a same-named page where one exists. This",
        "vocabulary is FLAT and that is exactly the problem: every tag is a single",
        "segment. You are not copying it, you are replacing its top level.",
        "",
        listing,
        "",
        "Output a list of 15 to 25 NAMESPACES. Rules:",
        "- A namespace is a high-level concept that many tags sit under. Lowercase,",
        "  one word (hyphens allowed). Never a proper noun, never a person, never a",
        "  company.",
        "- Together they must cover the subject matter above with little left over.",
        "- Include namespaces for proper nouns: a product/system/project/standard",
        "  named in the notes must have somewhere to live.",
        "- Do NOT propose `people`, `person`, `company` or `companies`. Wikilinks",
        "  already index those and they are not wanted as tags.",
        "- Do NOT propose `competition`: a competitor is a company, and a customer",
        "  programme belongs under a project namespace instead.",
        "- Do NOT propose `concept`. It is a catch-all that competes with every",
        "  domain namespace for the same tags; a concept belongs under its domain.",
        "- Distinguish a technical system built in-house from a product that was",
        "  marketed and sold, and say so in the meanings.",
        "- `year` already exists (year/2022 and such) — include it unchanged.",
        "",
        "Reply with one namespace per line, nothing else:",
        "<namespace><TAB><one-line meaning>",
        "No preamble, no commentary, no markdown, no numbering.",
    ])


def parse_namespaces(reply: str | None) -> dict[str, str]:
    """Parse the namespace reply into {namespace: meaning}, dropping closed ones."""
    out: dict[str, str] = {}
    for line in (reply or "").splitlines():
        line = line.strip()
        if not line or line.lower().startswith(("here", "namespace", "output")):
            continue
        match = _NAMESPACE_LINE_RE.match(line)
        if not match:
            continue
        name = match.group(1)
        if name in BANNED_NAMESPACES or "/" in name:
            continue
        out.setdefault(name, (match.group(2) or "").strip())
    return out


# --------------------------------------------------------------------------- #
# Step 2 — mapping
# --------------------------------------------------------------------------- #

def mapping_prompt(rows: Sequence[InventoryRow], namespaces: dict[str, str]) -> str:
    """Ask for `old -> namespace/term` for one chunk of tags."""
    vocabulary = "\n".join(f"{name}\t{meaning}" for name, meaning in namespaces.items())
    listing = "\n".join(
        f"{r.tag}\t{r.declared_count}"
        + (f"\twiki:{','.join(r.wiki_types)}" if r.wiki_types else "")
        + (f"\tNOTE:{r.blind}" if r.blind else "")
        for r in rows
    )
    return "\n".join([
        "You are converting a flat tag vocabulary into a hierarchical one.",
        "",
        "The approved NAMESPACES, with their meanings:",
        vocabulary,
        "",
        "Below are tags to map, as `old tag<TAB>note count`, sometimes with the wiki",
        "topic type of a same-named page (a strong hint: a `wiki:systems` match is a",
        "system, `wiki:projects` a project, `wiki:competition` a company or customer",
        "programme) and sometimes a NOTE about why Obsidian rejects the tag today.",
        "",
        listing,
        "",
        "For each tag output the replacement. Rules:",
        "- The new tag is `namespace/term` or `namespace/term/term`, where the",
        "  namespace is one of the list above, copied exactly. Two segments is the",
        "  norm; three is the exception for a genuine sub-distinction.",
        "- NEVER one segment. NEVER four.",
        "- Lowercase, hyphens inside a segment, never underscores or spaces.",
        "- Keep the term recognisable: `dataspec-live` stays `dataspec-live`, it does not",
        "  become `dataspec_live` or `dataspeclive`.",
        "- A proper noun keeps its name and gains a namespace: `alpha` becomes",
        "  something like `project/alpha` or `system/alpha` — whichever fits.",
        "- A tag already shaped `year/2022` is output unchanged.",
        "- **One home per term.** Never file the same term under two namespaces:",
        "  if `dataspec` belongs under `standard`, it is `standard/dataspec` everywhere and",
        "  never also `map/dataspec`. Pick the single best namespace and commit to it.",
        "- There is deliberately no `concept` namespace. A concept goes under the",
        "  domain it belongs to — `automotive/adas`, not `concept/adas`.",
        "",
        f"Output `{DROP}` instead of a replacement when the tag is:",
        "- a person's name (`jane.doe`, `john.smith`),",
        "- a bare company name that is only a vendor or competitor — BUT a customer",
        "  PROGRAMME keeps its name under a project namespace (`acme` and `globex` are",
        "  programmes the notes are about, not merely companies),",
        "- so generic in this vault that it carries no signal: `megacorp`,",
        "  `engineering`, `external`.",
        "",
        "Reply with exactly one line per tag above, in the same order, nothing else:",
        "<old tag><TAB><new tag or DROP>",
        "No preamble, no commentary, no markdown, no numbering, no blank lines.",
    ])


def parse_mapping(reply: str | None, expected: Iterable[str]) -> dict[str, str]:
    """Parse `old<TAB>new` lines, keeping only tags that were asked about.

    Lenient by design: a malformed line is dropped, not raised on, and the tag
    it referred to simply stays unmapped so a later re-run can pick it up.
    """
    wanted = set(expected)
    out: dict[str, str] = {}
    for line in (reply or "").splitlines():
        if not line.strip():
            continue
        match = _MAPPING_LINE_RE.match(line.rstrip())
        if not match:
            continue
        old, new = match.group(1).strip().lstrip("#"), match.group(2).strip()
        if old not in wanted:
            continue
        new = new.strip("`").lstrip("#").strip()
        if new.upper() == DROP:
            out[old] = DROP
        elif valid_tag(new) and new.split("/")[0] not in BANNED_NAMESPACES:
            out[old] = new
    return out


# --------------------------------------------------------------------------- #
# Steps 3-4 — deterministic consolidation
# --------------------------------------------------------------------------- #

def collapse_rare(mapping: dict[str, str], counts: dict[str, int],
                  rare_max: int = RARE_MAX) -> dict[str, str]:
    """Fold a depth-3 target covering `rare_max` notes or fewer into its parent."""
    weight: Counter = Counter()
    for old, new in mapping.items():
        if new != DROP:
            weight[new] += counts.get(old, 0)
    out: dict[str, str] = {}
    for new, total in weight.items():
        if new.count("/") == 2 and total <= rare_max and not YEAR_TAG_RE.match(new):
            out[new] = new.rsplit("/", 1)[0]
    return out


def merge_cross_namespace(mapping: dict[str, str], counts: dict[str, int]) -> dict[str, str]:
    """Candidates where the same final term appears under two namespaces.

    **Reported, not applied by default** (see `build_remap`'s
    `merge_across_namespaces`). The original "one home per term" rule assumed a
    shared term meant a shared concept, and on this vault it mostly did not:
    it folded `ai/safety` into `security/safety` (75 notes — AI safety is not
    functional safety), `business/model` into `ai/model`, `business/development`
    into `process/development`, and `data/quality` and `map/quality` into
    `process/quality`. The namespace is usually what disambiguates the term, so
    the same term under two namespaces is legitimate and these are suggestions
    for a human, not arithmetic.
    """
    weight: Counter = Counter()
    for old, new in mapping.items():
        if new != DROP:
            weight[new] += counts.get(old, 0)
    groups: dict[tuple[str, int], list[str]] = {}
    for new in weight:
        if YEAR_TAG_RE.match(new):
            continue
        term = new.rsplit("/", 1)[-1]
        if term in GENERIC_TERMS:
            # `ai/general` and `map/general` are two different subjects; only
            # the namespace means anything, so there is nothing to merge.
            continue
        groups.setdefault((term, new.count("/")), []).append(new)
    out: dict[str, str] = {}
    for candidates in groups.values():
        if len(candidates) < 2:
            continue
        winner = max(candidates, key=lambda t: (weight[t], t))
        for loser in candidates:
            if loser != winner:
                out[loser] = winner
    return out


def _singular(term: str) -> str:
    """Crude English de-pluralisation, only for grouping lexical variants."""
    for suffix, replacement in (("ies", "y"), ("sses", "ss"), ("shes", "sh"),
                                ("ches", "ch"), ("xes", "x"), ("s", "")):
        if term.endswith(suffix) and len(term) - len(suffix) >= 3:
            return term[:-len(suffix)] + replacement
    return term


def _lexical_key(tag: str) -> tuple[str, str]:
    namespace, term = tag.split("/", 1)
    return namespace, _singular(term.replace("-", "").replace(".", ""))


def merge_lexical_variants(mapping: dict[str, str], counts: dict[str, int]) -> dict[str, str]:
    """Fold spelling variants of one term within a namespace onto the most-used.

    `system/alpha-map` -> `system/alphamap`, `map/hd-maps` and `map/hdmap`
    -> `map/hd-map`. Purely mechanical: differing only by hyphens, dots or an
    English plural is not a difference in meaning.
    """
    weight: Counter = Counter()
    for old, new in mapping.items():
        if new != DROP:
            weight[new] += counts.get(old, 0)
    groups: dict[tuple[str, str], list[str]] = {}
    for tag in weight:
        if YEAR_TAG_RE.match(tag) or "/" not in tag:
            continue
        groups.setdefault(_lexical_key(tag), []).append(tag)
    out: dict[str, str] = {}
    for candidates in groups.values():
        if len(candidates) < 2:
            continue
        winner = max(candidates, key=lambda t: (weight[t], t))
        for loser in candidates:
            if loser != winner:
                out[loser] = winner
    return out


# --------------------------------------------------------------------------- #
# Step 2b — per-namespace term merge (LLM)
# --------------------------------------------------------------------------- #

# Below this many tags a namespace is not worth a call.
TERM_PASS_MIN = 12
TERM_CHUNK = 120


def namespace_term_chunks(
    canonical: Sequence[tuple[str, int, int]],
    min_tags: int = TERM_PASS_MIN,
    chunk: int = TERM_CHUNK,
) -> list[tuple[str, list[tuple[str, int]]]]:
    """Split the canonical tags into (namespace, [(tag, notes), ...]) work units."""
    by_namespace: dict[str, list[tuple[str, int]]] = {}
    for tag, notes, _sources in canonical:
        if YEAR_TAG_RE.match(tag) or "/" not in tag:
            continue
        by_namespace.setdefault(tag.split("/")[0], []).append((tag, notes))
    units: list[tuple[str, list[tuple[str, int]]]] = []
    for namespace in sorted(by_namespace, key=lambda ns: -len(by_namespace[ns])):
        tags = sorted(by_namespace[namespace], key=lambda r: (-r[1], r[0]))
        if len(tags) < min_tags:
            continue
        for i in range(0, len(tags), chunk):
            units.append((namespace, tags[i:i + chunk]))
    return units


def terms_prompt(namespace: str, meaning: str, tags: Sequence[tuple[str, int]]) -> str:
    """Ask which tags inside one namespace are the same concept."""
    listing = "\n".join(f"{tag}\t{notes}" for tag, notes in tags)
    return "\n".join([
        f"You are consolidating the `{namespace}` part of a knowledge-base tag",
        f"vocabulary. `{namespace}` means: {meaning or namespace}.",
        "",
        "Below are its tags, as `tag<TAB>number of notes carrying it`. There are far",
        "too many: the same concept appears under several near-identical names, and",
        "many tags sit on a single note.",
        "",
        listing,
        "",
        "Find the tags that mean the SAME THING and merge them. Rules:",
        "- Merge synonyms, near-synonyms, abbreviations and their expansions, and",
        "  singular/plural pairs onto ONE surviving tag.",
        "- Prefer the tag with the most notes as the survivor. Where a rarely-used",
        "  tag is clearly a narrower case of a common one, merge it into the common",
        "  one.",
        "- The survivor must be one of the tags listed above, copied exactly.",
        f"- Both sides must stay inside `{namespace}/`. Never move a tag to another",
        "  namespace here.",
        "- A genuinely distinct concept is left alone — do not merge things that",
        "  merely sound related. Precision matters more than a small list.",
        "",
        "Reply with one line per MERGE only — omit any tag that should stay as it",
        "is. Nothing else:",
        "<tag to retire><TAB><surviving tag>",
        "No preamble, no commentary, no markdown, no numbering, no blank lines.",
    ])


def parse_merges(reply: str | None, known: Iterable[str]) -> dict[str, str]:
    """Parse `retire<TAB>survivor` lines, keeping only sane same-namespace pairs."""
    valid = set(known)
    out: dict[str, str] = {}
    for line in (reply or "").splitlines():
        if not line.strip():
            continue
        match = _MAPPING_LINE_RE.match(line.rstrip())
        if not match:
            continue
        old = match.group(1).strip().strip("`").lstrip("#")
        new = match.group(2).strip().strip("`").lstrip("#")
        if old not in valid or new not in valid or old == new:
            continue
        if old.split("/")[0] != new.split("/")[0]:
            continue
        out[old] = new
    # A chain (a->b, b->c) is fine — `resolve` follows it — but a 2-cycle is
    # not: drop the weaker direction rather than let it oscillate.
    return {old: new for old, new in out.items() if out.get(new) != old or old < new}


def resolve(tag: str, *tables: dict[str, str]) -> str:
    """Chain `tag` through the tables until it stops moving. Cycle-safe."""
    seen = {tag}
    current = tag
    while True:
        nxt = None
        for table in tables:
            if current in table:
                nxt = table[current]
                break
        if nxt is None or nxt == current or nxt in seen:
            return current
        seen.add(nxt)
        current = nxt
        if current == DROP:
            return DROP


def _note_weights(remap: dict[str, str], counts: dict[str, int]) -> Counter:
    weight: Counter = Counter()
    for old, new in remap.items():
        if new != DROP:
            weight[new] += counts.get(old, 0)
    return weight


def build_remap(
    mapping: dict[str, str],
    counts: dict[str, int],
    *,
    term_merges: dict[str, str] | None = None,
    drop_singletons: bool = False,
    overrides: dict[str, str] | None = None,
    merge_across_namespaces: bool = False,
) -> tuple[dict[str, str], dict]:
    """Apply every consolidation pass in order and return the final old->new remap.

    Order matters. Lexical and term merges run first so that tags pooling onto
    one survivor are counted together; only then is it fair to ask whether a
    tag is rare enough to collapse or to drop.
    """
    lexical = merge_lexical_variants(mapping, counts)
    early = [t for t in (lexical, term_merges or {}) if t]
    interim = {
        old: (DROP if new == DROP else resolve(new, *early))
        for old, new in mapping.items()
    }
    collapsed = collapse_rare(interim, counts)
    candidates = merge_cross_namespace(interim, counts)
    merged = candidates if merge_across_namespaces else {}
    remap = {
        old: (DROP if new == DROP else resolve(new, collapsed, merged))
        for old, new in interim.items()
    }

    dropped_thin = 0
    if drop_singletons:
        # Computed only now, on the pooled counts: a tag that looked like a
        # singleton before merging may carry plenty of notes after it.
        thin = {tag for tag, notes in _note_weights(remap, counts).items() if notes <= 1}
        dropped_thin = len(thin)
        remap = {old: (DROP if new in thin else new) for old, new in remap.items()}

    # Overrides are applied last and win outright — they are the human's
    # corrections at the gate, so no automatic pass may undo them (a one-note
    # `project/globex` survives the singleton drop because someone asked for it).
    applied = 0
    for old, new in (overrides or {}).items():
        if old in remap and remap[old] != new:
            applied += 1
        remap[old] = new

    stats = {
        "mapped": sum(1 for v in remap.values() if v != DROP),
        "dropped": sum(1 for v in remap.values() if v == DROP),
        "merged_lexical": len(lexical),
        "merged_terms": len(term_merges or {}),
        "collapsed_rare": len(collapsed),
        "merged_cross_namespace": len(merged),
        "cross_namespace_candidates": len(candidates),
        "dropped_single_note": dropped_thin,
        "overrides_applied": applied,
        "canonical": len({v for v in remap.values() if v != DROP}),
    }
    return remap, stats


_REVIEW_ROW_RE = re.compile(r"^\|\s*`([^`]+)`\s*\|(.*?)\|\s*\d+\s*\|\s*$")
_REVIEW_PREFIX_RE = re.compile(r"^(?:should\s+be|use|->|=>|:)\s*", re.I)


def parse_review_comments(text: str) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Read `!!` corrections out of a filed review table.

    The review markdown is the gate's interface, so a comment written next to a
    row is read back rather than transcribed by hand. A comment is either a full
    replacement tag, `DROP`, or a bare top-level — in which case the row's
    current term is re-parented under it, so `!! software` on
    `automotive/telematics` means `software/telematics` and on `automotive/ota`
    means `software/ota`, preserving the merge the term pass made.

    Returns (overrides, unresolved) where `unresolved` holds the rows whose
    comment could not be turned into a tag, for a human to look at.
    """
    overrides: dict[str, str] = {}
    unresolved: list[tuple[str, str]] = []
    for line in text.splitlines():
        match = _REVIEW_ROW_RE.match(line)
        if not match or "!!" not in match.group(2):
            continue
        old = match.group(1).strip()
        current, _, comment = match.group(2).partition("!!")
        current = current.strip().strip("*").strip("`").strip()
        instruction = _REVIEW_PREFIX_RE.sub("", comment.strip()).strip()
        # Tolerate the ways a hand-typed tag goes wrong: a stray leading slash,
        # spaces around the separator, backticks, a trailing full stop.
        instruction = instruction.strip("`").strip().lstrip("/").rstrip(".")
        instruction = re.sub(r"\s*/\s*", "/", instruction)
        if not instruction:
            continue
        if instruction.upper() == DROP:
            overrides[old] = DROP
            continue
        if "/" not in instruction:
            term = current.rsplit("/", 1)[-1] if "/" in current else current
            if not term or term == instruction:
                unresolved.append((old, comment.strip()))
                continue
            instruction = f"{instruction}/{term}"
        if valid_tag(instruction) and instruction.split("/")[0] not in BANNED_NAMESPACES:
            overrides[old] = instruction
        else:
            unresolved.append((old, comment.strip()))
    return overrides, unresolved


def load_overrides(path) -> dict[str, str]:
    """Read the gate's correction table: `old tag<TAB>new tag or DROP`.

    Hand-authored, and deliberately separate from the generated artefacts so
    re-running a phase never discards a decision made at the gate. `#` starts a
    comment.
    """
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = re.split(r"\t+| {2,}", line, maxsplit=1)
        if len(parts) != 2:
            continue
        old, new = parts[0].strip(), parts[1].strip()
        if not old or not new:
            continue
        if new.upper() == DROP:
            out[old] = DROP
        elif valid_tag(new) and new.split("/")[0] not in BANNED_NAMESPACES:
            out[old] = new
    return out


def canonical_table(remap: dict[str, str], counts: dict[str, int]) -> list[tuple[str, int, int]]:
    """(canonical tag, note count, number of old tags folded in), most-used first."""
    notes: Counter = Counter()
    sources: Counter = Counter()
    for old, new in remap.items():
        if new == DROP:
            continue
        notes[new] += counts.get(old, 0)
        sources[new] += 1
    return sorted(
        ((tag, notes[tag], sources[tag]) for tag in notes),
        key=lambda row: (-row[1], row[0]),
    )


def chunks(rows: Sequence[InventoryRow], size: int = CHUNK_SIZE) -> list[list[InventoryRow]]:
    """Split into chunks, most-used tags first so trouble shows up early."""
    ordered = sorted(rows, key=lambda r: (-r.declared_count, r.tag))
    return [ordered[i:i + size] for i in range(0, len(ordered), size)]


def format_tags_md(canonical: Sequence[tuple[str, int, int]],
                   namespaces: dict[str, str], existing: set[str]) -> str:
    """Render a `config/tags.md` proposal, grouped by namespace.

    A proposal only: it is written to the scratch dir for a human to review and
    move into place. Nothing in this pipeline writes `config/tags.md` itself.
    """
    by_namespace: dict[str, list[tuple[str, int, int]]] = {}
    for tag, notes, sources in canonical:
        by_namespace.setdefault(tag.split("/")[0], []).append((tag, notes, sources))
    order = sorted(by_namespace, key=lambda ns: -sum(r[1] for r in by_namespace[ns]))

    lines = [
        "---",
        "date: " + datetime.date.today().isoformat(),
        "---",
        "# Tags",
        "",
        "The approved tag vocabulary for this vault. Proposed by "
        "`scripts/wiki-tags.py --phase taxonomy`; review before use.",
        "",
        "## How to use it",
        "",
        "When tagging a note, pick from this list. If nothing here fits, **add the",
        "tag to this list first**, then use it — so this file stays the single",
        "source of truth and `wiki-doctor` can check against it.",
        "",
        "Removing a tag from this list does not remove it from notes: the tagging",
        "scripts never strip a tag. That needs a remap run.",
        "",
        "## Rules",
        "",
        "- lowercase; `namespace/term` or `namespace/term/term`. Never 1 segment, never 4.",
        "- hyphens inside a segment (`dataspec-live`), never underscores or spaces.",
        "- English, always.",
        "- Never a person's name. Never a bare company name — a customer programme",
        "  is `project/<name>`.",
        "- The one exempt pattern is a year tag, shaped year/ plus four digits.",
        "",
        f"{len(canonical)} tags in {len(order)} namespaces. A `*` marks a tag that",
        "was already in use in the vault before this exercise.",
        "",
    ]
    for namespace in order:
        lines.append(f"## {namespace}")
        lines.append("")
        if namespace in namespaces and namespaces[namespace]:
            lines.append(f"_{namespaces[namespace]}_")
            lines.append("")
        for tag, notes, _sources in sorted(by_namespace[namespace], key=lambda r: (-r[1], r[0])):
            star = " *" if tag in existing else ""
            lines.append(f"- `{tag}`{star}  <!-- {notes} notes -->")
        lines.append("")
    return "\n".join(lines)
