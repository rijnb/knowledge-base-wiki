"""Tests for query-time freshness packets."""

import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _vault_fixture import VaultFixtureMixin  # noqa: E402
from lib.freshness_query import (  # noqa: E402
    build_query_packet,
    build_query_packet_from_qmd_results,
    resolve_qmd_result_pages,
)


ROOT = Path(__file__).resolve().parents[2]


class FreshnessQueryPacketTests(VaultFixtureMixin, unittest.TestCase):
    def test_ranks_blocks_and_explains_demoted_historical_evidence(self):
        self.write(
            "wiki/concepts/Practice.md",
            """# Practice

Use the current API-first practice. ^practice-current

> [!provenance]- Provenance
> schema: kb-prov-v1
> blocks:
>   practice-current:
>     sources: [raw/notes/current.md]
>     observed: 2026-05-01
>     checked: 2026-06-20
>     status: current
>     confidence: high
""",
        )
        self.write(
            "wiki/concepts/Old Practice.md",
            """# Old Practice

Use the old platform-first practice. ^practice-old

> [!provenance]- Provenance
> schema: kb-prov-v1
> blocks:
>   practice-old:
>     sources: [raw/notes/old.md]
>     observed: 2016-08-30
>     checked: 2026-06-24
>     status: historical
>     confidence: high
""",
        )

        packet = build_query_packet(
            self.root,
            query="What is the current development practice?",
            pages=[
                "wiki/concepts/Old Practice.md",
                "wiki/concepts/Practice.md",
            ],
        )

        self.assertEqual(packet["query_intent"], "current")
        self.assertEqual(
            [block["id"] for block in packet["ranked_blocks"]],
            ["practice-current", "practice-old"],
        )
        self.assertEqual(packet["ranked_blocks"][0]["freshness_action"], "prefer")
        self.assertEqual(packet["ranked_blocks"][1]["freshness_action"], "rank-lower-explain")
        self.assertIn("historical", packet["ranked_blocks"][1]["freshness_note"])

    def test_reports_retrieved_legacy_pages_without_block_provenance(self):
        self.write(
            "wiki/concepts/Legacy.md",
            """# Legacy

This page has not been migrated to block provenance yet.
""",
        )

        packet = build_query_packet(
            self.root,
            query="What is current?",
            pages=["wiki/concepts/Legacy.md"],
        )

        self.assertEqual(packet["ranked_blocks"], [])
        self.assertEqual(packet["legacy_pages"][0]["path"], "wiki/concepts/Legacy.md")
        self.assertEqual(packet["legacy_pages"][0]["reason"], "no-block-provenance")

    def test_minimal_stamp_is_reported_as_page_caution(self):
        self.write(
            "wiki/concepts/Stamped.md",
            """# Stamped

## Freshness Status

This page has a minimal provenance stamp only. ^freshness-status

> [!provenance]- Provenance
> schema: kb-prov-v1
> migration_status: legacy-inferred-minimal
> blocks:
>   freshness-status:
>     sources: [raw/notes/source.md]
>     checked: 2026-06-24
>     status: current
>     confidence: medium
>     provenance_quality: minimal-risk-stamp
>     review_mode: needs-currentness-answer
>     evidence_latest: 2018-07-01
""",
        )

        packet = build_query_packet(
            self.root,
            query="What is current?",
            pages=["wiki/concepts/Stamped.md"],
        )

        block = packet["ranked_blocks"][0]
        self.assertEqual(block["freshness_action"], "use-as-page-caution")
        self.assertIn("Minimal page-level freshness stamp only", block["freshness_note"])
        self.assertIn("review mode needs-currentness-answer", block["freshness_note"])

    def test_resolves_qmd_wiki_uris_to_real_page_paths(self):
        self.write("wiki/concepts/Recommend Development Practices.md", "# RDP\n")
        self.write("raw/notes/Recommend Development Practices.md", "# Raw\n")

        pages = resolve_qmd_result_pages(
            self.root,
            [
                "qmd://tomtom/raw/notes/Recommend-Development-Practices.md",
                "qmd://tomtom/wiki/concepts/Recommend-Development-Practices.md",
            ],
        )

        self.assertEqual(pages, ["wiki/concepts/Recommend Development Practices.md"])

    def test_qmd_raw_hit_with_wikilink_maps_to_canonical_page(self):
        self.write(
            "wiki/concepts/Concept.md",
            """# Concept

Current canonical claim. ^claim-current

> [!provenance]- Provenance
> schema: kb-prov-v1
> blocks:
>   claim-current:
>     sources: [raw/notes/Raw Update.md]
>     observed: 2026-06-20
>     checked: 2026-06-24
>     status: current
>     confidence: high
""",
        )
        self.write(
            "raw/notes/Raw Update.md",
            """---
date: 2026-06-20
---

This raw note links to [[Concept]].
""",
        )

        packet = build_query_packet_from_qmd_results(
            self.root,
            query="What is current?",
            result_files=["qmd://tomtom/raw/notes/Raw-Update.md"],
        )

        self.assertEqual(packet["candidate_pages"], ["wiki/concepts/Concept.md"])
        self.assertEqual(packet["ranked_blocks"][0]["id"], "claim-current")
        self.assertEqual(packet["raw_mappings"][0]["raw_path"], "raw/notes/Raw Update.md")
        self.assertEqual(packet["raw_mappings"][0]["mapped_pages"], ["wiki/concepts/Concept.md"])
        self.assertIn("wikilink", packet["raw_mappings"][0]["reasons"])
        self.assertEqual(packet["raw_evidence"], [])

    def test_qmd_raw_hit_with_title_variant_maps_to_canonical_page(self):
        self.write(
            "wiki/concepts/Recommend Development Practices.md",
            """# Recommend Development Practices

Historical claim. ^rdp-claim

> [!provenance]- Provenance
> schema: kb-prov-v1
> blocks:
>   rdp-claim:
>     sources: [raw/notes/2026-01-01 Recommend Development Practices.md]
>     observed: 2026-01-01
>     checked: 2026-06-24
>     status: historical
>     confidence: high
""",
        )
        self.write(
            "raw/notes/2026-01-01 Recommend Development Practices.md",
            """---
date: 2026-01-01
---

# 2026-01-01 Recommend Development Practices

Raw copy of the document.
""",
        )

        packet = build_query_packet_from_qmd_results(
            self.root,
            query="What did Recommend Development Practices say historically?",
            result_files=["qmd://tomtom/raw/notes/2026-01-01-Recommend-Development-Practices.md"],
        )

        self.assertEqual(packet["candidate_pages"], ["wiki/concepts/Recommend Development Practices.md"])
        self.assertEqual(packet["ranked_blocks"][0]["id"], "rdp-claim")
        self.assertIn("title-match", packet["raw_mappings"][0]["reasons"])

    def test_qmd_raw_hit_with_source_extension_suffix_maps_to_canonical_page(self):
        self.write(
            "wiki/concepts/Recommend Development Practices.md",
            """# Recommend Development Practices

Historical claim. ^rdp-claim

> [!provenance]- Provenance
> schema: kb-prov-v1
> blocks:
>   rdp-claim:
>     sources: [raw/notes/2017-07-29 Recommend Development Practices.docx.md]
>     observed: 2017-07-29
>     checked: 2026-06-24
>     status: historical
>     confidence: high
""",
        )
        self.write(
            "raw/notes/2017-07-29 Recommend Development Practices.docx.md",
            """---
date: 2017-07-29
---

# 2017-07-29 Recommend Development Practices.docx

Raw wrapper for a document copy.
""",
        )

        packet = build_query_packet_from_qmd_results(
            self.root,
            query="Recommend Development Practices history",
            result_files=["qmd://tomtom/raw/notes/2017-07-29-Recommend-Development-Practices-docx.md"],
        )

        self.assertEqual(packet["candidate_pages"], ["wiki/concepts/Recommend Development Practices.md"])
        self.assertEqual(packet["raw_evidence"], [])

    def test_qmd_unmapped_raw_hit_is_preserved_as_raw_evidence(self):
        self.write(
            "raw/notes/Only Raw.md",
            """---
date: 2026-06-20
---

# Only Raw

No canonical page exists yet.
""",
        )

        packet = build_query_packet_from_qmd_results(
            self.root,
            query="What is current?",
            result_files=["qmd://tomtom/raw/notes/Only-Raw.md"],
        )

        self.assertEqual(packet["candidate_pages"], [])
        self.assertEqual(packet["ranked_blocks"], [])
        self.assertEqual(packet["raw_mappings"], [])
        self.assertEqual(packet["raw_evidence"][0]["path"], "raw/notes/Only Raw.md")

    def test_qmd_ambiguous_normalized_wiki_path_is_unresolved(self):
        self.write("wiki/concepts/Foo Bar.md", "# Foo Bar\n")
        self.write("wiki/concepts/Foo_Bar.md", "# Foo Bar\n")

        packet = build_query_packet_from_qmd_results(
            self.root,
            query="What is current?",
            result_files=["qmd://tomtom/wiki/concepts/Foo-Bar.md"],
        )

        self.assertEqual(packet["candidate_pages"], [])
        self.assertEqual(packet["unresolved_qmd_results"], ["qmd://tomtom/wiki/concepts/Foo-Bar.md"])


