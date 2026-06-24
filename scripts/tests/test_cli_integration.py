"""End-to-end subprocess tests for scripts/wiki-doctor.py in batch mode.

These run the real CLI against throwaway fixture vaults and assert on exit
codes and the JSON payload — never touching the real vault.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "wiki-doctor.py"


class CliIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="wikidoctor-cli-"))
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))

    def write(self, rel, content):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def run_doctor(self, *extra):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--batch-mode", "--quiet",
             "--format", "json", *extra, str(self.root)],
            capture_output=True, text=True, timeout=120,
        )

    def test_clean_vault_exits_zero(self):
        self.write("wiki/concepts/a.md",
                   "This page has plenty of real prose words here.\n\nSee also [[b]].\n")
        self.write("wiki/concepts/b.md",
                   "This page also has plenty of real prose words here.\n\nSee also [[a]].\n")
        proc = self.run_doctor()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["summary"]["broken"], 0)
        self.assertEqual(payload["recommendations"][0]["id"], "freshness-check")
        self.assertEqual(payload["recommendations"][0]["skill"], "wiki-freshness")

    def test_broken_link_exits_one_with_json_entry(self):
        self.write("wiki/concepts/a.md",
                   "Plenty of real prose words so this is clearly not a stub page.\n"
                   "\nA reference to [[does-not-exist]] appears mid sentence here.\n")
        proc = self.run_doctor()
        self.assertEqual(proc.returncode, 1, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["summary"]["broken"], 1)
        self.assertEqual(payload["broken_links"][0]["target"], "does-not-exist")

    def test_fixable_link_with_fix_exits_zero_and_rewrites(self):
        # Regression for Bug 4: a fully-fixed run must report 0 remaining broken
        # and exit 0, with the file actually rewritten on disk.
        self.write("wiki/concepts/foo_ bar.md",
                   "Target page with plenty of prose words to avoid the stub check entirely.\n")
        page = self.write(
            "wiki/concepts/a.md",
            "Plenty of additional prose words here to dodge any stub flagging at all.\n"
            "\nThis sentence references [[foo: bar]] mid sentence for the link test.\n",
        )
        proc = self.run_doctor("--fix-simple-errors")
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["summary"]["broken"], 0, payload)
        self.assertGreaterEqual(payload["summary"]["fixed_links"], 1)
        # File rewritten on disk.
        self.assertIn("[[foo_ bar]]", page.read_text(encoding="utf-8"))
        # No remaining broken-link issue from the vault scan. (Exit may still be
        # non-zero if other issue classes exist, but here there are none.)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
