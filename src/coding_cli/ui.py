"""Presentation layer for the CLI.

Centralizes all terminal rendering so roles are visually distinct: the user and
the assistant each get a colored left "gutter" bar, while tool activity uses
compact arrow/check icons. Everything degrades to readable plain text when the
optional ``rich`` dependency is absent or ``NO_COLOR`` is set.
"""

from __future__ import annotations

import os
from typing import Optional

try:
    from rich.box import Box
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.text import Text
    from rich.theme import Theme

    _HAVE_RICH = True
except ImportError:  # pragma: no cover - rich is optional
    _HAVE_RICH = False

BAR = "▎"

_THEME_STYLES = {
    "user": "bold cyan",
    "assistant": "green",
    "tool": "cyan",
    "tool_done": "dim",
    "warn": "yellow",
    "error": "bold red",
    "notice": "dim",
}

# A box drawn with only a left edge (the gutter bar); every other edge is blank.
# Rows: top, head, head_row, mid, row, foot_row, foot, bottom (4 cols each:
# left, horizontal, divider, right).
if _HAVE_RICH:
    _BAR_BOX = Box(
        "    \n"
        f"{BAR}   \n"
        "    \n"
        f"{BAR}   \n"
        f"{BAR}   \n"
        "    \n"
        f"{BAR}   \n"
        "    \n"
    )

_console: "Optional[Console]" = None
PLAIN = True


def configure(force_plain: bool = False) -> None:
    """(Re)initialize the console. ``NO_COLOR`` or missing rich force plain mode."""
    global _console, PLAIN
    PLAIN = force_plain or (not _HAVE_RICH) or bool(os.environ.get("NO_COLOR"))
    if PLAIN:
        _console = None
    else:
        _console = Console(theme=Theme(_THEME_STYLES))


configure()


# --- pure formatting helpers (no I/O) --------------------------------------

def gutter(label: str, text: str, bar: str = BAR) -> str:
    """Plain-text gutter block: a label line then each body line, bar-prefixed."""
    lines = [f"{bar} {label}"]
    for line in (text or "").splitlines() or [""]:
        lines.append(f"{bar} {line}")
    return "\n".join(lines)


def tool_line(detail: str) -> str:
    return f"  → {detail}"


def tool_done(detail: str) -> str:
    return f"  ✓ {detail}"


# --- renderers --------------------------------------------------------------

def out(text: str, style: Optional[str] = None) -> None:
    if _console is not None and style:
        _console.print(text, style=style)
    else:
        print(text)


def notice(text: str) -> None:
    out(text, style="notice")


def warn(text: str) -> None:
    out(text, style="warn")


def error(text: str) -> None:
    out(text, style="error")


def prompt(label: str = "") -> str:
    """Read a line of user input behind a styled ``you ›`` prompt.

    ``label`` (e.g. ``"plan"``) is shown as ``you (plan) ›`` to surface the
    current permission mode.
    """
    tag = f" ({label})" if label else ""
    if _console is not None:
        return _console.input(f"\n[user]you{tag} ›[/] ")
    return input(f"\nyou{tag} › ")


def assistant(text: str) -> None:
    """Render the assistant's reply: a green gutter bar + Markdown body."""
    if _console is None:
        print()
        print(gutter("assistant", text))
        return
    _console.print()
    _console.print("[assistant]" + BAR + " assistant[/]")
    _console.print(
        Panel(
            Markdown(text or ""),
            box=_BAR_BOX,
            border_style="assistant",
            padding=(0, 1),
        )
    )


def tool(detail: str) -> None:
    out(tool_line(detail), style="tool")


def tool_result(detail: str) -> None:
    out(tool_done(detail), style="tool_done")


def diff(text: str) -> None:
    """Render a unified diff with red/green line styling (plain if no rich)."""
    if not text:
        out("  (no diff available)", style="notice")
        return
    for line in text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            out(line, style="green")
        elif line.startswith("-") and not line.startswith("---"):
            out(line, style="red")
        elif line.startswith("@@"):
            out(line, style="cyan")
        else:
            out(line, style="notice")
