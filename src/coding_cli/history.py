"""Disk-backed change tracking so a session's file edits can be reviewed and undone.

Every mutating tool records the file's prior state here before it writes. Snapshots
live under ``<workdir>/.coding_cli/`` (which ignores itself via its own
``.gitignore``), and a ``journal.json`` persists the change stack so ``undo`` keeps
working across restarts. ``session_diff`` reports the net change of each touched
file against the baseline captured the first time it was seen.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

DIR_NAME = ".coding_cli"


@dataclass
class Change:
    """One recorded mutation, with enough state to revert it."""

    seq: int
    path: str  # relative to workdir
    action: str  # "write_file" | "edit_file"
    existed_before: bool
    backup: Optional[str]  # snapshot filename holding the prior bytes, or None


class ChangeHistory:
    """Records and reverts file mutations made during a session."""

    def __init__(self, workdir: Path) -> None:
        self.workdir = Path(workdir).resolve()
        self.dir = self.workdir / DIR_NAME
        self.snap_dir = self.dir / "snapshots"
        self.journal_path = self.dir / "journal.json"
        # In-memory state, hydrated from disk if a journal already exists.
        self._changes: List[Change] = []
        self._baselines: dict[str, Optional[str]] = {}
        self._seq = 0
        self._load()

    # --- persistence --------------------------------------------------------

    def _ensure_dir(self) -> None:
        if self.snap_dir.is_dir():
            return
        self.snap_dir.mkdir(parents=True, exist_ok=True)
        # Make the whole directory ignore itself, regardless of the project's
        # own .gitignore, so snapshots never pollute the user's git status.
        (self.dir / ".gitignore").write_text("*\n", encoding="utf-8")

    def _load(self) -> None:
        if not self.journal_path.is_file():
            return
        try:
            data = json.loads(self.journal_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self._changes = [Change(**c) for c in data.get("changes", [])]
        self._baselines = data.get("baselines", {})
        self._seq = data.get("seq", len(self._changes))

    def _save(self) -> None:
        payload = {
            "seq": self._seq,
            "changes": [asdict(c) for c in self._changes],
            "baselines": self._baselines,
        }
        self.journal_path.write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )

    # --- recording ----------------------------------------------------------

    def record(
        self,
        rel_path: str,
        before_text: Optional[str],
        existed_before: bool,
        action: str,
    ) -> None:
        """Snapshot a file's prior state before it is overwritten."""
        self._ensure_dir()
        self._seq += 1
        backup: Optional[str] = None
        if existed_before:
            backup = f"{self._seq:04d}.bak"
            (self.snap_dir / backup).write_text(
                before_text or "", encoding="utf-8"
            )
        # Capture the baseline (original state) the first time we touch a path.
        if rel_path not in self._baselines:
            self._baselines[rel_path] = before_text if existed_before else None
        self._changes.append(
            Change(
                seq=self._seq,
                path=rel_path,
                action=action,
                existed_before=existed_before,
                backup=backup,
            )
        )
        self._save()

    # --- review & undo ------------------------------------------------------

    def undo(self) -> str:
        """Revert the most recent recorded change. Repeatable."""
        if not self._changes:
            return "Nothing to undo."
        change = self._changes.pop()
        target = self.workdir / change.path
        if not change.existed_before:
            # The change created the file; undoing means removing it.
            try:
                target.unlink()
            except FileNotFoundError:
                pass
            result = f"Undid {change.action}: removed {change.path}"
        else:
            content = ""
            if change.backup:
                content = (self.snap_dir / change.backup).read_text(
                    encoding="utf-8"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            result = f"Undid {change.action}: restored {change.path}"
        # Drop the baseline once no remaining change references the path, so a
        # later session_diff doesn't report a file we've fully reverted.
        if all(c.path != change.path for c in self._changes):
            self._baselines.pop(change.path, None)
        self._save()
        return result

    def session_diff(self) -> str:
        """Unified diff of every touched file: baseline -> current on disk."""
        if not self._baselines:
            return "No changes recorded this session."
        chunks: List[str] = []
        for path in sorted(self._baselines):
            baseline = self._baselines[path] or ""
            target = self.workdir / path
            current = (
                target.read_text(encoding="utf-8") if target.is_file() else ""
            )
            if baseline == current:
                continue
            diff = difflib.unified_diff(
                baseline.splitlines(),
                current.splitlines(),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                lineterm="",
            )
            chunks.append("\n".join(diff))
        if not chunks:
            return "No net changes this session."
        return "\n\n".join(chunks)

    def summary(self) -> List[str]:
        """Sorted list of paths changed this session."""
        return sorted(self._baselines)
