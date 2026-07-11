"""Local tools the agent can invoke: file IO and shell execution.

Each tool returns a string (its result or an error message). Mutating tools
(``write_file``, ``edit_file``, ``run_shell``) are gated through a confirmation
callback so the CLI can ask the user before anything touches disk.
"""

from __future__ import annotations

import difflib
import fnmatch
import os
import re
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

# search_text limits: cap matches, skip huge files, and prune noise directories.
SEARCH_MAX_RESULTS = 100
SEARCH_MAX_FILE_BYTES = 1_000_000
SEARCH_MAX_LINE_CHARS = 300
_SEARCH_SKIP_DIRS = {".git", "node_modules", "__pycache__"}

# Permission modes governing whether mutating tools run, ask, or are blocked.
MODE_DEFAULT = "default"      # confirm every mutating tool
MODE_AUTO = "auto-edit"       # auto-approve file edits; still confirm run_shell
MODE_PLAN = "plan"            # block all mutations; the model plans instead

@dataclass
class ConfirmDecision:
    """A confirm callback's answer: approve/deny plus optional user feedback."""

    approved: bool
    feedback: str = ""


# A confirmation callback: (action, detail, preview) -> bool | ConfirmDecision.
# ``preview`` is an optional unified diff the UI can show on demand. A falsey
# answer aborts; a ConfirmDecision may also carry a message back to the model.
ConfirmFn = Callable[[str, str, str], "bool | ConfirmDecision"]

MUTATING_TOOLS = {"write_file", "edit_file", "run_shell"}
EDIT_TOOLS = {"write_file", "edit_file"}


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
    # Permission mode governing mutating tools (see MODE_* constants).
    mode: str = MODE_DEFAULT


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
    if ctx.mode == MODE_PLAN:
        raise ToolError(
            "Plan mode is active: file changes and shell commands are disabled. "
            "Do not call this tool — reply with a concise, numbered plan for the "
            "user to approve."
        )
    if ctx.mode == MODE_AUTO and action in EDIT_TOOLS:
        return  # auto-approve file edits
    if ctx.confirm is None:
        return
    decision = ctx.confirm(action, detail, preview)
    if isinstance(decision, ConfirmDecision):
        approved, feedback = decision.approved, decision.feedback
    else:
        approved, feedback = bool(decision), ""
    if not approved:
        message = f"User declined: {action}."
        if feedback:
            message += f" Feedback: {feedback}"
        raise ToolError(message)


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

def read_file(
    ctx: ToolContext,
    path: str,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
) -> str:
    """Return a file's contents, optionally just a line range.

    With no ``offset``/``limit`` the whole file is returned (truncated at
    ``MAX_OUTPUT_CHARS``). Pass ``offset`` (1-based line number) and/or ``limit``
    (line count) to read only a window of a large file and page through it. Ranged
    output keeps the raw lines (no line-number prefixes, so it stays safe to feed
    straight into ``edit_file``) and adds a ``[lines X-Y of N]`` footer.
    """
    target = _resolve(ctx, path)
    if not target.is_file():
        raise ToolError(f"No such file: {path}")
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ToolError(f"Could not read {path}: {exc}")

    if offset is None and limit is None:
        out = _truncate(text)
        if len(text) > MAX_OUTPUT_CHARS:
            out += (
                "\n[truncated; call read_file with offset (1-based line) and "
                "limit to read specific line ranges]"
            )
        return out

    start = 1 if offset is None else int(offset)
    if start < 1:
        raise ToolError("offset must be a 1-based line number >= 1.")
    if limit is not None and int(limit) < 1:
        raise ToolError("limit must be >= 1.")
    lines = text.splitlines()
    total = len(lines)
    if start > total:
        return f"[file has {total} lines; offset {start} is past end]"
    count = total - (start - 1) if limit is None else int(limit)
    chunk = lines[start - 1 : start - 1 + count]
    end = start + len(chunk) - 1
    return _truncate("\n".join(chunk)) + f"\n[lines {start}-{end} of {total}]"


def search_text(
    ctx: ToolContext,
    pattern: str,
    path: str = ".",
    glob: Optional[str] = None,
    ignore_case: bool = False,
) -> str:
    """Regex-search files under ``path`` and return matching ``path:line: text``.

    Read-only. ``pattern`` is a Python regex; ``path`` may be a file or directory
    (searched recursively). ``glob`` filters by workdir-relative path (e.g.
    ``*.py``); ``ignore_case`` makes the match case-insensitive. Reserved/denied
    paths, ``.git``/``node_modules``/``__pycache__``, oversized files, and
    non-UTF-8 (binary) files are skipped.
    """
    try:
        regex = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as exc:
        raise ToolError(f"Invalid regex {pattern!r}: {exc}")
    root = _resolve(ctx, path)
    if not root.exists():
        raise ToolError(f"No such file or directory: {path}")
    workdir = ctx.workdir.resolve()
    reserved = {p for p, _ in _reserved_paths(ctx)}

    files: "list[Path]" = []
    if root.is_file():
        files.append(root)
    else:
        for dirpath, dirnames, filenames in os.walk(root):
            here = Path(dirpath)
            # Prune skip/reserved directories in place so os.walk won't descend.
            dirnames[:] = [
                d
                for d in dirnames
                if d not in _SEARCH_SKIP_DIRS and (here / d).resolve() not in reserved
            ]
            for name in sorted(filenames):
                files.append(here / name)

    matches: "list[str]" = []
    truncated = False
    for file in files:
        resolved = file.resolve()
        if resolved in reserved or any(r in resolved.parents for r in reserved):
            continue
        try:
            rel = resolved.relative_to(workdir).as_posix()
        except ValueError:
            rel = file.as_posix()
        if glob is not None and not fnmatch.fnmatch(rel, glob):
            continue
        try:
            if resolved.stat().st_size > SEARCH_MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        try:
            content = resolved.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable; skip
        for lineno, line in enumerate(content.splitlines(), start=1):
            if regex.search(line):
                snippet = line.strip()[:SEARCH_MAX_LINE_CHARS]
                matches.append(f"{rel}:{lineno}: {snippet}")
                if len(matches) >= SEARCH_MAX_RESULTS:
                    truncated = True
                    break
        if truncated:
            break

    if not matches:
        return f"No matches for {pattern!r}."
    out = "\n".join(matches)
    if truncated:
        out += "\n... [more matches; refine the pattern or narrow path]"
    return _truncate(out)


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
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise ToolError(f"Cannot edit {path}: not a UTF-8 text file.")
    count = text.count(old)
    if count == 0:
        raise ToolError(
            f"`old` string not found in {path}. The file may have changed since "
            "you last saw it — call read_file to get its current contents, then "
            "retry edit_file with an exact snippet (or use write_file to rewrite "
            "it). Do not ask the user to edit the file manually."
        )
    if count > 1:
        raise ToolError(
            f"`old` string is not unique in {path} (found {count} times). "
            "Include more surrounding context to identify one location "
            "(read_file to see it)."
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
            encoding="utf-8",
            errors="replace",
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
    "search_text": search_text,
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
