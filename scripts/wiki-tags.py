#!/usr/bin/env python3
"""
wiki-tags.py — Build and apply the curated tag vocabulary in config/tags.md.

Phases run one at a time and each is resumable. Dry run is the default: a phase
that writes needs --apply.

  0  inventory       The real tag inventory, from `obsidian tags` with phantom
                     parent aggregates stripped (Obsidian reports `#year` with
                     the summed count of every `year/*`, though no note declares
                     a bare `year`). Joins each tag against wiki/<type>/ pages,
                     which is the free namespace signal for the taxonomy phase.
                     No LLM. Writes .tags/inventory.tsv.

  1  escape          Rewrite stray inline hashtags as `\\#foo` so they stop
                     polluting the tag list. Targets are the tags Obsidian sees
                     that no note declares in frontmatter, minus the ancestors
                     of declared tags. Body only; frontmatter, fenced code and
                     inline code spans are never touched. No LLM.
     escape-revert   Undo the above from its backup, byte-for-byte or not at all.

  2  excerpts        Build the capped, PDF-free excerpt per note that the LLM
                     phases read. Prose first, then OCR callouts sampled spread
                     across the document. No LLM. Writes .tags/excerpts.jsonl.

  3a namespaces      ONE sonnet call proposing the top-level namespace list from
                     the most-used tags. Review it before spending on 3b, since
                     every chunk there maps into this list. Writes
                     .tags/namespaces.tsv; --apply replaces an existing list.

  3b taxonomy        Map every tag into those namespaces, ~38 sonnet calls,
                     chunked and checkpointed per chunk (safe to interrupt;
                     re-run resumes). Then two deterministic passes: fold rare
                     depth-3 tags into their parent, and merge the same term
                     across namespaces. Writes .tags/remap.tsv,
                     .tags/canonical.tsv and a .tags/tags.md proposal.
                     --limit N stops after N chunks.

  3c terms           Merge synonyms WITHIN each namespace, one sonnet call per
                     namespace chunk, checkpointed. This is the pass that makes
                     the list usable: mapping alone only adds a prefix, leaving
                     ~3900 tags. Also applies the free lexical-variant merge and
                     drops tags left covering a single note.

     apply-review    Read `!!` corrections out of a filed review table
                     (default INBOX/Tag Remap Review.md, or --out PATH) and
                     append them to .tags/overrides.tsv. A comment is a full
                     replacement tag, DROP, or a bare top-level — in which case
                     the row's current term is re-parented under it. No LLM.

     consolidate     Re-run only the deterministic passes over the existing
                     checkpoint and rewrite the outputs. No LLM, so a change to
                     the consolidation rules costs nothing to re-derive.

                     ==> HUMAN GATE: review remap rows covering >5 notes, then
                     copy .tags/tags.md to config/tags.md.

Not yet implemented: check (the wiki-doctor lint) and the ingest hooks.
See INBOX/Plan Systematic Tags.md.

Both LLM phases obey `ai_backend:` in config/settings.md and pause on the same
5-hour usage threshold as scripts/wiki-ingest.sh.

INVARIANTS
  * PDFs and images are never opened — `![[...]]` embeds are dropped, never resolved.
  * `obsidian tags` is the authority on what a tag is; grep is not.
  * Nothing is written without --apply, and a body edit is backed up (flushed
    and fsynced) before the file is rewritten. raw/ and wiki/ are outside git,
    so the backup is the only way back.

Usage:
  python3 scripts/wiki-tags.py --phase inventory [--format tsv|json] [--out FILE]
  python3 scripts/wiki-tags.py --phase escape [--apply]
  python3 scripts/wiki-tags.py --phase escape-revert [--apply]
  python3 scripts/wiki-tags.py --phase excerpts [--only raw] [--limit N]
  python3 scripts/wiki-tags.py --phase namespaces [--apply]
  python3 scripts/wiki-tags.py --phase taxonomy [--limit N]
  python3 scripts/wiki-tags.py --phase terms [--limit N]
  python3 scripts/wiki-tags.py --phase apply-review [--out FILE] [--apply]
  python3 scripts/wiki-tags.py --phase consolidate
  python3 scripts/wiki-tags.py --phase remap [--apply]
  python3 scripts/wiki-tags.py --phase assign [--limit N]
  python3 scripts/wiki-tags.py --phase write [--apply]
  python3 scripts/wiki-tags.py --phase write-revert [--apply]
"""

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collections import Counter  # noqa: E402

from lib import ai_backend, usage  # noqa: E402
from lib.wiki_assign import (  # noqa: E402
    BUNDLE_SIZE,
    assign_prompt,
    bundles,
    is_target,
    load_vocabulary,
    parse_assignments,
)
from lib.wiki_taxonomy import (  # noqa: E402
    NAMESPACE_SAMPLE,
    build_remap,
    canonical_table,
    chunks,
    format_tags_md,
    load_overrides,
    mapping_prompt,
    parse_review_comments,
    namespace_prompt,
    namespace_term_chunks,
    parse_mapping,
    parse_merges,
    parse_namespaces,
    terms_prompt,
)
from lib.wiki_tags import (  # noqa: E402
    CAP_WORDS,
    SCAN_DIRS,
    JsonlWriter,
    ObsidianUnavailable,
    append_jsonl,
    build_inventory,
    escape_document,
    format_inventory_tsv,
    frontmatter_backup_record,
    full_backup_record,
    iter_notes,
    iter_vault_md,
    load_jsonl,
    note_record,
    parse_tags,
    restore_frontmatter,
    restore_full,
    scratch_dir,
    series_key,
    split_document,
    unlisted_inline_tags,
    write_tags,
)

