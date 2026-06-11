#!/usr/bin/env bash
# Copy .claude skills and agents to other agent clients.
set -euo pipefail

if [ ! -d .claude ]; then
    echo "Wrong directory; must be run from directory with .claude"
    exit 1
fi

copy_tree() {
    local src="$1"
    local dest="$2"

    rm -rf "$dest"
    mkdir -p "$(dirname "$dest")"
    cp -R "$src" "$dest"
}

copy_tree .claude/skills .junie/skills
copy_tree .claude/agents .junie/agents

copy_tree .claude/skills .agents/skills
copy_tree .claude/agents .agents/agents

copy_tree .claude/skills .codex/skills
rm -rf .codex/agents
mkdir -p .codex/agents

python3 - <<'PY'
from pathlib import Path
import json


def parse_agent(path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise SystemExit(f"Agent file lacks frontmatter: {path}")
    _, frontmatter, body = text.split("---\n", 2)

    metadata = {}
    skills = []
    current_key = None
    for raw_line in frontmatter.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        if line.startswith("  - ") and current_key == "skills":
            skills.append(line[4:].strip())
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        current_key = key.strip()
        value = value.strip()
        if current_key == "skills":
            continue
        metadata[current_key] = value

    if not metadata.get("name") or not metadata.get("description"):
        raise SystemExit(f"Agent file misses name/description: {path}")

    return metadata, skills, body.strip()


def toml_string(value):
    return json.dumps(value, ensure_ascii=False)


source_dir = Path(".claude/agents")
target_dir = Path(".codex/agents")

for source in sorted(source_dir.glob("*.md")):
    metadata, skills, body = parse_agent(source)
    instructions = body
    if skills:
        skill_list = ", ".join(f"`{skill}`" for skill in skills)
        instructions = (
            f"Use the repository skill(s) {skill_list} before doing the work. "
            f"{instructions}"
        )

    target = target_dir / f"{metadata['name']}.toml"
    target.write_text(
        "\n".join(
            [
                f"name = {toml_string(metadata['name'])}",
                f"description = {toml_string(metadata['description'])}",
                f"developer_instructions = {toml_string(instructions)}",
                "",
            ]
        ),
        encoding="utf-8",
    )
PY

echo "Claude skills copied to .junie/, .agents/, and .codex/; Codex agents generated as TOML."
