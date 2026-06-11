"""Shared tempdir vault fixture for wiki-doctor tests.

Tests must never touch the real vault — every fixture builds an isolated
temporary directory tree and cleans it up afterwards.
"""

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class VaultFixtureMixin:
    """Creates a throwaway vault root under a tempdir and offers write helpers."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="wikidoctor-test-"))
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))

    def write(self, rel: str, content: str, encoding: str = "utf-8") -> Path:
        """Write a text file at root/rel, creating parent dirs."""
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)
        return p

    def write_bytes(self, rel: str, data: bytes) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def read(self, rel: str) -> str:
        return (self.root / rel).read_text(encoding="utf-8")