_ESCAPE_BACKUP = "inline-escape-backup.jsonl"
_MAX_SAMPLES = 4
_LLM_TIMEOUT = 300
# Sweeps for tags the model omitted from an otherwise-successful chunk.
_SWEEP_ROUNDS = 2
_SWEEP_BASE = 1000


def _progress(done: int, total: int, label: str) -> None:
    pct = (100 * done // total) if total else 100
    print(f"\r[ {done}/{total} ] {pct}% — {label[:60]:<60}", end="", file=sys.stderr)


def _end_progress() -> None:
    print(file=sys.stderr)


def _window(text: str, at: int, width: int = 80) -> str:
    """`width` characters of `text` centred on offset `at`, with ellipses."""
    start = max(0, at - width // 2)
    end = min(len(text), start + width)
    return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")


def _changed_line_sample(before: str, after: str) -> tuple[str, str]:
    """The first differing line of the two texts, windowed on the change itself.

    Trimming from the start of the line hides the edit whenever it sits past
    the display width — which made a dry run print identical before/after
    lines and prove nothing.
    """
    for old, new in zip(before.splitlines(), after.splitlines()):
        if old == new:
            continue
        at = next((i for i, (a, b) in enumerate(zip(old, new)) if a != b), 0)
        return _window(old, at), _window(new, at)
    return "", ""


# --------------------------------------------------------------------------- #

def phase_inventory(root: Path, fmt: str, out: Path | None) -> int:
    try:
        rows, stats = build_inventory(root)
    except ObsidianUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    target = out or (scratch_dir(root) / "inventory.tsv")
    if fmt == "json":
        target = target.with_suffix(".json")
        target.write_text(
            json.dumps([r.to_dict() for r in rows], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    else:
        target.write_text(format_inventory_tsv(rows), encoding="utf-8")

    print(f"{stats['real_tags']} real tags "
          f"({stats['obsidian_reported']} reported by Obsidian, "
          f"{stats['parent_aggregates']} phantom parent aggregates stripped)")
    print(f"  {stats['declared_occurrences']} frontmatter occurrences "
          f"over {stats['declared_distinct']} distinct tags")
    print(f"  {stats['singletons']} used exactly once; "
          f"{stats['inline_only']} inline-only (never declared)")
    print(f"  {stats['conforming']} already conform to the curated shape")
    print(f"  {stats['with_wiki_type']} match a wiki page name "
          f"({stats['ambiguous_wiki_type']} ambiguous across topic types)")
    if stats["blind"]:
        print(f"  {sum(stats['blind'].values())} tags Obsidian does not index "
              f"({stats['blind_occurrences']} occurrences): "
              + ", ".join(f"{n} {reason}" for reason, n in stats["blind"].items()))
    print(f"written to {target}")
    return 0


def phase_escape(root: Path, apply: bool) -> int:
    try:
        targets = unlisted_inline_tags(root)
    except ObsidianUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not targets:
        print("no stray inline hashtags — nothing to escape")
        return 0
    print(f"{len(targets)} stray inline tags, "
          f"{sum(targets.values())} occurrences reported by Obsidian")
    if not apply:
        # Print the whole target list: these are about to be escaped out of
        # Obsidian's tag pane, and some may be tags someone actually meant.
        ranked = sorted(targets.items(), key=lambda kv: (-kv[1], kv[0]))
        print("  " + ", ".join(f"#{t}({n})" for t, n in ranked))

    # The backup is append-only across runs rather than refusing to start when
    # one exists: a second pass (a widened scope, say) touches different files,
    # and moving the first run's backup aside would strand it — revert would
    # never see it. Revert keeps the earliest snapshot per path, so replaying
    # any number of runs still lands on the original text.
    backup = scratch_dir(root) / _ESCAPE_BACKUP

    names = list(targets)
    # Wider than iter_notes on purpose: Obsidian counts hashtags in _resources
    # attachment payloads and root-level files (README.md) as tags too.
    notes = list(iter_vault_md(root))
    touched = occurrences = 0
    samples: list[tuple[str, str, str]] = []
    for i, path in enumerate(notes, 1):
        if i % 200 == 0 or i == len(notes):
            _progress(i, len(notes), path.name)
        content = path.read_text(encoding="utf-8", errors="replace")
        if "#" not in content:
            continue
        new_content, changed = escape_document(content, names)
        if not changed:
            continue
        touched += 1
        occurrences += changed
        if len(samples) < _MAX_SAMPLES:
            old_line, new_line = _changed_line_sample(content, new_content)
            samples.append((str(path.relative_to(root)), old_line, new_line))
        if apply:
            append_jsonl(backup, full_backup_record(path, root, content))
            path.write_text(new_content, encoding="utf-8")
    _end_progress()

    print(f"{'escaped' if apply else 'would escape'} {occurrences} occurrences "
          f"in {touched} notes")
    for rel, old_line, new_line in samples:
        print(f"\n  {rel}\n    - {old_line}\n    + {new_line}")
    if apply:
        print(f"\nbackup: {backup}")
    else:
        print("\ndry run — re-run with --apply to write")
    return 0


def phase_escape_revert(root: Path, apply: bool) -> int:
    backup = scratch_dir(root) / _ESCAPE_BACKUP
    records = load_jsonl(backup)
    if not records:
        print(f"no backup at {backup} — nothing to revert", file=sys.stderr)
        return 1
    # First snapshot per path wins: that is the text before any escape run.
    earliest: dict[str, dict] = {}
    for record in records:
        earliest.setdefault(record["path"], record)
    records = list(earliest.values())
    if not apply:
        print(f"would restore {len(records)} notes from {backup}")
        print("dry run — re-run with --apply to write")
        return 0

    counts: dict[str, int] = {}
    for record in records:
        status = restore_full(record, root)
        counts[status] = counts.get(status, 0) + 1
    print(f"restored {counts.get('restored', 0)}, "
          f"already matching {counts.get('unchanged', 0)}, "
          f"missing {counts.get('missing', 0)}")
    backup.rename(backup.with_suffix(".jsonl.done"))
    return 0


def _inventory_rows(root: Path) -> list:
    """Declared tags only — the set the remap has to account for."""
    rows, _ = build_inventory(root)
    return [r for r in rows if r.declared_count > 0]


def phase_namespaces(root: Path, apply: bool) -> int:
    """Step 1 of the taxonomy: one call, proposing the namespace list."""
    if not ai_backend.available(root):
        print(f"error: the {ai_backend.read_backend(root)} CLI is not installed",
              file=sys.stderr)
        return 1
    try:
        rows = _inventory_rows(root)
    except ObsidianUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    out = scratch_dir(root) / "namespaces.tsv"
    if out.exists() and not apply:
        namespaces = _load_namespaces(out)
        print(f"{len(namespaces)} namespaces already proposed in {out}:")
        for name, meaning in namespaces.items():
            print(f"  {name:<16} {meaning}")
        print("\nre-run with --apply to replace them")
        return 0

    print(f"asking {ai_backend.MODEL_TAXONOMY} for namespaces "
          f"from the {NAMESPACE_SAMPLE} most-used of {len(rows)} tags…",
          file=sys.stderr)
    usage.wait_until_below(context="taxonomy namespaces")
    reply = ai_backend.run(
        namespace_prompt(rows),
        root=root, model=ai_backend.MODEL_TAXONOMY, timeout=_LLM_TIMEOUT,
    )
    namespaces = parse_namespaces(reply)
    if not namespaces:
        print("error: no usable namespaces in the reply", file=sys.stderr)
        return 1
    out.write_text(
        "\n".join(f"{n}\t{m}" for n, m in namespaces.items()) + "\n", encoding="utf-8"
    )
    print(f"{len(namespaces)} namespaces:")
    for name, meaning in namespaces.items():
        print(f"  {name:<16} {meaning}")
    print(f"\nwritten to {out}")
    print("review this list, then run --phase taxonomy to map all tags into it")
    return 0


def _load_namespaces(path: Path) -> dict[str, str]:
    namespaces: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        namespaces[parts[0].strip()] = parts[1].strip() if len(parts) > 1 else ""
    return namespaces


def _load_term_merges(root: Path) -> dict[str, str]:
    """The term-merge table, if the `terms` phase has run."""
    path = scratch_dir(root) / "term-merges.tsv"
    merges: dict[str, str] = {}
    if not path.is_file():
        return merges
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[1] != "__chunk_done__":
            merges[parts[1]] = parts[2]
    return merges


def _write_taxonomy_outputs(root: Path, rows: list, mapping: dict[str, str],
                            namespaces: dict[str, str]) -> tuple[dict, int]:
    """Re-derive the consolidation and rewrite remap/canonical/tags.md."""
    scratch = scratch_dir(root)
    counts = {r.tag: r.declared_count for r in rows}
    remap, stats = build_remap(
        mapping, counts,
        term_merges=_load_term_merges(root),
        drop_singletons=True,
        overrides=load_overrides(scratch / "overrides.tsv"),
    )
    canonical = canonical_table(remap, counts)
    (scratch / "remap.tsv").write_text(
        "old\tnew\tnotes\n" + "".join(
            f"{old}\t{new}\t{counts.get(old, 0)}\n"
            for old, new in sorted(remap.items(),
                                   key=lambda kv: (-counts.get(kv[0], 0), kv[0]))
        ), encoding="utf-8")
    (scratch / "canonical.tsv").write_text(
        "tag\tnotes\told_tags\n" + "".join(
            f"{tag}\t{notes}\t{sources}\n" for tag, notes, sources in canonical
        ), encoding="utf-8")
    (scratch / "tags.md").write_text(
        format_tags_md(canonical, namespaces, set(counts)), encoding="utf-8")
    return stats, len([r for r in rows if r.tag not in mapping])


def phase_terms(root: Path, limit: int | None) -> int:
    """Merge synonyms within each namespace. The pass that makes the list usable.

    Runs over the canonical tags from `taxonomy`, one call per namespace chunk,
    and only for namespaces big enough to be worth it.
    """
    if not ai_backend.available(root):
        print(f"error: the {ai_backend.read_backend(root)} CLI is not installed",
              file=sys.stderr)
        return 1
    scratch = scratch_dir(root)
    canonical_file = scratch / "canonical.tsv"
    if not canonical_file.is_file():
        print(f"error: no {canonical_file} — run --phase taxonomy first", file=sys.stderr)
        return 1
    namespaces = _load_namespaces(scratch / "namespaces.tsv")

    canonical: list[tuple[str, int, int]] = []
    for line in canonical_file.read_text(encoding="utf-8").splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) >= 3:
            canonical.append((parts[0], int(parts[1]), int(parts[2])))

    units = namespace_term_chunks(canonical)
    checkpoint = scratch / "term-merges.tsv"
    done, merges = _load_checkpoint(checkpoint)
    todo = [(i, u) for i, u in enumerate(units) if i not in done]
    if done:
        print(f"resuming: {len(done)} of {len(units)} namespace chunks already merged",
              file=sys.stderr)
    if limit:
        todo = todo[:limit]

    failed = 0
    with checkpoint.open("a", encoding="utf-8") as handle:
        for n, (index, (namespace, tags)) in enumerate(todo, 1):
            _progress(n, len(todo), f"{namespace} ({len(tags)} tags)")
            usage.wait_until_below(context=f"term merge {namespace}")
            reply = ai_backend.run(
                terms_prompt(namespace, namespaces.get(namespace, ""), tags),
                root=root, model=ai_backend.MODEL_TAXONOMY, timeout=_LLM_TIMEOUT,
            )
            parsed = parse_merges(reply, (t for t, _ in tags))
            if reply is None:
                failed += 1
                continue
            for old, new in parsed.items():
                handle.write(f"{index}\t{old}\t{new}\n")
                merges[old] = new
            # A chunk with no merges is still done: the sentinel stops it being
            # re-paid for, and "nothing to merge here" is a valid answer.
            handle.write(f"{index}\t__chunk_done__\t-\n")
            handle.flush()
            os.fsync(handle.fileno())
    if todo:
        _end_progress()

    try:
        rows = _inventory_rows(root)
    except ObsidianUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _done, mapping = _load_checkpoint(scratch / "taxonomy-map.tsv")
    stats, _unmapped = _write_taxonomy_outputs(root, rows, mapping, namespaces)
    print(f"{len(merges)} term merges -> {stats['canonical']} canonical tags")
    print(f"  {stats['merged_lexical']} lexical variants, {stats['merged_terms']} synonym "
          f"merges, {stats['merged_cross_namespace']} cross-namespace, "
          f"{stats['dropped_single_note']} single-note tags dropped")
    if failed:
        print(f"  {failed} chunks returned nothing — re-run to retry")
    remaining = len(units) - len(_load_checkpoint(checkpoint)[0])
    if remaining:
        print(f"  {remaining} namespace chunks still to do — re-run to continue")
    print(f"\nproposal for review: {scratch / 'tags.md'}")
    return 0


def phase_apply_review(root: Path, review: Path | None, apply: bool) -> int:
    """Read `!!` corrections out of a filed review table into the override table.

    The review markdown is the gate's interface, so corrections written there
    are read back rather than transcribed by hand.
    """
    path = review or (root / "INBOX" / "Tag Remap Review.md")
    if not path.is_file():
        print(f"error: no review file at {path}", file=sys.stderr)
        return 1
    overrides, unresolved = parse_review_comments(
        path.read_text(encoding="utf-8", errors="replace"))
    if not overrides and not unresolved:
        print(f"no `!!` comments found in {path}")
        return 0

    target = scratch_dir(root) / "overrides.tsv"
    existing = load_overrides(target)
    fresh = {old: new for old, new in overrides.items() if existing.get(old) != new}
    namespaces = set(_load_namespaces(scratch_dir(root) / "namespaces.tsv"))
    unknown = sorted({
        new.split("/")[0] for new in fresh.values()
        if new != "DROP" and new.split("/")[0] not in namespaces
    })

    print(f"{len(overrides)} corrections in {path.name}, {len(fresh)} new")
    for old, new in sorted(fresh.items(), key=lambda kv: (kv[1], kv[0])):
        print(f"  {old:<20} -> {new}")
    if unknown:
        print(f"\nnamespaces not yet in namespaces.tsv: {', '.join(unknown)}")
        print("add them there (with a one-line meaning) before consolidating")
    if unresolved:
        print("\nnot understood — resolve these by hand:")
        for old, comment in unresolved:
            print(f"  {old:<20} !! {comment}")
    if not apply:
        print("\ndry run — re-run with --apply to append to overrides.tsv")
        return 0
    if fresh:
        stamp = datetime.date.today().isoformat()
        with target.open("a", encoding="utf-8") as handle:
            handle.write(f"\n# --- From {path.name}, {stamp} ---\n")
            for old, new in sorted(fresh.items(), key=lambda kv: (kv[1], kv[0])):
                handle.write(f"{old}\t{new}\n")
        print(f"\nappended {len(fresh)} overrides to {target}")
    print("now run --phase consolidate to re-derive the tables (no LLM cost)")
    return 0


def phase_consolidate(root: Path) -> int:
    """Re-run the deterministic passes over the existing checkpoint. No LLM.

    Exists so a change to the consolidation rules can be re-derived for free
    rather than re-paying for every chunk — which is how the `automotive/general`
    merge bug was fixed without spending a second run.
    """
    scratch = scratch_dir(root)
    ns_file = scratch / "namespaces.tsv"
    checkpoint = scratch / "taxonomy-map.tsv"
    if not checkpoint.is_file():
        print(f"error: no {checkpoint} — run --phase taxonomy first", file=sys.stderr)
        return 1
    try:
        rows = _inventory_rows(root)
    except ObsidianUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    namespaces = _load_namespaces(ns_file) if ns_file.is_file() else {}
    _done, mapping = _load_checkpoint(checkpoint)
    stats, unmapped = _write_taxonomy_outputs(root, rows, mapping, namespaces)
    print(f"{len(mapping)} tags in the checkpoint -> {stats['canonical']} canonical tags")
    print(f"  {stats['dropped']} dropped, {stats['collapsed_rare']} rare depth-3 "
          f"folded into parents, {stats['merged_cross_namespace']} cross-namespace merges")
    if unmapped:
        print(f"  {unmapped} tags still unmapped")
    print(f"rewritten: {scratch / 'remap.tsv'}, {scratch / 'canonical.tsv'}, "
          f"{scratch / 'tags.md'}")
    return 0


def phase_taxonomy(root: Path, limit: int | None) -> int:
    """Step 2 of the taxonomy: map every tag into the approved namespaces."""
    if not ai_backend.available(root):
        print(f"error: the {ai_backend.read_backend(root)} CLI is not installed",
              file=sys.stderr)
        return 1
    scratch = scratch_dir(root)
    ns_file = scratch / "namespaces.tsv"
    if not ns_file.is_file():
        print(f"error: no {ns_file} — run --phase namespaces first", file=sys.stderr)
        return 1
    namespaces = _load_namespaces(ns_file)
    try:
        rows = _inventory_rows(root)
    except ObsidianUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    checkpoint = scratch / "taxonomy-map.tsv"
    done_chunks, mapping = _load_checkpoint(checkpoint)
    batches = chunks(rows)
    todo = [(i, c) for i, c in enumerate(batches) if i not in done_chunks]
    if done_chunks:
        print(f"resuming: {len(done_chunks)} of {len(batches)} chunks already mapped",
              file=sys.stderr)
    if limit:
        todo = todo[:limit]

    failed: list[int] = []
    with checkpoint.open("a", encoding="utf-8") as handle:
        for n, (index, chunk) in enumerate(todo, 1):
            _progress(n, len(todo), f"chunk {index + 1}/{len(batches)}")
            usage.wait_until_below(context=f"taxonomy chunk {index + 1}")
            reply = ai_backend.run(
                mapping_prompt(chunk, namespaces),
                root=root, model=ai_backend.MODEL_TAXONOMY, timeout=_LLM_TIMEOUT,
            )
            parsed = parse_mapping(reply, (r.tag for r in chunk))
            if not parsed:
                failed.append(index)
                continue
            for old, new in parsed.items():
                handle.write(f"{index}\t{old}\t{new}\n")
                mapping[old] = new
            # Sentinel so a chunk that legitimately mapped nothing still counts
            # as done and is not re-paid for on the next run.
            handle.write(f"{index}\t__chunk_done__\t-\n")
            handle.flush()
            os.fsync(handle.fileno())
    if todo:
        _end_progress()

    # A chunk gets its sentinel as soon as it returns *any* usable line, so a
    # tag the model silently skipped is otherwise stranded forever: its chunk
    # counts as done and never runs again. Sweep the leftovers into fresh
    # chunks of their own, numbered above the originals so the sentinels cannot
    # collide.
    if not limit:
        for round_number in range(_SWEEP_ROUNDS):
            leftover = [r for r in rows if r.tag not in mapping]
            if not leftover:
                break
            print(f"sweeping {len(leftover)} tags no chunk returned "
                  f"(round {round_number + 1})", file=sys.stderr)
            gained = 0
            with checkpoint.open("a", encoding="utf-8") as handle:
                for i, chunk in enumerate(chunks(leftover)):
                    index = _SWEEP_BASE + round_number * 100 + i
                    usage.wait_until_below(context="taxonomy sweep")
                    reply = ai_backend.run(
                        mapping_prompt(chunk, namespaces),
                        root=root, model=ai_backend.MODEL_TAXONOMY, timeout=_LLM_TIMEOUT,
                    )
                    parsed = parse_mapping(reply, (r.tag for r in chunk))
                    for old, new in parsed.items():
                        handle.write(f"{index}\t{old}\t{new}\n")
                        mapping[old] = new
                    handle.write(f"{index}\t__chunk_done__\t-\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                    gained += len(parsed)
            if not gained:
                # The model declines to name these however often it is asked;
                # another round would just cost money. They need an override.
                break

    stats, unmapped = _write_taxonomy_outputs(root, rows, mapping, namespaces)
    print(f"{len(mapping)} of {len(rows)} tags mapped "
          f"-> {stats['canonical']} canonical tags")
    print(f"  {stats['dropped']} dropped, {stats['collapsed_rare']} rare depth-3 "
          f"folded into parents, {stats['merged_cross_namespace']} cross-namespace merges")
    if unmapped:
        print(f"  {unmapped} still unmapped — re-run to pick them up")
    if failed:
        print(f"  {len(failed)} chunks returned nothing — re-run to retry")
    print(f"\nwritten: {scratch / 'remap.tsv'}, {scratch / 'canonical.tsv'}")
    print(f"proposal for review: {scratch / 'tags.md'}")
    print("\nHUMAN GATE: review the remap rows covering >5 notes, then copy the")
    print("proposal to config/tags.md before running the remap.")
    return 0


def _load_checkpoint(path: Path) -> tuple[set[int], dict[str, str]]:
    """(chunk indices already done, mapping so far) from the checkpoint file."""
    done: set[int] = set()
    mapping: dict[str, str] = {}
    if not path.is_file():
        return done, mapping
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        try:
            index = int(parts[0])
        except ValueError:
            continue
        if parts[1] == "__chunk_done__":
            done.add(index)
        else:
            mapping[parts[1]] = parts[2]
    return done, mapping


_REMAP_BACKUP = "remap-backup.jsonl"
_WRITE_BACKUP = "write-backup.jsonl"


def phase_assign(root: Path, limit: int | None) -> int:
    """Ask the model for tags for every note that carries too few.

    Closed vocabulary: anything off the approved list is counted and reported,
    never written. Checkpointed per bundle, so an interruption costs one call.
    """
    if not ai_backend.available(root):
        print(f"error: the {ai_backend.read_backend(root)} CLI is not installed",
              file=sys.stderr)
        return 1
    vocabulary = load_vocabulary(root / "config" / "tags.md")
    if not vocabulary:
        print("error: no assignable vocabulary in config/tags.md", file=sys.stderr)
        return 1
    scratch = scratch_dir(root)
    excerpts = scratch / "excerpts.jsonl"
    if not excerpts.is_file():
        print(f"error: no {excerpts} — run --phase excerpts first", file=sys.stderr)
        return 1

    records = load_jsonl(excerpts)
    targets = [r for r in records if is_target(r)]
    checkpoint = scratch / "assigned.jsonl"
    done = {r["path"] for r in load_jsonl(checkpoint)}
    todo = [r for r in targets if r["path"] not in done]
    if done:
        print(f"resuming: {len(done)} of {len(targets)} notes already assigned",
              file=sys.stderr)
    batches = bundles(todo)
    if limit:
        batches = batches[:limit]
    if not batches:
        print(f"nothing to do — all {len(targets)} target notes are assigned")
        return 0

    print(f"{len(todo)} notes to tag in {len(batches)} bundles of {BUNDLE_SIZE}, "
          f"model {ai_backend.MODEL_ASSIGN}, {len(vocabulary)} approved tags",
          file=sys.stderr)
    rejected: Counter = Counter()
    failed: list[str] = []
    assigned = 0
    with JsonlWriter(checkpoint, durable=True) as writer:
        for i, bundle in enumerate(batches, 1):
            _progress(i, len(batches), f"{bundle[0]['title'][:40]}")
            usage.wait_until_below(context=f"assign bundle {i}")
            reply = ai_backend.run(
                assign_prompt(bundle, vocabulary),
                root=root, model=ai_backend.MODEL_ASSIGN, timeout=_LLM_TIMEOUT,
            )
            tags_by_path, rejects = parse_assignments(reply, bundle, vocabulary)
            rejected.update(rejects)
            for record in bundle:
                got = tags_by_path.get(record["path"])
                if got:
                    writer.write({"path": record["path"], "tags": got})
                    assigned += 1
                else:
                    failed.append(record["path"])
    _end_progress()

    if rejected:
        (scratch / "assign-rejects.tsv").write_text(
            "tag\tcount\n" + "".join(f"{t}\t{n}\n" for t, n in rejected.most_common()),
            encoding="utf-8")
    if failed:
        (scratch / "assign-failed.txt").write_text("\n".join(failed) + "\n",
                                                   encoding="utf-8")

    print(f"{assigned} notes assigned tags")
    print(f"  {sum(rejected.values())} off-list suggestions over {len(rejected)} tags "
          f"— reported, not written")
    if rejected:
        print("  most wanted: "
              + ", ".join(f"{t}({n})" for t, n in rejected.most_common(8)))
        print(f"  full list: {scratch / 'assign-rejects.tsv'}")
    if failed:
        print(f"  {len(failed)} notes got no usable line — re-run to retry "
              f"({scratch / 'assign-failed.txt'})")
    print(f"\ncheckpoint: {checkpoint}")
    print("apply with --phase write --apply")
    return 0


def phase_write(root: Path, apply: bool) -> int:
    """Merge the assigned tags into frontmatter. Additive: nothing is removed."""
    scratch = scratch_dir(root)
    checkpoint = scratch / "assigned.jsonl"
    records = load_jsonl(checkpoint)
    if not records:
        print(f"no assignments at {checkpoint} — run --phase assign first",
              file=sys.stderr)
        return 1
    vocabulary = set(load_vocabulary(root / "config" / "tags.md", assignable=False))
    # Append-only across runs, like the escape backup: tagging new notes is a
    # recurring step, so refusing over an existing backup would make every run
    # after the first need a file moved out of the way. `write-revert` keeps the
    # earliest record per path, so replaying any number of runs still lands on
    # the note's original frontmatter.
    backup = scratch / _WRITE_BACKUP

    # Last assignment per path wins, so a re-run's fresher answer replaces an
    # earlier one rather than both being merged in.
    latest: dict[str, list[str]] = {}
    for record in records:
        latest[record["path"]] = record["tags"]

    changed = added = 0
    missing = 0
    samples: list[tuple[str, list[str], list[str]]] = []
    handle = backup.open("a", encoding="utf-8") if apply else None
    try:
        for i, (rel, tags) in enumerate(sorted(latest.items()), 1):
            if i % 500 == 0 or i == len(latest):
                _progress(i, len(latest), rel.rsplit("/", 1)[-1])
            path = root / rel
            if not path.is_file():
                missing += 1
                continue
            content = path.read_text(encoding="utf-8", errors="replace")
            fm, _ = split_document(content)
            before = parse_tags(fm)
            after = sorted(set(before) | {t for t in tags if t in vocabulary})
            if after == sorted(before):
                continue
            changed += 1
            added += len(after) - len(set(before))
            if len(samples) < _MAX_SAMPLES:
                samples.append((rel, before, after))
            if apply:
                handle.write(json.dumps(
                    frontmatter_backup_record(path, root, content),
                    ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
                path.write_text(write_tags(content, after), encoding="utf-8")
    finally:
        if handle is not None:
            handle.close()
    _end_progress()

    print(f"{'wrote' if apply else 'would write'} tags to {changed} notes "
          f"({added} tags added)")
    if missing:
        print(f"  {missing} notes no longer exist — skipped")
    for rel, before, after in samples:
        print(f"\n  {rel}\n    - {' '.join(before) or '(none)'}\n    + {' '.join(after)}")
    if apply:
        print(f"\nbackup: {backup}")
    else:
        print("\ndry run — re-run with --apply to write")
    return 0


def _load_remap(path: Path) -> dict[str, str]:
    table: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0]:
            table[parts[0]] = parts[1]
    return table


def phase_remap(root: Path, apply: bool) -> int:
    """Rewrite every note's frontmatter tags through the approved remap table.

    The only bulk tag-removing operation in the pipeline, so it is fenced:
    every target must already be in `config/tags.md`, and each note is backed
    up — flushed and fsynced — *before* it is rewritten. `raw/` and `wiki/` sit
    outside git, so that backup is the only way back.
    """
    scratch = scratch_dir(root)
    remap_file = scratch / "remap.tsv"
    if not remap_file.is_file():
        print(f"error: no {remap_file} — run --phase taxonomy first", file=sys.stderr)
        return 1
    vocabulary = set(load_vocabulary(root / "config" / "tags.md", assignable=False))
    if not vocabulary:
        print("error: no approved vocabulary in config/tags.md. Review "
              f"{scratch / 'tags.md'} and copy it into place first.", file=sys.stderr)
        return 1

    table = _load_remap(remap_file)
    unapproved = sorted({
        new for new in table.values()
        if new != "DROP" and new not in vocabulary
    })
    if unapproved:
        print(f"error: {len(unapproved)} remap targets are not in config/tags.md:",
              file=sys.stderr)
        for tag in unapproved[:20]:
            print(f"  {tag}", file=sys.stderr)
        print("refusing to rewrite notes against an unapproved vocabulary",
              file=sys.stderr)
        return 1

    backup = scratch / _REMAP_BACKUP
    if apply and backup.exists():
        print(f"error: {backup} already exists — a remap has run. Revert it or "
              "move it aside first.", file=sys.stderr)
        return 1

    notes = list(iter_notes(root))
    changed = dropped = added = 0
    emptied: list[str] = []
    unknown: Counter = Counter()
    samples: list[tuple[str, list[str], list[str]]] = []
    handle = backup.open("a", encoding="utf-8") if apply else None
    try:
        for i, path in enumerate(notes, 1):
            if i % 500 == 0 or i == len(notes):
                _progress(i, len(notes), path.name)
            content = path.read_text(encoding="utf-8", errors="replace")
            fm, _ = split_document(content)
            before = parse_tags(fm)
            if not before:
                continue
            after: list[str] = []
            for tag in before:
                new = table.get(tag)
                if new is None:
                    # Not in the table at all: leave it, and report it. Silently
                    # dropping a tag the taxonomy never saw would lose data.
                    unknown[tag] += 1
                    if tag not in after:
                        after.append(tag)
                elif new != "DROP" and new not in after:
                    after.append(new)
            after = sorted(after)
            if after == sorted(before):
                continue
            changed += 1
            dropped += max(0, len(before) - len(after))
            added += max(0, len(after) - len(before))
            if not after:
                emptied.append(str(path.relative_to(root)))
            if len(samples) < _MAX_SAMPLES:
                samples.append((str(path.relative_to(root)), before, after))
            if apply:
                record = frontmatter_backup_record(path, root, content)
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
                path.write_text(write_tags(content, after), encoding="utf-8")
    finally:
        if handle is not None:
            handle.close()
    _end_progress()

    print(f"{'rewrote' if apply else 'would rewrite'} {changed} of {len(notes)} notes")
    print(f"  {dropped} tag slots removed, {added} added")
    print(f"  {len(emptied)} notes left with no tags (phase 5 will re-tag them)")
    if unknown:
        print(f"  {len(unknown)} tags not in the remap table, left untouched: "
              + ", ".join(f"{t}({n})" for t, n in unknown.most_common(8)))
    for rel, before, after in samples:
        print(f"\n  {rel}\n    - {' '.join(before)}\n    + {' '.join(after) or '(none)'}")
    if apply:
        print(f"\nbackup: {backup}")
        print("undo with --phase remap-revert --apply")
    else:
        print("\ndry run — re-run with --apply to write")
    return 0


def phase_remap_revert(root: Path, apply: bool) -> int:
    backup = scratch_dir(root) / _REMAP_BACKUP
    records = load_jsonl(backup)
    if not records:
        print(f"no backup at {backup} — nothing to revert", file=sys.stderr)
        return 1
    earliest: dict[str, dict] = {}
    for record in records:
        earliest.setdefault(record["path"], record)
    if not apply:
        print(f"would restore frontmatter on {len(earliest)} notes from {backup}")
        print("dry run — re-run with --apply to write")
        return 0
    counts: Counter = Counter()
    for record in earliest.values():
        counts[restore_frontmatter(record, root)] += 1
    print(f"restored {counts['restored']}, already original {counts['unchanged']}, "
          f"missing {counts['missing']}, body changed since backup {counts['mismatch']}")
    if counts["mismatch"]:
        print("  those were left untouched — their bodies no longer match the backup")
    backup.rename(backup.with_suffix(".jsonl.done"))
    return 0


def phase_write_revert(root: Path, apply: bool) -> int:
    """Undo the write phase from its backup, earliest record per path."""
    backup = scratch_dir(root) / _WRITE_BACKUP
    records = load_jsonl(backup)
    if not records:
        print(f"no backup at {backup} — nothing to revert", file=sys.stderr)
        return 1
    earliest: dict[str, dict] = {}
    for record in records:
        earliest.setdefault(record["path"], record)
    if not apply:
        print(f"would restore frontmatter on {len(earliest)} notes from {backup}")
        print("dry run — re-run with --apply to write")
        return 0
    counts: Counter = Counter()
    for record in earliest.values():
        counts[restore_frontmatter(record, root)] += 1
    print(f"restored {counts['restored']}, already original {counts['unchanged']}, "
          f"missing {counts['missing']}, body changed since backup {counts['mismatch']}")
    backup.rename(backup.with_suffix(".jsonl.done"))
    return 0


def phase_excerpts(root: Path, only: str | None, limit: int | None, cap: int) -> int:
    subdirs = (only,) if only else SCAN_DIRS
    notes = list(iter_notes(root, subdirs))
    if limit:
        notes = notes[:limit]
    if not notes:
        print(f"error: no notes under {', '.join(subdirs)}", file=sys.stderr)
        return 2

    out = scratch_dir(root) / "excerpts.jsonl"
    if out.exists():
        out.unlink()

    title_only = untagged = 0
    total_words = 0
    series: dict[str, int] = {}
    failed = 0
    with JsonlWriter(out) as writer:
        for i, path in enumerate(notes, 1):
            if i % 200 == 0 or i == len(notes):
                _progress(i, len(notes), path.name)
            try:
                record = note_record(path, root, cap)
            except Exception as exc:                  # one bad note never aborts a run
                print(f"\n!! {path.relative_to(root)}: {exc}", file=sys.stderr)
                failed += 1
                continue
            writer.write(record)
            total_words += record["words"]
            title_only += record["title_only"]
            untagged += not record["tags"]
            key = series_key(record["title"])
            if key:
                series[key] = series.get(key, 0) + 1
    _end_progress()

    written = len(notes) - failed
    print(f"{written} excerpts, {total_words} words "
          f"(mean {total_words // max(1, written)}, cap {cap})")
    print(f"  {title_only} too thin to excerpt — will be tagged from the title alone")
    print(f"  {untagged} carry no frontmatter tags yet")
    if failed:
        print(f"  {failed} failed to read")
    biggest = sorted(series.items(), key=lambda kv: -kv[1])[:5]
    if biggest and biggest[0][1] > 5:
        print("  largest title series (inspect before spending tokens): "
              + ", ".join(f"{n} x {k!r}" for k, n in biggest if n > 5))
    print(f"written to {out}")
    return 0


# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--phase", required=True,
                        choices=("inventory", "escape", "escape-revert", "excerpts",
                                 "namespaces", "taxonomy", "terms",
                                 "apply-review", "consolidate",
                                 "remap", "remap-revert",
                                 "assign", "write", "write-revert"))
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="vault root (default: cwd)")
    parser.add_argument("--only", help="restrict to one subdir, e.g. raw or wiki")
    parser.add_argument("--limit", type=int, help="excerpts: stop after N notes")
    parser.add_argument("--cap-words", type=int, default=CAP_WORDS,
                        help=f"excerpt word budget per note (default: {CAP_WORDS})")
    parser.add_argument("--format", choices=("tsv", "json"), default="tsv",
                        help="inventory output format")
    parser.add_argument("--out", type=Path, help="inventory: write here instead of .tags/")
    parser.add_argument("--apply", action="store_true",
                        help="actually write; without it every phase is a dry run")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if not any((root / d).is_dir() for d in SCAN_DIRS):
        print(f"error: none of {', '.join(SCAN_DIRS)} found under {root}", file=sys.stderr)
        return 2

    if args.phase == "inventory":
        return phase_inventory(root, args.format, args.out)
    if args.phase == "escape":
        return phase_escape(root, args.apply)
    if args.phase == "escape-revert":
        return phase_escape_revert(root, args.apply)
    if args.phase == "namespaces":
        return phase_namespaces(root, args.apply)
    if args.phase == "taxonomy":
        return phase_taxonomy(root, args.limit)
    if args.phase == "terms":
        return phase_terms(root, args.limit)
    if args.phase == "apply-review":
        return phase_apply_review(root, args.out, args.apply)
    if args.phase == "consolidate":
        return phase_consolidate(root)
    if args.phase == "remap":
        return phase_remap(root, args.apply)
    if args.phase == "remap-revert":
        return phase_remap_revert(root, args.apply)
    if args.phase == "assign":
        return phase_assign(root, args.limit)
    if args.phase == "write":
        return phase_write(root, args.apply)
    if args.phase == "write-revert":
        return phase_write_revert(root, args.apply)
    return phase_excerpts(root, args.only, args.limit, args.cap_words)


if __name__ == "__main__":
    sys.exit(main())