class FreshnessQueryCliTests(VaultFixtureMixin, unittest.TestCase):
    def test_cli_outputs_query_packet_json(self):
        self.write(
            "wiki/concepts/Practice.md",
            """# Practice

Use the current practice. ^practice-current

> [!provenance]- Provenance
> schema: kb-prov-v1
> blocks:
>   practice-current:
>     sources: [raw/notes/current.md]
>     observed: 2026-05-01
>     checked: 2026-06-20
>     status: current
>     confidence: high
""",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/system/wiki-freshness-query.py"),
                "--root",
                str(self.root),
                "--query",
                "What is current?",
                "--page",
                "wiki/concepts/Practice.md",
                "--format",
                "json",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["ranked_blocks"][0]["id"], "practice-current")

    def test_qmd_with_no_resolved_wiki_pages_does_not_scan_entire_vault(self):
        import importlib.util

        self.write(
            "wiki/concepts/Practice.md",
            """# Practice

Use the current practice. ^practice-current

> [!provenance]- Provenance
> schema: kb-prov-v1
> blocks:
>   practice-current:
>     sources: [raw/notes/current.md]
>     observed: 2026-05-01
>     checked: 2026-06-20
>     status: current
>     confidence: high
""",
        )
        script_path = ROOT / "scripts/system/wiki-freshness-query.py"
        spec = importlib.util.spec_from_file_location("wiki_freshness_query_cli", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        argv = [
            "wiki-freshness-query.py",
            "--root",
            str(self.root),
            "--query",
            "nothing relevant",
            "--qmd",
            "--format",
            "json",
        ]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(
            module,
            "_run_qmd_query",
            return_value=["qmd://tomtom/raw/notes/Only-Raw.md"],
        ), mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            rc = module.main()

        self.assertEqual(rc, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["candidate_pages"], [])
        self.assertEqual(payload["ranked_blocks"], [])
        self.assertEqual(payload["legacy_pages"], [])
        self.assertEqual(payload["raw_evidence"], [])


class FreshnessQueryCliGuardTests(VaultFixtureMixin, unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/system/wiki-freshness-query.py"),
                "--root",
                str(self.root),
                "--query",
                "current state",
                *args,
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_rejects_negative_limit(self):
        result = self.run_cli("--limit", "-1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("limit", result.stderr.lower())

    def test_rejects_negative_qmd_limit(self):
        result = self.run_cli("--qmd-limit", "-3")
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
