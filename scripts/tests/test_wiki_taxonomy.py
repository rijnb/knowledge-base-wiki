"""Tests for lib.wiki_taxonomy, lib.ai_backend and lib.usage (phase 3)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _vault_fixture import VaultFixtureMixin  # noqa: E402
from lib import ai_backend, usage  # noqa: E402
from lib.wiki_tags import InventoryRow  # noqa: E402
from lib.wiki_taxonomy import (  # noqa: E402
    BANNED_NAMESPACES,
    DROP,
    build_remap,
    canonical_table,
    chunks,
    collapse_rare,
    format_tags_md,
    load_overrides,
    mapping_prompt,
    merge_cross_namespace,
    merge_lexical_variants,
    namespace_prompt,
    namespace_term_chunks,
    parse_merges,
    terms_prompt,
    parse_mapping,
    parse_namespaces,
    parse_review_comments,
    resolve,
)


def row(tag: str, count: int, types=(), blind="") -> InventoryRow:
    return InventoryRow(
        tag=tag, obsidian_count=count, declared_count=count,
        wiki_types=list(types), depth=tag.count("/") + 1, blind=blind,
    )


class NamespaceParsingTest(unittest.TestCase):
    def test_parses_tab_separated_lines(self):
        reply = "sw\tsoftware engineering\nmap\tmap data and formats\n"
        self.assertEqual(parse_namespaces(reply),
                         {"sw": "software engineering", "map": "map data and formats"})

    def test_tolerates_bullets_backticks_and_dashes(self):
        reply = "- `sw` — software\n* map: map data\n"
        self.assertEqual(set(parse_namespaces(reply)), {"sw", "map"})

    def test_drops_banned_namespaces(self):
        reply = ("sw\tsoftware\npeople\tcolleagues\ncompanies\tvendors\n"
                 "competition\tcompetitors\nconcept\tcatch-all\n")
        parsed = parse_namespaces(reply)
        self.assertEqual(set(parsed), {"sw"})
        for banned in BANNED_NAMESPACES:
            self.assertNotIn(banned, parsed)

    def test_drops_multi_segment_and_preamble(self):
        reply = "Here are the namespaces:\nsw/agile\tnot a namespace\nsw\tsoftware\n"
        self.assertEqual(set(parse_namespaces(reply)), {"sw"})

    def test_empty_reply(self):
        self.assertEqual(parse_namespaces(None), {})
        self.assertEqual(parse_namespaces(""), {})


class MappingParsingTest(unittest.TestCase):
    ASKED = ["alpha", "megacorp", "dataspec-live", "jane.doe"]

    def test_parses_and_keeps_drops(self):
        reply = ("alpha\tproject/alpha\n"
                 "megacorp\tDROP\n"
                 "dataspec-live\tstandard/dataspec-live\n"
                 "jane.doe\tDROP\n")
        self.assertEqual(parse_mapping(reply, self.ASKED), {
            "alpha": "project/alpha",
            "megacorp": DROP,
            "dataspec-live": "standard/dataspec-live",
            "jane.doe": DROP,
        })

    def test_tolerates_numbering_arrows_and_spaces(self):
        reply = "[1] alpha -> project/alpha\n2. megacorp   DROP\n"
        parsed = parse_mapping(reply, self.ASKED)
        self.assertEqual(parsed["alpha"], "project/alpha")
        self.assertEqual(parsed["megacorp"], DROP)

    def test_rejects_one_and_four_segment_targets(self):
        reply = "alpha\talpha\ndataspec-live\ta/b/c/d\n"
        self.assertEqual(parse_mapping(reply, self.ASKED), {})

    def test_rejects_banned_namespace_targets(self):
        for target in ("people/jane-doe", "concept/dataspec-live", "competition/alpha"):
            reply = f"alpha\t{target}\n"
            self.assertEqual(parse_mapping(reply, self.ASKED), {}, target)

    def test_ignores_tags_not_asked_about(self):
        reply = "something-else\tsw/other\n"
        self.assertEqual(parse_mapping(reply, self.ASKED), {})

    def test_year_tag_passes_through(self):
        self.assertEqual(parse_mapping("year/2022\tyear/2022\n", ["year/2022"]),
                         {"year/2022": "year/2022"})

    def test_malformed_line_does_not_lose_the_rest(self):
        reply = "garbage\nalpha\tproject/alpha\n"
        self.assertEqual(parse_mapping(reply, self.ASKED), {"alpha": "project/alpha"})


class ConsolidationTest(unittest.TestCase):
    def test_collapse_rare_folds_thin_depth_three(self):
        mapping = {"a": "sw/agile/scrum", "b": "sw/agile/kanban"}
        counts = {"a": 1, "b": 40}
        collapsed = collapse_rare(mapping, counts)
        self.assertEqual(collapsed, {"sw/agile/scrum": "sw/agile"})

    def test_collapse_rare_leaves_depth_two_and_year_alone(self):
        mapping = {"a": "sw/agile", "b": "year/2013"}
        self.assertEqual(collapse_rare(mapping, {"a": 1, "b": 1}), {})

    def test_merge_cross_namespace_picks_the_most_used(self):
        mapping = {"a": "map/security", "b": "sw/security"}
        merged = merge_cross_namespace(mapping, {"a": 3, "b": 30})
        self.assertEqual(merged, {"map/security": "sw/security"})

    def test_merge_never_folds_generic_filler_terms(self):
        # Regression: these were all folded onto automotive/general because they
        # share the term "general", silently reassigning 1880 notes' worth of
        # correct mappings. Only the namespace means anything here.
        mapping = {
            "automotive": "automotive/general",
            "ai": "ai/general",
            "maps": "map/general",
            "navigation": "navigation/general",
            "security": "security/general",
        }
        counts = {"automotive": 1175, "ai": 598, "maps": 467,
                  "navigation": 391, "security": 264}
        self.assertEqual(merge_cross_namespace(mapping, counts), {})
        remap, _ = build_remap(mapping, counts)
        self.assertEqual(remap["ai"], "ai/general")
        self.assertEqual(remap["maps"], "map/general")
        self.assertEqual(remap["security"], "security/general")

    def test_merge_ignores_distinct_terms(self):
        mapping = {"a": "map/routing", "b": "sw/testing"}
        self.assertEqual(merge_cross_namespace(mapping, {"a": 5, "b": 5}), {})

    def test_resolve_chains_tables(self):
        collapsed = {"sw/agile/scrum": "sw/agile"}
        merged = {"sw/agile": "process/agile"}
        self.assertEqual(resolve("sw/agile/scrum", collapsed, merged), "process/agile")

    def test_resolve_survives_a_cycle(self):
        table = {"a/b": "c/d", "c/d": "a/b"}
        self.assertIn(resolve("a/b", table), ("a/b", "c/d"))

    def test_build_remap_applies_both_passes_and_counts(self):
        mapping = {
            "scrum": "sw/agile/scrum",       # rare depth-3 -> sw/agile
            "agile": "sw/agile",
            "megacorp": DROP,
        }
        counts = {"scrum": 1, "agile": 50, "megacorp": 2278}
        remap, stats = build_remap(mapping, counts)
        self.assertEqual(remap["scrum"], "sw/agile")
        self.assertEqual(remap["megacorp"], DROP)
        self.assertEqual(stats["dropped"], 1)
        self.assertEqual(stats["canonical"], 1)

    def test_canonical_table_sums_notes_and_sources(self):
        remap = {"dataspec": "standard/dataspec", "DataSpec": "standard/dataspec", "x": DROP}
        counts = {"dataspec": 281, "DataSpec": 1, "x": 9}
        self.assertEqual(canonical_table(remap, counts), [("standard/dataspec", 282, 2)])

    def test_chunks_put_the_most_used_first(self):
        rows = [row("rare", 1), row("common", 900), row("mid", 50)]
        batches = chunks(rows, size=2)
        self.assertEqual([r.tag for r in batches[0]], ["common", "mid"])
        self.assertEqual([r.tag for r in batches[1]], ["rare"])


class LexicalMergeTest(unittest.TestCase):
    def test_folds_hyphen_dot_and_plural_variants(self):
        mapping = {"a": "system/alphamap", "b": "system/alpha-map",
                   "c": "map/hd-map", "d": "map/hd-maps", "e": "map/hdmap"}
        counts = {"a": 537, "b": 15, "c": 133, "d": 10, "e": 1}
        merged = merge_lexical_variants(mapping, counts)
        self.assertEqual(merged["system/alpha-map"], "system/alphamap")
        self.assertEqual(merged["map/hd-maps"], "map/hd-map")
        self.assertEqual(merged["map/hdmap"], "map/hd-map")

    def test_does_not_cross_namespaces_or_touch_year(self):
        mapping = {"a": "map/tile", "b": "cloud/tiles", "c": "year/2013"}
        self.assertEqual(merge_lexical_variants(mapping, {"a": 5, "b": 5, "c": 5}), {})

    def test_distinct_terms_are_left_alone(self):
        mapping = {"a": "process/api", "b": "process/agile"}
        self.assertEqual(merge_lexical_variants(mapping, {"a": 5, "b": 5}), {})


class TermMergeTest(unittest.TestCase):
    KNOWN = ["process/testing", "process/test", "process/qa", "map/poi"]

    def test_parses_same_namespace_merges(self):
        reply = "process/test\tprocess/testing\nprocess/qa\tprocess/testing\n"
        self.assertEqual(parse_merges(reply, self.KNOWN),
                         {"process/test": "process/testing",
                          "process/qa": "process/testing"})

    def test_rejects_cross_namespace_and_unknown_and_self(self):
        for reply in ("map/poi\tprocess/testing\n",
                      "process/nonexistent\tprocess/testing\n",
                      "process/test\tprocess/test\n"):
            self.assertEqual(parse_merges(reply, self.KNOWN), {}, reply)

    def test_breaks_a_two_cycle(self):
        reply = "process/test\tprocess/testing\nprocess/testing\tprocess/test\n"
        merged = parse_merges(reply, self.KNOWN)
        self.assertEqual(len(merged), 1)

    def test_namespace_chunks_skip_small_namespaces(self):
        canonical = [(f"process/t{i}", 5, 1) for i in range(15)]
        canonical += [("ux/design", 3, 1), ("year/2013", 9, 1)]
        units = namespace_term_chunks(canonical, min_tags=12, chunk=10)
        self.assertEqual([ns for ns, _ in units], ["process", "process"])
        self.assertEqual(len(units[0][1]), 10)

    def test_build_remap_applies_term_merges_before_dropping_singletons(self):
        # Three single-note tags pool onto one survivor with 3 notes, so the
        # singleton drop must not touch it.
        mapping = {"a": "process/test", "b": "process/testing", "c": "process/qa"}
        counts = {"a": 1, "b": 1, "c": 1}
        term_merges = {"process/test": "process/testing", "process/qa": "process/testing"}
        remap, stats = build_remap(mapping, counts,
                                   term_merges=term_merges, drop_singletons=True)
        self.assertEqual(set(remap.values()), {"process/testing"})
        self.assertEqual(stats["dropped_single_note"], 0)

    def test_drop_singletons_removes_a_tag_on_one_note(self):
        mapping = {"a": "process/lonely", "b": "process/busy"}
        remap, stats = build_remap(mapping, {"a": 1, "b": 40}, drop_singletons=True)
        self.assertEqual(remap["a"], DROP)
        self.assertEqual(remap["b"], "process/busy")
        self.assertEqual(stats["dropped_single_note"], 1)


class OverrideTest(VaultFixtureMixin, unittest.TestCase):
    """Gate corrections must win outright — no automatic pass may undo them."""

    def test_override_beats_a_drop_and_a_mapping(self):
        mapping = {"acme": DROP, "zephyr": "system/zephyr"}
        counts = {"acme": 23, "zephyr": 10}
        overrides = {"acme": "project/acme", "zephyr": DROP}
        remap, stats = build_remap(mapping, counts, overrides=overrides)
        self.assertEqual(remap["acme"], "project/acme")
        self.assertEqual(remap["zephyr"], DROP)
        self.assertEqual(stats["overrides_applied"], 2)

    def test_override_survives_the_singleton_drop(self):
        # globex has one note; the drop would remove it, but it was asked for.
        remap, _ = build_remap({"globex": DROP}, {"globex": 1},
                               drop_singletons=True,
                               overrides={"globex": "project/globex"})
        self.assertEqual(remap["globex"], "project/globex")

    def test_load_overrides_parses_comments_tabs_and_drop(self):
        path = self.write(".tags/overrides.tsv",
                          "# a comment\n\nacme\tproject/acme\n"
                          "here\tDROP\n"
                          "aws   cloud/aws   # trailing comment\n")
        self.assertEqual(load_overrides(path), {
            "acme": "project/acme", "here": DROP, "aws": "cloud/aws",
        })

    def test_load_overrides_rejects_bad_targets(self):
        path = self.write(".tags/overrides.tsv",
                          "a\tonesegment\nb\tp/e/o/p\nc\tpeople/x\nd\tconcept/y\n")
        self.assertEqual(load_overrides(path), {})

    def test_load_overrides_missing_file(self):
        self.assertEqual(load_overrides(self.root / "nope.tsv"), {})


class ReviewCommentTest(unittest.TestCase):
    """The filed review table is the gate's interface and is read back."""

    def _rows(self, *rows: str) -> str:
        head = "| old tag | new tag | notes |\n|---|---|------:|\n"
        return head + "".join(rows)

    def test_full_replacement_tag(self):
        overrides, unresolved = parse_review_comments(
            self._rows("| `jira` | `system/jira` !! tool/jira | 22 |\n"))
        self.assertEqual(overrides, {"jira": "tool/jira"})
        self.assertEqual(unresolved, [])

    def test_drop(self):
        overrides, _ = parse_review_comments(
            self._rows("| `devhouse` | `system/devhouse` !!DROP | 46 |\n"))
        self.assertEqual(overrides, {"devhouse": DROP})

    def test_bare_top_level_reparents_the_current_term(self):
        overrides, _ = parse_review_comments(self._rows(
            "| `telematics` | `automotive/telematics` !! software | 83 |\n",
            # software-update was merged into automotive/ota; re-parenting must
            # preserve that merge rather than resurrect the old term.
            "| `software-update` | `automotive/ota` !! software | 9 |\n",
            "| `copilot` | `ai/copilot` !! tool | 6 |\n",
        ))
        self.assertEqual(overrides, {
            "telematics": "software/telematics",
            "software-update": "software/ota",
            "copilot": "tool/copilot",
        })

    def test_tolerates_hand_typing(self):
        overrides, _ = parse_review_comments(self._rows(
            "| `daf` | `system/daf` !!should be project/daf | 61 |\n",
            "| `consultco` | `system/consultco` !! project /consultco | 17 |\n",
            "| `maven` | `process/maven` !! /tool/maven | 12 |\n",
        ))
        self.assertEqual(overrides, {
            "daf": "project/daf",
            "consultco": "project/consultco",
            "maven": "tool/maven",
        })

    def test_term_equal_to_namespace_is_unresolved_not_guessed(self):
        overrides, unresolved = parse_review_comments(
            self._rows("| `hardware` | `automotive/hardware` !! hardware | 87 |\n"))
        self.assertEqual(overrides, {})
        self.assertEqual(unresolved, [("hardware", "hardware")])

    def test_rows_without_comments_are_ignored(self):
        overrides, unresolved = parse_review_comments(
            self._rows("| `alpha` | `system/alpha` | 647 |\n"))
        self.assertEqual((overrides, unresolved), ({}, []))

    def test_banned_namespace_is_unresolved(self):
        _overrides, unresolved = parse_review_comments(
            self._rows("| `x` | `system/x` !! concept/x | 9 |\n"))
        self.assertEqual(len(unresolved), 1)


