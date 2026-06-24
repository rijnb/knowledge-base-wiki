"""Argument-handling guards for qmd-sync-collections.sh.

These run before any `qmd` invocation, so they do not require the qmd CLI.
"""

import subprocess
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent.parent / "system" / "qmd-sync-collections.sh"


class QmdSyncArgTests(unittest.TestCase):
    def run_script(self, *args):
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            text=True,
            capture_output=True,
            timeout=30,
        )

    def test_root_without_value_fails_cleanly(self):
        result = self.run_script("--root")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--root", result.stderr)

    def test_unknown_arg_fails(self):
        result = self.run_script("--bogus")
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
