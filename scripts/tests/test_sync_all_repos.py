#!/usr/bin/env python3
"""Tests for sync-all-repos.sh orchestration."""

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class SyncAllReposTests(unittest.TestCase):
    def make_fixture(self) -> tuple[Path, Path]:
        tmp = Path(tempfile.mkdtemp(prefix="kb-sync-"))
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))

        src = tmp / "TomTom"
        src.mkdir()
        shutil.copy2(ROOT / "sync-all-repos.sh", src / "sync-all-repos.sh")
        (src / "scripts/system").mkdir(parents=True)
        shutil.copy2(
            ROOT / "scripts/system/copy-claude-skills-to-other-agents.sh",
            src / "scripts/system/copy-claude-skills-to-other-agents.sh",
        )
        (src / ".claude/skills/wiki-example").mkdir(parents=True)
        (src / ".claude/skills/wiki-example/SKILL.md").write_text(
            "---\nname: wiki-example\n---\n\nfresh\n",
            encoding="utf-8",
        )
        (src / ".claude/agents").mkdir(parents=True)
        (src / ".agents/skills/wiki-example").mkdir(parents=True)
        (src / ".agents/skills/wiki-example/SKILL.md").write_text(
            "---\nname: wiki-example\n---\n\nstale\n",
            encoding="utf-8",
        )

        home = tmp / "home"
        (home / "source/rijnb/knowledge-base-wiki").mkdir(parents=True)
        (home / "source/tomtom-internal/knowledge-base-wiki").mkdir(parents=True)

        fake_bin = tmp / "bin"
        fake_bin.mkdir()
        (fake_bin / "rsync").write_text(
            "#!/usr/bin/env bash\n"
            "exit 0\n",
            encoding="utf-8",
        )
        (fake_bin / "rsync").chmod(0o755)

        return src, home

    def test_sync_refreshes_agent_skill_mirrors_first(self):
        src, home = self.make_fixture()
        env = dict(os.environ)
        env["HOME"] = str(home)
        env["PATH"] = f"{src.parent / 'bin'}:{env['PATH']}"

        proc = subprocess.run(
            ["bash", "sync-all-repos.sh"],
            cwd=src,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            (src / ".agents/skills/wiki-example/SKILL.md").read_text(encoding="utf-8"),
            (src / ".claude/skills/wiki-example/SKILL.md").read_text(encoding="utf-8"),
        )
        self.assertTrue((src / ".codex/skills/wiki-example/SKILL.md").is_file())
        self.assertTrue((src / ".junie/skills/wiki-example/SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