class PromptTest(unittest.TestCase):
    def test_namespace_prompt_includes_counts_and_wiki_hints(self):
        prompt = namespace_prompt([row("alpha", 647, ["systems"]), row("nope", 0)])
        self.assertIn("alpha\t647\twiki:systems", prompt)
        self.assertNotIn("nope", prompt)          # undeclared tags carry no signal
        self.assertIn("year", prompt)

    def test_mapping_prompt_carries_namespaces_blind_notes_and_rules(self):
        prompt = mapping_prompt(
            [row("1:1", 14, blind="illegal-char")],
            {"meeting": "meetings and reviews"},
        )
        self.assertIn("meeting\tmeetings and reviews", prompt)
        self.assertIn("1:1\t14\tNOTE:illegal-char", prompt)
        self.assertIn("NEVER one segment", prompt)
        self.assertIn(DROP, prompt)

    def test_format_tags_md_groups_by_namespace_and_stars_existing(self):
        canonical = [("sw/agile", 50, 2), ("map/hd-map", 10, 1)]
        out = format_tags_md(canonical, {"sw": "software"}, existing={"sw/agile"})
        self.assertIn("## sw", out)
        self.assertIn("- `sw/agile` *", out)
        self.assertIn("- `map/hd-map`", out)
        self.assertNotIn("- `map/hd-map` *", out)
        self.assertIn("Never 1 segment, never 4", out)


