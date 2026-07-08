"""Command-line entry point: argument parsing, the REPL, and rendering."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import shell_policy, ui
from .agent import Agent, build_agent
from .config import Config, ConfigError
from .history import ChangeHistory
from .tools import MODE_AUTO, MODE_DEFAULT, MODE_PLAN, ConfirmDecision

# Friendly --mode names mapped to the internal mode constants.
_MODE_BY_NAME = {"default": MODE_DEFAULT, "auto": MODE_AUTO, "plan": MODE_PLAN}
_LABEL_BY_MODE = {MODE_AUTO: "auto", MODE_PLAN: "plan"}  # default shows no label


def _mode_label(mode: str) -> str:
    return _LABEL_BY_MODE.get(mode, "")


def _prompt_confirm(
    action: str, detail: str, preview: str, allow_cmd=None
) -> ConfirmDecision:
    """Interactive y/n/diff/message prompt. ``allow_cmd`` is ``(command, path)``
    to also offer an ``[a] always allow`` option (run_shell only)."""
    ui.warn(f"\n  ⚠  {action}: {detail}")
    opts = "[y]es / [n]o / "
    if preview:
        opts += "[d]iff / "
    if allow_cmd is not None:
        opts += "[a]lways allow / "
    prompt = f"  Proceed? {opts}or type a message: "
    while True:
        try:
            reply = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return ConfirmDecision(False)
        low = reply.lower()
        if low in ("y", "yes"):
            return ConfirmDecision(True)
        if low == "d" and preview:
            ui.diff(preview)
            continue
        if low == "a" and allow_cmd is not None:
            command, path = allow_cmd
            shell_policy.append_allowlist(path, command)
            ui.notice(
                f"  Always-allowed. Edit {path} to adjust (shorten an entry to "
                "broaden it, or delete it to revoke)."
            )
            return ConfirmDecision(True)
        if low in ("n", "no", ""):
            return ConfirmDecision(False)
        # Anything else is a message back to the model (declines + explains).
        return ConfirmDecision(False, feedback=reply)


def _make_confirm(get_workdir):
    """Build the interactive confirmation callback for mutating tools.

    Auto-approval by mode and plan-mode blocking are handled in
    ``tools._confirm``; this callback runs when a real prompt is wanted. For
    run_shell it adds a per-project allowlist and dangerous-command warnings.
    """

    def confirm(action: str, detail: str, preview: str = "") -> ConfirmDecision:
        if action == "run_shell":
            danger = shell_policy.is_dangerous(detail)
            if danger is not None:
                ui.error(f"  ⚠  DANGEROUS ({danger}) — review carefully.")
                # Dangerous commands are never auto-approved or always-allowed.
                return _prompt_confirm(action, detail, preview, allow_cmd=None)
            path = shell_policy.allowlist_path(get_workdir())
            if shell_policy.matches_allowlist(detail, shell_policy.load_allowlist(path)):
                ui.notice(f"  ↳ auto-allowed (allowlist): {detail}")
                return ConfirmDecision(True)
            return _prompt_confirm(action, detail, preview, allow_cmd=(detail, path))
        return _prompt_confirm(action, detail, preview, allow_cmd=None)

    return confirm


def _make_reporter():
    def report(event: str, detail: str) -> None:
        if event == "note":
            ui.note(detail)
        elif event == "tool":
            ui.tool(detail)
        elif event == "tool_purpose":
            ui.tool_purpose(detail)
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
    ui.notice(f"working in: {agent.workdir}  (mode: {agent.mode})")
    if agent.skills:
        names = ", ".join(sorted(agent.skills))
        ui.notice(f"Skills available: {names}")
    while True:
        try:
            line = ui.prompt(_mode_label(agent.mode)).strip()
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
            ui.assistant(answer)
            if agent.mode == MODE_PLAN:
                _handle_plan_approval(agent)
        except KeyboardInterrupt:
            ui.warn("\n(interrupted)")
            continue
        except Exception as exc:
            ui.error(f"Error: {exc}")
            continue


def _handle_plan_approval(agent: Agent) -> None:
    """After a plan-mode turn, let the user approve and start implementing."""
    while True:
        try:
            reply = input(
                "\n  Approve plan?  [a] auto-apply / [c] confirm-each / [N] no: "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            reply = ""
        if reply in ("a", "auto", "y", "yes"):
            agent.set_mode(MODE_AUTO)
            break
        if reply in ("c", "confirm"):
            agent.set_mode(MODE_DEFAULT)
            break
        if reply in ("n", "no", ""):
            ui.notice("Kept plan mode — refine the task, or /auto // /normal to edit.")
            return
        ui.warn("  Please answer a, c, or n.")
    ui.notice(f"Plan approved — implementing (mode: {agent.mode}).")
    answer = agent.run_turn("The plan is approved. Implement it now.")
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
    elif cmd in ("/plan", "/auto", "/normal"):
        agent.set_mode({
            "/plan": MODE_PLAN,
            "/auto": MODE_AUTO,
            "/normal": MODE_DEFAULT,
        }[cmd])
        ui.notice(f"Mode: {agent.mode}")
    elif cmd == "/help":
        ui.out(
            "Commands: /plan  /auto  /normal  /reset  /cd  /diff  /undo  "
            "/skills  /help  /exit"
        )
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
        "--mode",
        choices=["default", "auto", "plan"],
        default=None,
        help="Permission mode: default (confirm edits), auto (auto-apply file "
        "edits, still confirm shell), or plan (no changes; propose a plan first).",
    )
    parser.add_argument(
        "--no-confirm",
        action="store_true",
        help="Alias for --mode auto (auto-apply file edits).",
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

    if args.mode:
        mode = _MODE_BY_NAME[args.mode]
    elif args.no_confirm:
        mode = MODE_AUTO
    else:
        mode = MODE_DEFAULT

    agent = build_agent(
        config,
        report=_make_reporter(),
        stream=not args.no_stream,
        mode=mode,
    )
    # Late-bind the confirm callback so its per-project allowlist follows /cd.
    agent.confirm = _make_confirm(lambda: agent.workdir)

    if args.once:
        return _run_once(agent, args.once)
    return _repl(agent)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
