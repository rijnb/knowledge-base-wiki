"""Resolve wikilinks, markdown links, and (optionally) external URLs."""

import re
import urllib.error
import urllib.request
from pathlib import Path

from .links import CURLY_TO_STRAIGHT, is_external
from .paths import should_skip_md


KNOWN_EXTENSIONS = {".md", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".webp"}

# Characters that are often replaced by '_' when a title becomes a filename.
# Includes '_' itself (so file stems normalize the same as their original titles),
# plus straight/curly quotes and any non-ASCII codepoint.
_PROBLEMATIC_CHARS = re.compile(r'''[_:!#$%&*<>?/\\|'"]|[^\x00-\x7f]''')


def normalize_name(name: str) -> str:
    """Canonical form for fuzzy matching.

    Replaces '_' and chars typically substituted with '_' in filenames with a
    space, then collapses whitespace. This makes '[[foo: bar]]', '[[foo bar]]',
    '[[foo's bar?]]', '[[café]]', and files 'foo_ bar.md' / 'foo_s bar_.md' /
    'caf_.md' all map to the same key.
    """
    return re.sub(r'\s+', ' ', _PROBLEMATIC_CHARS.sub(' ', name)).strip().lower()


def build_normalized_index(root: Path) -> dict[str, list[Path]]:
    """Map normalize_name(stem) -> list of .md paths, for fuzzy wikilink matching."""
    index: dict[str, list[Path]] = {}
    for p in root.rglob("*.md"):
        if should_skip_md(p, root):
            continue
        key = normalize_name(p.stem)
        index.setdefault(key, []).append(p)
    return index


def find_normalized_match(target: str, root: Path, norm_index: dict[str, list[Path]]) -> "str | None":
    """Try to match a broken wikilink target by normalizing problematic characters.

    Returns the corrected link text (stem, or relative path if the original
    target included a directory) if exactly one file matches, else None.
    """
    candidate = Path(target)
    has_known_ext = candidate.suffix.lower() in KNOWN_EXTENSIONS
    name = candidate.stem if has_known_ext else candidate.name
    key = normalize_name(name)
    if not key:
        return None
    # If the target includes a directory prefix, restrict the search to that subdir.
    if candidate.parent != Path("."):
        subdir = root / candidate.parent
        if subdir.is_dir():
            for p in subdir.glob("*.md"):
                if normalize_name(p.stem) == key:
                    return str(candidate.parent / p.stem)
        return None
    # Vault-wide fuzzy match — only accept a unique result to avoid false fixes.
    matches = norm_index.get(key, [])
    if len(matches) == 1:
        return matches[0].stem
    return None


def find_whitespace_before_ext_match(
    target: str,
    root: Path,
    path_suffix_set: "set[str] | None" = None,
) -> "str | None":
    """If the broken link target has whitespace immediately before its extension
    (e.g. 'foo .pdf', 'docs/bar  .md'), strip that whitespace and check whether
    the resulting filename exists in the vault.

    Returns the corrected link text on a unique match, else None. The returned
    form preserves any directory component the original target had. For .md
    targets without a directory component, the bare stem is returned (matching
    Obsidian's wikilink convention).
    """
    candidate = Path(target)
    suffix = candidate.suffix
    if not suffix:
        return None
    stem = candidate.stem
    stripped_stem = stem.rstrip()
    if stripped_stem == stem or not stripped_stem:
        return None  # no trailing whitespace before extension
    fixed_name = stripped_stem + suffix
    has_known_ext = suffix.lower() in KNOWN_EXTENSIONS

    # Directory-qualified target: only accept a match at that exact subpath.
    if candidate.parent != Path("."):
        rel_fixed = candidate.parent / fixed_name
        if (root / rel_fixed).exists():
            return str(rel_fixed)
        for top in ("wiki", "raw"):
            if (root / top / rel_fixed).exists():
                return str(rel_fixed)
        if path_suffix_set is not None and str(rel_fixed) in path_suffix_set:
            return str(rel_fixed)
        return None

    # Bare-name target: search vault-wide via the suffix index when available,
    # else fall back to a glob. Require a unique match to avoid false fixes.
    if path_suffix_set is not None:
        if fixed_name in path_suffix_set:
            if has_known_ext and suffix.lower() == ".md":
                return Path(fixed_name).stem
            return fixed_name
        return None

    matches = [p for p in root.rglob(fixed_name) if p.is_file()]
    if len(matches) == 1:
        if has_known_ext and suffix.lower() == ".md":
            return matches[0].stem
        return fixed_name
    return None


