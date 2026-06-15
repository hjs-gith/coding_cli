"""Command-line entry point: argument parsing, the REPL, and rendering."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import ui
from .agent import Agent, build_agent
from .config import Config, ConfigError
from .history import ChangeHistory


def _make_confirm(auto_yes: bool):
    """Build the confirmation callback for mutating tools."""

    def confirm(action: str, detail: str, preview: str = "") -> bool:
        if auto_yes:
            ui.notice(f"  [auto-approved] {action}: {detail}")
            return True
        ui.warn(f"\n  ⚠  {action}: {detail}")
        prompt = "  Proceed? [y/N/d] " if preview else "  Proceed? [y/N] "
        while True:
            try:
                reply = input(prompt).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                return False
            if reply == "d" and preview:
                ui.diff(preview)
                continue
            return reply in ("y", "yes")

    return confirm


def _make_reporter():
    def report(event: str, detail: str) -> None:
        if event == "tool":
            ui.tool(detail)
        elif event == "tool_result":
            ui.tool_result(detail)

    return report


def _run_once(agent: Agent, prompt: str) -> int:
    try:
        answer = agent.run_turn(prompt)
    except Exception as exc:  # surface backend/tool errors cleanly
        ui.error(f"Error: {exc}")
        return 1
    ui.assistant(answer)
    return 0


def _repl(agent: Agent) -> int:
    ui.out("coding-cli — type a request, or /help. Ctrl-D to exit.", style="bold")
    ui.notice(f"working in: {agent.workdir}")
    if agent.skills:
        names = ", ".join(sorted(agent.skills))
        ui.notice(f"Skills available: {names}")
    while True:
        try:
            line = ui.prompt().strip()
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
            ui.warn("\n(interrupted)")
            continue
        except Exception as exc:
            ui.error(f"Error: {exc}")
            continue
        ui.assistant(answer)


def _handle_command(agent: Agent, line: str) -> bool:
    """Handle a /slash command. Returns True if the REPL should exit."""
    cmd = line.split()[0].lower()
    if cmd in ("/exit", "/quit"):
        return True
    if cmd == "/reset":
        agent.reset()
        ui.notice("Started a new conversation.")
    elif cmd == "/cd":
        parts = line.split(maxsplit=1)
        if len(parts) == 1:
            ui.notice(str(agent.workdir))
        else:
            ui.notice(agent.set_workdir(parts[1].strip()))
    elif cmd == "/skills":
        if agent.skills:
            for name, skill in sorted(agent.skills.items()):
                ui.out(f"  {name} — {skill.description}")
        else:
            ui.notice("  (no skills discovered)")
    elif cmd == "/diff":
        ui.diff(agent.session_diff())
    elif cmd == "/undo":
        ui.notice(agent.undo())
    elif cmd == "/help":
        ui.out("Commands: /reset  /cd  /diff  /undo  /skills  /help  /exit")
    else:
        ui.warn(f"Unknown command: {cmd}. Try /help.")
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
        ui.notice(ChangeHistory(workdir).undo())
        return 0

    try:
        config = Config.load(workdir=workdir)
    except ConfigError as exc:
        ui.error(f"Configuration error: {exc}")
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
