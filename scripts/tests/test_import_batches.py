#!/usr/bin/env python3
"""Subprocess tests for ingest dedup: the stamping entrypoint and the
batch-creation script's rename/modify-aware filtering."""

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sha256_of(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


class StampEntrypointTests(unittest.TestCase):
    def make_vault(self) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="kb-stamp-"))
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        (tmp / "scripts").mkdir()
        shutil.copytree(ROOT / "scripts/lib", tmp / "scripts/lib")
        (tmp / "scripts/system").mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "scripts/system/wiki-stamp-log-hashes.py",
                     tmp / "scripts/system/wiki-stamp-log-hashes.py")
        (tmp / "raw/notes").mkdir(parents=True)
        (tmp / "wiki").mkdir()
        return tmp

    def test_entrypoint_stamps_log(self):
        tmp = self.make_vault()
        note = tmp / "raw/notes/Note.md"
        note.write_text("hello\n", encoding="utf-8")
        (tmp / "wiki/log.jsonl").write_text(
            json.dumps({"date": "2026-06-01 12:00:00", "session": 1,
                        "file": "raw/notes/Note.md", "summary": "x",
                        "pages_created": [], "pages_updated": []}) + "\n",
            encoding="utf-8")
        proc = subprocess.run(
            ["python3", "scripts/system/wiki-stamp-log-hashes.py"],
            cwd=tmp, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        entry = json.loads((tmp / "wiki/log.jsonl").read_text().splitlines()[0])
        self.assertEqual(entry["hash"], sha256_of(note))
        self.assertEqual(entry["mtime"], int(note.stat().st_mtime))


class ImportBatchDedupTests(unittest.TestCase):
    def make_vault(self) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="kb-batch-"))
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        (tmp / "scripts/system").mkdir(parents=True)
        shutil.copy2(ROOT / "scripts/system/wiki-create-import-batches.sh",
                     tmp / "scripts/system/wiki-create-import-batches.sh")
        (tmp / "raw/notes").mkdir(parents=True)
        (tmp / "wiki").mkdir()
        return tmp

    def stamped_entry(self, tmp: Path, rel: str) -> dict:
        p = tmp / rel
        return {"date": "2026-06-01 12:00:00", "session": 1, "file": rel,
                "hash": sha256_of(p), "mtime": int(p.stat().st_mtime),
                "summary": "x", "pages_created": [], "pages_updated": []}

    def write_log(self, tmp: Path, entries: list[dict]) -> None:
        (tmp / "wiki/log.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")

    def run_batches(self, tmp: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", "scripts/system/wiki-create-import-batches.sh", "--force"],
            cwd=tmp, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False)

    def new_files(self, tmp: Path) -> set:
        out = set()
        import_dir = tmp / ".import"
        if import_dir.exists():
            for bf in import_dir.glob("batch-import-*.txt"):
                out |= {l for l in bf.read_text().splitlines() if l.strip()}
        return out

    def test_renamed_file_is_not_reingested(self):
        tmp = self.make_vault()
        orig = tmp / "raw/notes/Original.md"
        orig.write_text("stable content\n", encoding="utf-8")
        self.write_log(tmp, [self.stamped_entry(tmp, "raw/notes/Original.md")])
        # Rename (preserves bytes -> same hash); the new name is not in the log.
        orig.rename(tmp / "raw/notes/Renamed.md")
        self.run_batches(tmp)
        self.assertNotIn("raw/notes/Renamed.md", self.new_files(tmp))

    def test_modified_file_is_reingested(self):
        tmp = self.make_vault()
        note = tmp / "raw/notes/Note.md"
        note.write_text("version one\n", encoding="utf-8")
        entry = self.stamped_entry(tmp, "raw/notes/Note.md")
        self.write_log(tmp, [entry])
        # Change content AND advance mtime past the logged value.
        note.write_text("version two — edited\n", encoding="utf-8")
        import os
        os.utime(note, (entry["mtime"] + 100, entry["mtime"] + 100))
        self.run_batches(tmp)
        self.assertIn("raw/notes/Note.md", self.new_files(tmp))

    def test_unchanged_file_is_skipped(self):
        tmp = self.make_vault()
        note = tmp / "raw/notes/Note.md"
        note.write_text("unchanged\n", encoding="utf-8")
        self.write_log(tmp, [self.stamped_entry(tmp, "raw/notes/Note.md")])
        self.run_batches(tmp)
        self.assertNotIn("raw/notes/Note.md", self.new_files(tmp))

    def test_touched_same_content_is_skipped(self):
        tmp = self.make_vault()
        note = tmp / "raw/notes/Note.md"
        note.write_text("same bytes\n", encoding="utf-8")
        entry = self.stamped_entry(tmp, "raw/notes/Note.md")
        self.write_log(tmp, [entry])
        import os
        os.utime(note, (entry["mtime"] + 500, entry["mtime"] + 500))  # mtime moves, bytes don't
        self.run_batches(tmp)
        self.assertNotIn("raw/notes/Note.md", self.new_files(tmp))

    def test_brand_new_file_is_ingested(self):
        tmp = self.make_vault()
        (tmp / "raw/notes/Fresh.md").write_text("brand new\n", encoding="utf-8")
        self.write_log(tmp, [])  # empty log
        self.run_batches(tmp)
        self.assertIn("raw/notes/Fresh.md", self.new_files(tmp))

    def test_unstamped_logged_path_is_still_skipped(self):
        # Legacy / pending entry: logged path, no hash/mtime -> old behavior (skip).
        tmp = self.make_vault()
        note = tmp / "raw/notes/Pending.md"
        note.write_text("just ingested, not yet stamped\n", encoding="utf-8")
        self.write_log(tmp, [{"date": "2026-06-01 12:00:00", "session": 1,
                              "file": "raw/notes/Pending.md", "summary": "x",
                              "pages_created": [], "pages_updated": []}])
        self.run_batches(tmp)
        self.assertNotIn("raw/notes/Pending.md", self.new_files(tmp))

    def test_ingest_false_markdown_and_explicit_linked_files_are_skipped(self):
        tmp = self.make_vault()
        (tmp / "raw/notes/_resources").mkdir(parents=True)
        (tmp / "raw/notes/docs").mkdir(parents=True)
        (tmp / "raw/notes/Sensitive.md").write_text(
            "---\ningest: false\n---\n"
            "![[secret.pdf]]\n"
            "[plan](docs/Plan.docx)\n"
            "[mail](_resources/foo_(mail).pdf)\n"
            "[remote](https://example.com/doc.pdf)\n",
            encoding="utf-8")
        (tmp / "raw/notes/_resources/secret.pdf").write_bytes(b"secret")
        (tmp / "raw/notes/_resources/foo_(mail).pdf").write_bytes(b"mail")
        (tmp / "raw/notes/docs/Plan.docx").write_bytes(b"plan")
        (tmp / "raw/notes/Public.md").write_text("public\n", encoding="utf-8")
        self.write_log(tmp, [])

        proc = self.run_batches(tmp)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        files = self.new_files(tmp)
        self.assertNotIn("raw/notes/Sensitive.md", files)
        self.assertNotIn("raw/notes/_resources/secret.pdf", files)
        self.assertNotIn("raw/notes/_resources/foo_(mail).pdf", files)
        self.assertNotIn("raw/notes/docs/Plan.docx", files)
        self.assertIn("raw/notes/Public.md", files)
        self.assertIn("Skipped (ingest:false): 1", proc.stdout)
        self.assertIn("Sensitive.md (+3 linked files)", proc.stdout)
        self.assertNotIn("secret.pdf", proc.stdout)
        self.assertNotIn("foo_(mail).pdf", proc.stdout)
        self.assertNotIn("Plan.docx", proc.stdout)

    def test_ingest_false_accepts_quoted_case_variants_only(self):
        tmp = self.make_vault()
        (tmp / "raw/notes/Quoted.md").write_text(
            "---\ningest: 'False'\n---\nprivate\n", encoding="utf-8")
        (tmp / "raw/notes/No.md").write_text(
            "---\ningest: no\n---\nnormal\n", encoding="utf-8")
        self.write_log(tmp, [])

        proc = self.run_batches(tmp)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        files = self.new_files(tmp)
        self.assertNotIn("raw/notes/Quoted.md", files)
        self.assertIn("raw/notes/No.md", files)
        self.assertIn("Quoted.md", proc.stdout)


