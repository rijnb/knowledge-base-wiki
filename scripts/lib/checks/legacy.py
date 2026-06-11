"""Detect leftover legacy converted/ directories and run the migration script.

The legacy conversion layout (dir/<name>.<ext> + dir/converted/<stem>.md) was
replaced by the _resources layout (dir/_resources/<name>.<ext> + companion
dir/<stem>.md).  scripts/system/migrate-converted-to-resources.py performs the
one-time migration; this check reports any converted/ directories that still
exist under raw/.
"""

import os
import subprocess
import sys
from pathlib import Path

MIGRATION_SCRIPT = Path("scripts") / "system" / "migrate-converted-to-resources.py"


def check_legacy_converted(root: Path, quiet: bool = False) -> dict:
    """Find legacy converted/ directories under raw/."""
    if not quiet:
        print("Checking for legacy converted/ directories...", file=sys.stderr)

    raw_dir = root / "raw"
    dirs: list[str] = []
    md_files = 0
    if raw_dir.is_dir():
        for dirpath, dirnames, filenames in os.walk(raw_dir):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            base = Path(dirpath)
            if base.name == "converted":
                dirs.append(str(base.relative_to(root)))
                md_files += sum(1 for f in filenames if f.endswith(".md"))

    return {
        "legacy_converted": sorted(dirs),
        "summary": {"converted_dirs_found": len(dirs), "converted_md_files": md_files},
    }


def run_migration(root: Path) -> dict:
    """Run migrate-converted-to-resources.py --apply from the vault root."""
    script = root / MIGRATION_SCRIPT
    if not script.is_file():
        return {"ran": False, "returncode": None,
                "error": f"migration script not found: {script}"}
    proc = subprocess.run(
        [sys.executable, str(script), "--apply"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return {
        "ran": True,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
