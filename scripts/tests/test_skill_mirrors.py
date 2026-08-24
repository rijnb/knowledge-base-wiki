#!/usr/bin/env python3
"""Guards that .agents/, .junie/ and .codex/ skills match .claude/ verbatim.

`.claude/skills` is canonical; the other three are copies produced by
scripts/system/copy-claude-skills-to-other-agents.sh. Nothing failed when that
sync was skipped, so the mirrors quietly rotted: a rename shipped to .claude
only, leaving the other harnesses following instructions for a layout that no
longer existed. This test turns that into a visible failure.

Run the sync to fix a failure here:
    bash scripts/system/copy-claude-skills-to-other-agents.sh
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / ".claude" / "skills"
MIRRORS = (".agents", ".junie", ".codex")

FIX = "run: bash scripts/system/copy-claude-skills-to-other-agents.sh"


def relative_files(base: Path) -> dict[str, bytes]:
    """Every file under base, keyed by its path relative to base."""
    return {
        str(p.relative_to(base)): p.read_bytes()
        for p in sorted(base.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


@unittest.skipUnless(CANONICAL.is_dir(), "no .claude/skills in this checkout")
class SkillMirrorTests(unittest.TestCase):
    def test_every_mirror_exists(self):
        for mirror in MIRRORS:
            with self.subTest(mirror=mirror):
                self.assertTrue((ROOT / mirror / "skills").is_dir(),
                                f"{mirror}/skills is missing — {FIX}")

    def test_mirrors_have_the_same_skill_set(self):
        expected = {p.name for p in CANONICAL.iterdir() if p.is_dir()}
        for mirror in MIRRORS:
            with self.subTest(mirror=mirror):
                path = ROOT / mirror / "skills"
                if not path.is_dir():
                    self.skipTest(f"{mirror}/skills is missing")
                actual = {p.name for p in path.iterdir() if p.is_dir()}
                self.assertEqual(
                    actual, expected,
                    f"{mirror}/skills has a different skill set — {FIX}")

    def test_mirror_contents_are_identical_to_claude(self):
        expected = relative_files(CANONICAL)
        for mirror in MIRRORS:
            with self.subTest(mirror=mirror):
                path = ROOT / mirror / "skills"
                if not path.is_dir():
                    self.skipTest(f"{mirror}/skills is missing")
                actual = relative_files(path)
                stale = sorted(
                    name for name in expected.keys() & actual.keys()
                    if expected[name] != actual[name]
                )
                self.assertEqual(
                    stale, [],
                    f"{mirror}/skills is out of date for {stale} — {FIX}")
                self.assertEqual(
                    sorted(actual.keys()), sorted(expected.keys()),
                    f"{mirror}/skills has extra or missing files — {FIX}")


if __name__ == "__main__":
    unittest.main()
