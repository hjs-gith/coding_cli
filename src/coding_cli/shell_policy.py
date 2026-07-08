"""Policy helpers for run_shell: a per-project allowlist and a best-effort
dangerous-command warning.

The allowlist lets the user pick "always allow" for a command at the confirm
prompt; entries are stored one per line in ``<workdir>/.coding_cli/
allowed_commands.txt`` and can be hand-edited. Matching is prefix-based but
refuses to match commands that chain or redirect, so a dangerous command cannot
be tacked onto an allowed prefix. ``is_dangerous`` is a heuristic warning, NOT a
security boundary.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from .history import DIR_NAME as _HISTORY_DIR

ALLOWLIST_FILE = "allowed_commands.txt"

# Shell control / redirection metacharacters. If a command contains any of these
# it must be confirmed explicitly — an allowlisted prefix never covers it.
_CHAIN_RE = re.compile(r"[&;|`<>]|\$\(")

# Best-effort dangerous-command patterns -> human label. A warning, not a gate.
_DANGEROUS = [
    (re.compile(r"\brm\b\s+(?:-\S*\s+)*-\S*r\S*f|\brm\b\s+(?:-\S*\s+)*-\S*f\S*r"), "rm -rf"),
    (re.compile(r"\brm\b\s+-\w*\s+-\w*"), "rm with combined flags"),
    (re.compile(r":\s*\(\s*\)\s*\{"), "fork bomb"),
    (re.compile(r"\bmkfs\b"), "mkfs (format filesystem)"),
    (re.compile(r"\bdd\b.*\bof=/dev/"), "dd to a device"),
    (re.compile(r">\s*/dev/(?:sd|nvme|disk|hd)"), "overwrite a disk device"),
    (re.compile(r"\bsudo\b"), "sudo"),
    (re.compile(r"\bchmod\b\s+.*-\w*R|\bchown\b\s+.*-\w*R"), "recursive chmod/chown"),
    (re.compile(r"\bgit\b.*\bpush\b.*(?:--force|-f\b|--force-with-lease)"), "git push --force"),
    (re.compile(r"\b(?:curl|wget)\b.*\|\s*(?:sudo\s+)?(?:sh|bash|zsh)\b"), "pipe download to shell"),
    (re.compile(r"\b(?:shutdown|reboot|halt|poweroff)\b"), "shutdown/reboot"),
]


def is_dangerous(command: str) -> Optional[str]:
    """Return a label if ``command`` matches a known dangerous pattern, else None."""
    for pattern, label in _DANGEROUS:
        if pattern.search(command):
            return label
    return None


def matches_allowlist(command: str, entries: List[str]) -> bool:
    """True if ``command`` is covered by an allowlist entry.

    An entry matches when the command equals it, or begins with the entry
    followed by a space AND the command has no chaining/redirection — so a
    dangerous command cannot be appended to an allowed prefix.
    """
    cmd = command.strip()
    if not cmd:
        return False
    for entry in entries:
        e = entry.strip()
        if not e or e.startswith("#"):
            continue
        if cmd == e:
            return True
        if cmd.startswith(e + " ") and not _CHAIN_RE.search(cmd):
            return True
    return False


def load_allowlist(path: Path) -> List[str]:
    """Read allowlist entries (skipping blanks and ``#`` comments). Missing → []."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    entries: List[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            entries.append(stripped)
    return entries


def allowlist_path(workdir: Path) -> Path:
    """Location of the per-project allowlist file."""
    return Path(workdir).resolve() / _HISTORY_DIR / ALLOWLIST_FILE


def append_allowlist(path: Path, command: str) -> None:
    """Append ``command`` to the allowlist, creating the dir + self-ignore first."""
    path.parent.mkdir(parents=True, exist_ok=True)
    gitignore = path.parent / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n", encoding="utf-8")
    header = ""
    if not path.exists():
        header = (
            "# run_shell commands coding-cli auto-approves. One command (or "
            "prefix) per line; # comments and blank lines are ignored.\n"
        )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(header + command.strip() + "\n")
