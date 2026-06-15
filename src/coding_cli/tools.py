"""Local tools the agent can invoke: file IO and shell execution.

Each tool returns a string (its result or an error message). Mutating tools
(``write_file``, ``edit_file``, ``run_shell``) are gated through a confirmation
callback so the CLI can ask the user before anything touches disk.
"""

from __future__ import annotations

import difflib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from .history import DIR_NAME as HISTORY_DIR

if TYPE_CHECKING:
    from .history import ChangeHistory

MAX_OUTPUT_CHARS = 20_000
SHELL_TIMEOUT_SECONDS = 120
MAX_DIFF_LINES = 120

# A confirmation callback: (action, detail, preview) -> bool. ``preview`` is an
# optional unified diff the UI can show on demand. Returning False aborts.
ConfirmFn = Callable[[str, str, str], bool]

MUTATING_TOOLS = {"write_file", "edit_file", "run_shell"}


class ToolError(Exception):
    """Recoverable tool failure; the message is fed back to the model."""


@dataclass
class ToolContext:
    """Shared state passed to every tool invocation."""

    workdir: Path
    confirm: Optional[ConfirmFn] = None
    # use_skill needs access to the skill registry; injected by the agent.
    load_skill: Optional[Callable[[str], str]] = None
    # Records prior file state so changes can be reviewed and undone.
    history: Optional["ChangeHistory"] = None
    # Workdir-relative paths the file tools refuse to touch (the ``.coding_cli``
    # snapshot dir is always reserved on top of these).
    deny: tuple[str, ...] = ()


def _reserved_paths(ctx: ToolContext) -> "list[tuple[Path, str]]":
    """Resolved (path, label) pairs the file tools must not touch: the always
    reserved ``.coding_cli`` snapshot dir plus any configured denylist entries."""
    workdir = ctx.workdir.resolve()
    reserved = [(workdir / HISTORY_DIR, HISTORY_DIR)]
    for entry in ctx.deny or ():
        reserved.append(((workdir / entry).resolve(), entry))
    return reserved


def _resolve(ctx: ToolContext, path: str) -> Path:
    """Resolve ``path`` under the workdir, rejecting escapes and reserved paths."""
    workdir = ctx.workdir.resolve()
    target = (workdir / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    try:
        target.relative_to(workdir)
    except ValueError:
        raise ToolError(
            f"Refusing to access '{path}': outside the working directory {workdir}."
        )
    for reserved, label in _reserved_paths(ctx):
        if target == reserved or reserved in target.parents:
            raise ToolError(
                f"Refusing to access '{path}': '{label}' is a protected path, "
                "off-limits to tools."
            )
    return target


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n... [truncated {len(text) - MAX_OUTPUT_CHARS} chars]"


def _confirm(ctx: ToolContext, action: str, detail: str, preview: str = "") -> None:
    if ctx.confirm is not None and not ctx.confirm(action, detail, preview):
        raise ToolError(f"User declined: {action}")


def _make_diff(path: str, before: str, after: str) -> str:
    """Build a truncated unified diff of a pending file change."""
    diff = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
    )
    if len(diff) > MAX_DIFF_LINES:
        omitted = len(diff) - MAX_DIFF_LINES
        diff = diff[:MAX_DIFF_LINES] + [f"... [truncated {omitted} diff lines]"]
    return "\n".join(diff)


# --- individual tools -------------------------------------------------------

def read_file(ctx: ToolContext, path: str) -> str:
    target = _resolve(ctx, path)
    if not target.is_file():
        raise ToolError(f"No such file: {path}")
    try:
        return _truncate(target.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        raise ToolError(f"Could not read {path}: {exc}")


def list_dir(ctx: ToolContext, path: str = ".") -> str:
    target = _resolve(ctx, path)
    if not target.is_dir():
        raise ToolError(f"Not a directory: {path}")
    reserved = {p for p, _ in _reserved_paths(ctx)}
    entries = []
    for child in sorted(target.iterdir()):
        if child.resolve() in reserved:
            continue  # hide reserved/protected paths from the model
        suffix = "/" if child.is_dir() else ""
        entries.append(child.name + suffix)
    return "\n".join(entries) if entries else "(empty directory)"


def write_file(ctx: ToolContext, path: str, content: str) -> str:
    target = _resolve(ctx, path)
    exists = target.is_file()
    before = target.read_text(encoding="utf-8", errors="replace") if exists else ""
    verb = "Overwrite" if exists else "Create"
    preview = _make_diff(path, before, content)
    _confirm(ctx, "write_file", f"{verb} {path} ({len(content)} chars)", preview)
    if ctx.history is not None:
        ctx.history.record(path, before, exists, "write_file")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise ToolError(f"Could not write {path}: {exc}")
    return f"{'Overwrote' if exists else 'Created'} {path} ({len(content)} chars)."


def edit_file(ctx: ToolContext, path: str, old: str, new: str) -> str:
    target = _resolve(ctx, path)
    if not target.is_file():
        raise ToolError(f"No such file: {path}")
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0:
        raise ToolError(f"`old` string not found in {path}.")
    if count > 1:
        raise ToolError(
            f"`old` string is not unique in {path} (found {count} times). "
            "Include more surrounding context."
        )
    updated = text.replace(old, new, 1)
    preview = _make_diff(path, text, updated)
    _confirm(ctx, "edit_file", f"Edit {path}: replace 1 occurrence", preview)
    if ctx.history is not None:
        ctx.history.record(path, text, True, "edit_file")
    try:
        target.write_text(updated, encoding="utf-8")
    except OSError as exc:
        raise ToolError(f"Could not write {path}: {exc}")
    return f"Edited {path} (1 replacement)."


def run_shell(ctx: ToolContext, command: str) -> str:
    _confirm(ctx, "run_shell", command)
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(ctx.workdir),
            capture_output=True,
            text=True,
            timeout=SHELL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise ToolError(f"Command timed out after {SHELL_TIMEOUT_SECONDS}s.")
    out = proc.stdout or ""
    err = proc.stderr or ""
    parts = [f"exit code: {proc.returncode}"]
    if out:
        parts.append(f"stdout:\n{out}")
    if err:
        parts.append(f"stderr:\n{err}")
    return _truncate("\n".join(parts))


def use_skill(ctx: ToolContext, name: str) -> str:
    if ctx.load_skill is None:
        raise ToolError("Skills are not available in this session.")
    return ctx.load_skill(name)


# --- dispatch ---------------------------------------------------------------

_DISPATCH: dict[str, Callable[..., str]] = {
    "read_file": read_file,
    "list_dir": list_dir,
    "write_file": write_file,
    "edit_file": edit_file,
    "run_shell": run_shell,
    "use_skill": use_skill,
}


def execute(ctx: ToolContext, name: str, args: dict) -> str:
    """Run a tool by name, returning its result or a formatted error string."""
    func = _DISPATCH.get(name)
    if func is None:
        return f"ERROR: unknown tool '{name}'."
    try:
        return func(ctx, **args)
    except ToolError as exc:
        return f"ERROR: {exc}"
    except TypeError as exc:
        return f"ERROR: bad arguments for {name}: {exc}"
