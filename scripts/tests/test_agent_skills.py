"""Keep coding-agent instructions and skills discoverable and internally consistent."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIRECTORY = REPOSITORY_ROOT / ".github" / "skills"
AGENTS = REPOSITORY_ROOT / "AGENTS.md"
SKILL_DIRECTORIES = sorted(path for path in SKILLS_DIRECTORY.iterdir() if path.is_dir())
# Repository-relative paths quoted in backticks, e.g. `scripts/dev.py` or `.github/skills/x/y.py`.
QUOTED_REPOSITORY_PATH = re.compile(
    r"`((?:\.github|scripts|student-\d|shared|ai-services|deployment|docs)/[^`\s<>*]+)`"
)


def _front_matter(skill: Path) -> dict[str, object]:
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, f"{skill.name}/SKILL.md must start with YAML front matter"
    value = yaml.safe_load(match.group(1))
    assert isinstance(value, dict)
    return value


def test_claude_code_reads_the_shared_agent_instructions() -> None:
    assert (REPOSITORY_ROOT / "CLAUDE.md").read_text(encoding="utf-8").strip() == "@AGENTS.md"


def test_skills_have_one_canonical_home() -> None:
    assert SKILL_DIRECTORIES
    for duplicate in (".claude/skills", ".agents/skills"):
        assert not (REPOSITORY_ROOT / duplicate).exists(), (
            f"keep skills in .github/skills, not {duplicate}"
        )


@pytest.mark.parametrize("skill", SKILL_DIRECTORIES, ids=lambda path: path.name)
def test_skill_front_matter_is_valid(skill: Path) -> None:
    metadata = _front_matter(skill)
    name = metadata.get("name")
    description = metadata.get("description")
    assert name == skill.name
    assert isinstance(name, str) and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
    assert len(name) <= 64
    assert isinstance(description, str) and 0 < len(description) <= 1024


@pytest.mark.parametrize("skill", SKILL_DIRECTORIES, ids=lambda path: path.name)
def test_every_skill_is_indexed_for_agents_without_native_skill_loading(skill: Path) -> None:
    assert f".github/skills/{skill.name}/SKILL.md" in AGENTS.read_text(encoding="utf-8")


def test_agents_index_names_only_existing_skills() -> None:
    indexed = set(re.findall(r"\.github/skills/([a-z0-9-]+)/SKILL\.md", AGENTS.read_text("utf-8")))
    assert indexed == {skill.name for skill in SKILL_DIRECTORIES}


@pytest.mark.parametrize("skill", SKILL_DIRECTORIES, ids=lambda path: path.name)
def test_skill_repository_paths_exist(skill: Path) -> None:
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    missing = [
        quoted
        for quoted in QUOTED_REPOSITORY_PATH.findall(text)
        if not (REPOSITORY_ROOT / quoted.rstrip("/")).exists()
    ]
    assert missing == []