class AiBackendTest(VaultFixtureMixin, unittest.TestCase):
    def test_reads_the_setting(self):
        self.write("config/settings.md", "---\nai_backend: codex\n---\n")
        self.assertEqual(ai_backend.read_backend(self.root), "codex")

    def test_defaults_to_claude_when_missing_or_unknown(self):
        self.assertEqual(ai_backend.read_backend(self.root), "claude")
        self.write("config/settings.md", "---\nai_backend: nonsense\n---\n")
        self.assertEqual(ai_backend.read_backend(self.root), "claude")

    def test_claude_command_is_bare_and_carries_the_model(self):
        cmd = ai_backend._command("claude", "/bin/claude", "hi", "sonnet", True)
        self.assertEqual(cmd[:3], ["/bin/claude", "-p", "hi"])
        self.assertIn("--model", cmd)
        # bare mode is containment, not tuning: no tools means the subprocess
        # cannot open a note or a PDF of its own accord.
        self.assertIn("--tools", cmd)
        self.assertIn("--setting-sources", cmd)

    def test_bare_can_be_turned_off(self):
        cmd = ai_backend._command("claude", "/bin/claude", "hi", None, False)
        self.assertNotIn("--tools", cmd)
        self.assertNotIn("--model", cmd)

    def test_codex_uses_exec_and_ignores_model_and_bare(self):
        cmd = ai_backend._command("codex", "/bin/codex", "hi", "sonnet", True)
        self.assertEqual(cmd, ["/bin/codex", "exec", "hi"])


class UsageTest(unittest.TestCase):
    def test_waits_while_over_threshold_then_proceeds(self):
        readings = iter([92, 90, 40])
        slept: list[int] = []
        usage.wait_until_below(threshold=85, wait_seconds=7,
                               sleep=slept.append, probe=lambda: next(readings))
        self.assertEqual(slept, [7, 7])

    def test_unknown_utilization_does_not_stall_the_run(self):
        slept: list[int] = []
        usage.wait_until_below(sleep=slept.append, probe=lambda: None)
        self.assertEqual(slept, [])

    def test_cache_is_ignored_when_stale_or_malformed(self):
        self.assertIsNone(usage._from_cache())    # no cache file in the test env
        self.assertIsNone(usage._from_cache(now=0))


if __name__ == "__main__":
    unittest.main()
