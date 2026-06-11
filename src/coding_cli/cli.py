"""Command-line entry point: argument parsing, the REPL, and rendering."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .agent import Agent, build_agent
from .config import Config, ConfigError
from .history import ChangeHistory

try:
    from rich.console import Console

    _console = Console()
except ImportError:  # pragma: no cover - rich is optional
    _console = None


def _out(text: str, style: str | None = None) -> None:
    if _console is not None and style:
        _console.print(text, style=style)
    else:
        print(text)


def _print_diff(diff: str) -> None:
    """Render a unified diff with red/green line styling (plain if no rich)."""
    if not diff:
        _out("  (no diff available)", style="dim")
        return
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            _out(line, style="green")
        elif line.startswith("-") and not line.startswith("---"):
            _out(line, style="red")
        elif line.startswith("@@"):
            _out(line, style="cyan")
        else:
            _out(line, style="dim")


def _make_confirm(auto_yes: bool):
    """Build the confirmation callback for mutating tools."""

    def confirm(action: str, detail: str, preview: str = "") -> bool:
        if auto_yes:
            _out(f"  [auto-approved] {action}: {detail}", style="dim")
            return True
        _out(f"\n  ⚠  {action}: {detail}", style="yellow")
        prompt = "  Proceed? [y/N/d] " if preview else "  Proceed? [y/N] "
        while True:
            try:
                reply = input(prompt).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                return False
            if reply == "d" and preview:
                _print_diff(preview)
                continue
            return reply in ("y", "yes")

    return confirm


def _make_reporter():
    def report(event: str, detail: str) -> None:
        if event == "tool":
            _out(f"  → {detail}", style="cyan")
        elif event == "tool_result":
            _out(f"  ✓ {detail}", style="dim")

    return report


def _run_once(agent: Agent, prompt: str) -> int:
    try:
        answer = agent.run_turn(prompt)
    except Exception as exc:  # surface backend/tool errors cleanly
        _out(f"Error: {exc}", style="red")
        return 1
    _out(answer)
    return 0


def _repl(agent: Agent) -> int:
    _out("coding-cli — type a request, or /help. Ctrl-D to exit.", style="bold")
    _out(f"working in: {agent.workdir}", style="dim")
    if agent.skills:
        names = ", ".join(sorted(agent.skills))
        _out(f"Skills available: {names}", style="dim")
    while True:
        try:
            line = input("\n› ").strip()
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print()
            continue
        if not line:
            continue
        if line.startswith("/"):
            if _handle_command(agent, line):
                return 0
            continue
        try:
            answer = agent.run_turn(line)
        except KeyboardInterrupt:
            _out("\n(interrupted)", style="yellow")
            continue
        except Exception as exc:
            _out(f"Error: {exc}", style="red")
            continue
        _out("")
        _out(answer)


def _handle_command(agent: Agent, line: str) -> bool:
    """Handle a /slash command. Returns True if the REPL should exit."""
    cmd = line.split()[0].lower()
    if cmd in ("/exit", "/quit"):
        return True
    if cmd == "/reset":
        agent.reset()
        _out("Started a new conversation.", style="dim")
    elif cmd == "/cd":
        parts = line.split(maxsplit=1)
        if len(parts) == 1:
            _out(str(agent.workdir), style="dim")
        else:
            _out(agent.set_workdir(parts[1].strip()), style="dim")
    elif cmd == "/skills":
        if agent.skills:
            for name, skill in sorted(agent.skills.items()):
                _out(f"  {name} — {skill.description}")
        else:
            _out("  (no skills discovered)")
    elif cmd == "/diff":
        _print_diff(agent.session_diff())
    elif cmd == "/undo":
        _out(agent.undo(), style="dim")
    elif cmd == "/help":
        _out("Commands: /reset  /cd  /diff  /undo  /skills  /help  /exit")
    else:
        _out(f"Unknown command: {cmd}. Try /help.", style="yellow")
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="coding-cli",
        description="A minimal agentic coding CLI backed by a Dify chat app.",
    )
    parser.add_argument(
        "--once",
        metavar="PROMPT",
        help="Run a single prompt and exit (non-interactive).",
    )
    parser.add_argument(
        "--workdir",
        default=None,
        help="Working directory the agent operates in (default: current dir).",
    )
    parser.add_argument(
        "--no-confirm",
        action="store_true",
        help="Auto-approve file writes and shell commands (use with care).",
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Use blocking responses instead of streaming.",
    )
    parser.add_argument(
        "--undo",
        action="store_true",
        help="Undo the most recent recorded file change and exit.",
    )
    args = parser.parse_args(argv)

    workdir = Path(args.workdir).resolve() if args.workdir else Path.cwd()

    # --undo reverts a previously recorded change without contacting Dify, so
    # handle it before loading config (it needs no API key).
    if args.undo:
        _out(ChangeHistory(workdir).undo(), style="dim")
        return 0

    try:
        config = Config.load(workdir=workdir)
    except ConfigError as exc:
        _out(f"Configuration error: {exc}", style="red")
        return 2

    agent = build_agent(
        config,
        confirm=_make_confirm(args.no_confirm),
        report=_make_reporter(),
        stream=not args.no_stream,
    )

    if args.once:
        return _run_once(agent, args.once)
    return _repl(agent)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