class RelinkEntrypointTests(unittest.TestCase):
    def make_vault(self) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="kb-relink-"))
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        (tmp / "scripts").mkdir()
        shutil.copytree(ROOT / "scripts/lib", tmp / "scripts/lib")
        (tmp / "scripts/system").mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "scripts/system/wiki-relink-log-renames.py",
                     tmp / "scripts/system/wiki-relink-log-renames.py")
        (tmp / "raw/notes").mkdir(parents=True)
        (tmp / "wiki").mkdir()
        return tmp

    def test_entrypoint_relinks_renamed_entry(self):
        tmp = self.make_vault()
        new = tmp / "raw/notes/New.md"
        new.write_text("stable\n", encoding="utf-8")
        (tmp / "wiki/log.jsonl").write_text(
            json.dumps({"date": "2026-06-01 12:00:00", "session": 1,
                        "file": "raw/notes/Old.md", "hash": sha256_of(new),
                        "mtime": 1, "summary": "x",
                        "pages_created": [], "pages_updated": []}) + "\n",
            encoding="utf-8")
        proc = subprocess.run(
            ["python3", "scripts/system/wiki-relink-log-renames.py"],
            cwd=tmp, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        entry = json.loads((tmp / "wiki/log.jsonl").read_text().splitlines()[0])
        self.assertEqual(entry["file"], "raw/notes/New.md")


if __name__ == "__main__":
    unittest.main()
