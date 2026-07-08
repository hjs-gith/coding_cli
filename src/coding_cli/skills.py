"""Custom skills: Claude Code-style Markdown capabilities loaded on demand.

A skill is a folder containing a ``SKILL.md`` with YAML-ish frontmatter
(``name``, ``description``) and a Markdown instruction body. Skills are
auto-discovered from several directories; only name + description are advertised
to the model, and the full body is loaded when the model calls
``use_skill(name)`` (progressive disclosure).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Cap the file listing appended to a loaded skill so a stray large folder can't
# flood the model's context.
MAX_SKILL_FILES = 50


@dataclass
class Skill:
    """A discovered skill."""

    name: str
    description: str
    path: Path  # the SKILL.md file
    body: str


def skill_search_dirs(workdir: Path) -> List[Path]:
    """Directories scanned for skills, in increasing-priority order.

    Later directories override earlier ones by skill name, so a project-local
    ``./skills`` wins over the user config dir, which wins over bundled skills.
    """
    here = Path(__file__).resolve().parent
    bundled = here.parent.parent / "skills"  # repo-root/skills
    user = Path.home() / ".config" / "coding-cli" / "skills"
    project = Path(workdir).resolve() / "skills"
    return [bundled, user, project]


def discover_skills(workdir: Path) -> Dict[str, Skill]:
    """Find and parse all skills reachable from ``workdir``."""
    found: Dict[str, Skill] = {}
    for directory in skill_search_dirs(workdir):
        if not directory.is_dir():
            continue
        for skill_md in sorted(directory.glob("*/SKILL.md")):
            skill = _parse_skill(skill_md)
            if skill is not None:
                found[skill.name] = skill  # later dirs override by name
    return found


def catalog(skills: Dict[str, Skill]) -> List[Tuple[str, str]]:
    """Return ``(name, description)`` pairs for the protocol preamble."""
    return [(s.name, s.description) for s in sorted(skills.values(), key=lambda s: s.name)]


def _parse_skill(skill_md: Path) -> Optional[Skill]:
    try:
        raw = skill_md.read_text(encoding="utf-8")
    except OSError:
        return None
    front, body = _split_frontmatter(raw)
    name = front.get("name") or skill_md.parent.name
    description = front.get("description", "").strip()
    return Skill(
        name=name.strip(),
        description=description,
        path=skill_md,
        body=body.strip(),
    )


def _split_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    """Split a leading ``---`` YAML block into a flat dict + the remaining body.

    A deliberately tiny parser (only ``key: value`` pairs) so we avoid a PyYAML
    dependency. Anything fancier in frontmatter is ignored.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    front: Dict[str, str] = {}
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
        line = lines[i]
        if ":" in line:
            key, _, value = line.partition(":")
            front[key.strip()] = value.strip().strip("\"'")
    if end is None:
        return {}, text  # no closing fence; treat whole thing as body
    body = "\n".join(lines[end + 1 :])
    return front, body


def _skill_files(directory: Path) -> List[Path]:
    """Absolute paths of a skill's bundled files (scripts, data), excluding the
    SKILL.md itself and noise like hidden dirs and ``__pycache__``."""
    files: List[Path] = []
    for p in sorted(directory.rglob("*")):
        if not p.is_file() or p.name == "SKILL.md":
            continue
        rel_parts = p.relative_to(directory).parts
        if any(part.startswith(".") or part == "__pycache__" for part in rel_parts):
            continue
        files.append(p)
    return files


def make_loader(skills: Dict[str, Skill]):
    """Build a ``load_skill(name) -> str`` callable for the tool context."""

    def load_skill(name: str) -> str:
        skill = skills.get(name)
        if skill is None:
            available = ", ".join(sorted(skills)) or "(none)"
            return f"ERROR: unknown skill '{name}'. Available skills: {available}"
        header = f"# Skill: {skill.name}\n{skill.description}\n\n"
        directory = skill.path.parent
        section = f"\n\n---\nSkill directory: {directory}"
        files = _skill_files(directory)
        if files:
            shown = files[:MAX_SKILL_FILES]
            listing = "\n".join(f"- {p}" for p in shown)
            if len(files) > MAX_SKILL_FILES:
                listing += f"\n- ... ({len(files) - MAX_SKILL_FILES} more)"
            section += (
                "\nBundled files (use these full paths — run scripts with "
                "run_shell, read files with read_file when inside the working "
                "directory):\n" + listing
            )
        return header + skill.body + section

    return load_skill