def resolve_wikilink(
    target: str,
    root: Path,
    all_md_stems: dict[str, list[Path]],
    path_suffix_set: "set[str] | None" = None,
) -> bool:
    """
    Resolve an Obsidian wikilink against the vault root.
    Wikilinks can be:
      - a bare filename stem:    people/rijn-buve  →  <root>/people/rijn-buve.md
      - a full path (no ext):    wiki/concepts/foo →  <root>/wiki/concepts/foo.md
      - a full path with ext:    wiki/concepts/foo.md
    Also checks .png/.jpg/.jpeg/.gif/.svg/.pdf for embedded files.
    If the target has no recognized extension, .md is assumed (Obsidian default).

    [[x/y]] is valid if x/y is found anywhere under raw/ or wiki/ (any depth).
    [[x]] is valid if x is found anywhere under raw/ or wiki/.

    Returns True if the target resolves to an existing file.
    """
    candidate = Path(target)
    has_known_ext = candidate.suffix.lower() in KNOWN_EXTENSIONS

    # Try exact path first
    if (root / target).exists():
        return True

    # If no recognized extension, try appending .md and other known types.
    # This handles bare names like "my-note", paths like "wiki/concepts/foo",
    # and names with dots that aren't file extensions (e.g. "2024.05.15").
    # Also try appending .md when the target has a known extension but the exact
    # file doesn't exist — e.g. [[foo.png]] resolves to foo.png.md.
    if not has_known_ext:
        for ext in (".md", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".webp"):
            if (root / (target + ext)).exists():
                return True
    else:
        if (root / (target + ".md")).exists():
            return True

    # If the target contains a directory component (e.g. "x/y"), also search
    # under the top-level "wiki/" and "raw/" collections — a link [[x/y]] is
    # valid when wiki/x/y.md or raw/x/y.md exists, regardless of where the
    # linking file lives.
    if candidate.parent != Path("."):
        for top in ("wiki", "raw"):
            if (root / top / target).exists():
                return True
            if not has_known_ext:
                for ext in (".md", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".webp"):
                    if (root / top / (target + ext)).exists():
                        return True
            else:
                if (root / top / (target + ".md")).exists():
                    return True

    # Fuzzy match: bare stem against all known markdown files.
    # Only apply when the target has no directory component — a full-path target
    # like [[_resources/foo/bar.md]] must resolve by path, not by stem alone,
    # otherwise any file named bar.md anywhere in the vault would silence the error.
    # Use the full name as the lookup key when there is no recognized extension,
    # so that "v1.2" matches "v1.2.md" rather than looking up "v1".
    if candidate.parent == Path("."):
        stem = candidate.stem if has_known_ext else candidate.name
        if stem in all_md_stems:
            return True

    # Broad suffix search: [[x/y]] is valid if any file under raw/ or wiki/
    # has a path that ends with x/y (at any depth).  Handles cases like
    # [[_resources/foo/bar.pdf]] where the file lives at raw/notes/_resources/foo/bar.pdf,
    # and bare names like [[foo.pdf]] where the file lives at raw/notes/foo.pdf.
    if path_suffix_set is not None:
        # Strip a leading "./" that Obsidian sometimes emits for relative embeds,
        # then normalize curly quotes to straight so both sides match.
        normalized = target
        if normalized.startswith("./"):
            normalized = normalized[2:]
        normalized = normalized.translate(CURLY_TO_STRAIGHT)
        if normalized in path_suffix_set:
            return True
        if (normalized + ".md") in path_suffix_set:
            return True

    return False


def resolve_wikilink_to_path(target: str, root: Path, stem_index: dict[str, list[Path]]) -> "Path | None":
    """Resolve a wikilink target to an actual Path, or None if unresolvable or ambiguous."""
    candidate = Path(target)
    has_known_ext = candidate.suffix.lower() in KNOWN_EXTENSIONS

    exact = root / target
    if exact.exists():
        return exact

    if not has_known_ext:
        exact_md = root / (target + ".md")
        if exact_md.exists():
            return exact_md

    # If the target has a directory component, also look under wiki/ and raw/.
    if candidate.parent != Path("."):
        for top in ("wiki", "raw"):
            if (root / top / target).exists():
                return root / top / target
            if not has_known_ext:
                p = root / top / (target + ".md")
                if p.exists():
                    return p

    stem = candidate.stem if has_known_ext else candidate.name
    matches = stem_index.get(stem, [])
    if len(matches) == 1:
        return matches[0]
    return None  # not found or ambiguous


def resolve_mdlink(target: str, source_file: Path, root: Path, all_md_stems: dict[str, list[Path]]) -> bool:
    """Resolve a standard markdown relative link."""
    if is_external(target):
        return True  # handled separately

    # URL-decode basic percent-encoding (e.g. spaces as %20)
    try:
        from urllib.parse import unquote
        target = unquote(target)
    except Exception:
        pass

    p = (source_file.parent / target).resolve()
    if p.exists():
        return True

    # Also check target + ".md" — e.g. foo.png resolves to foo.png.md
    p_md = (source_file.parent / (target + ".md")).resolve()
    if p_md.exists():
        return True

    # Also try treating as root-relative
    p2 = (root / target).resolve()
    if p2.exists():
        return True

    p2_md = (root / (target + ".md")).resolve()
    if p2_md.exists():
        return True

    return False


def check_external(url: str, timeout: int) -> tuple[bool, str]:
    """Return (ok, reason). Performs a HEAD request, falls back to GET."""
    try:
        req = urllib.request.Request(url, method="HEAD")
        req.add_header("User-Agent", "wiki-lint-check/1.0")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status < 400, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        if e.code == 405:
            # HEAD not allowed — try GET
            try:
                req2 = urllib.request.Request(url, method="GET")
                req2.add_header("User-Agent", "wiki-lint-check/1.0")
                with urllib.request.urlopen(req2, timeout=timeout) as resp:
                    return resp.status < 400, f"HTTP {resp.status}"
            except Exception as e2:
                return False, str(e2)
        return False, f"HTTP {e.code} {e.reason}"
    except urllib.error.URLError as e:
        return False, str(e.reason)
    except Exception as e:
        return False, str(e)
