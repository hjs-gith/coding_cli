"""The agentic ReAct loop tying Dify, the protocol, tools, and skills together."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional

from . import protocol, skills as skills_mod, tools
from .dify_client import DifyClient
from .history import ChangeHistory
from .skills import Skill


# Callback used to surface intermediate tool activity to the UI.
# (event_type, detail) e.g. ("tool", "read_file: src/foo.py")
ReporterFn = Callable[[str, str], None]

# Cap on a between-steps status note shown to the user (keeps a runaway note
# from flooding the screen mid-loop).
MAX_NOTE_CHARS = 600

# Prepended to user input in plan mode so the model plans instead of acting.
PLAN_HINT = (
    "[PLAN MODE — do not edit files or run shell commands. Use read-only tools to "
    "research if needed, then reply with a short numbered implementation plan for "
    "the user to approve.]\n\n"
)

# Prepended once when leaving plan mode, to countermand the accumulated plan-mode
# instructions in the conversation so the model resumes editing.
EXIT_PLAN_HINT = (
    "[Plan mode is over — you may now edit files and run shell commands. Disregard "
    "the earlier instructions to only plan, and carry out the work.]\n\n"
)


@dataclass
class Agent:
    """Drives one conversation: user turn -> tool calls -> final answer."""

    client: DifyClient
    workdir: Path
    skills: Dict[str, Skill]
    history: ChangeHistory
    max_tool_iters: int = 12
    confirm: Optional[tools.ConfirmFn] = None
    report: Optional[ReporterFn] = None
    stream: bool = True
    deny: tuple[str, ...] = ()
    mode: str = tools.MODE_DEFAULT
    _preamble_sent: bool = False
    _exit_plan_pending: bool = False

    def set_mode(self, mode: str) -> None:
        """Switch the permission mode.

        Leaving plan mode arms a one-shot hint (consumed on the next turn) that
        tells the model plan mode is over, countermanding the accumulated
        plan-mode instructions in the Dify conversation so it resumes editing.
        """
        if self.mode == tools.MODE_PLAN and mode != tools.MODE_PLAN:
            self._exit_plan_pending = True
        self.mode = mode

    def reset(self) -> None:
        """Begin a fresh conversation (new Dify thread + re-send preamble).

        File-change history is intentionally left intact so a conversation reset
        never costs the ability to review or undo edits already made on disk.
        """
        self.client.reset()
        self._preamble_sent = False

    def undo(self) -> str:
        """Revert the most recent file change made this session."""
        return self.history.undo()

    def set_workdir(self, path: str) -> str:
        """Change the working directory mid-session.

        Re-roots the filesystem sandbox and re-binds the directory-scoped state
        (snapshot history and project-local skills). The Dify conversation and
        credentials are left untouched. Relative paths resolve against the
        current workdir; ``~`` is expanded. Returns a status message.
        """
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.workdir / candidate
        candidate = candidate.resolve()
        if not candidate.is_dir():
            return f"Not a directory: {path}"
        self.workdir = candidate
        self.history = ChangeHistory(candidate)
        self.skills = skills_mod.discover_skills(candidate)
        return f"Working directory: {candidate}"

    def session_diff(self) -> str:
        """Unified diff of every file changed this session."""
        return self.history.session_diff()

    def _tool_context(self) -> tools.ToolContext:
        return tools.ToolContext(
            workdir=self.workdir,
            confirm=self.confirm,
            load_skill=skills_mod.make_loader(self.skills),
            history=self.history,
            deny=self.deny,
            mode=self.mode,
        )

    def _preamble(self) -> str:
        return protocol.build_preamble(skills_mod.catalog(self.skills))

    def run_turn(self, user_input: str) -> str:
        """Run a single user turn to completion, returning the final answer."""
        # In plan mode, remind the model (per turn, since the mode can change
        # mid-session) to research read-only and propose a plan instead of acting.
        if self.mode == tools.MODE_PLAN:
            user_input = PLAN_HINT + user_input
        elif self._exit_plan_pending:
            # Just left plan mode: countermand the accumulated "only plan"
            # instructions so the model resumes editing. One-shot.
            user_input = EXIT_PLAN_HINT + user_input
            self._exit_plan_pending = False
        # Inject the protocol preamble in-band on the first turn of a
        # conversation, since a Dify chat app has no API-settable system prompt.
        if not self._preamble_sent:
            query = self._preamble() + "\n\n---\n\nUser: " + user_input
            self._preamble_sent = True
        else:
            query = user_input

        ctx = self._tool_context()
        for _ in range(self.max_tool_iters):
            result = self.client.chat(query, stream=self.stream)
            call = protocol.parse_tool_call(result.answer)
            if call is None:
                # No tool block -> this is the final answer.
                return result.answer.strip()

            note = protocol.extract_note(result.answer)
            if note and self.report is not None:
                self.report("note", note[:MAX_NOTE_CHARS])
            self._announce(call)
            output = tools.execute(ctx, call.name, call.args)
            self._announce_result(call.name, output)
            query = protocol.format_tool_result(call.name, output)

        return (
            "Stopped: reached the maximum of "
            f"{self.max_tool_iters} tool steps without a final answer."
        )

    def _announce(self, call: protocol.ToolCall) -> None:
        if self.report is None:
            return
        self.report("tool", _summarize_call(call))
        if call.purpose:
            self.report("tool_purpose", call.purpose)

    def _announce_result(self, name: str, output: str) -> None:
        if self.report is None:
            return
        first_line = output.strip().splitlines()[0] if output.strip() else ""
        self.report("tool_result", f"{name}: {first_line}")


def _summarize_call(call: protocol.ToolCall) -> str:
    args = call.args
    if call.name == "run_shell":
        return f"run_shell: {args.get('command', '')}"
    if call.name == "use_skill":
        return f"use_skill: {args.get('name', '')}"
    if "path" in args:
        return f"{call.name}: {args['path']}"
    return call.name


def build_agent(
    config,
    *,
    confirm: Optional[tools.ConfirmFn] = None,
    report: Optional[ReporterFn] = None,
    stream: bool = True,
    mode: str = tools.MODE_DEFAULT,
) -> Agent:
    """Construct an Agent from a loaded Config, discovering skills."""
    client = DifyClient(
        api_key=config.api_key,
        base_url=config.base_url,
        user_id=config.user_id,
    )
    discovered = skills_mod.discover_skills(config.workdir)
    return Agent(
        client=client,
        workdir=config.workdir,
        skills=discovered,
        history=ChangeHistory(config.workdir),
        max_tool_iters=config.max_tool_iters,
        confirm=confirm,
        report=report,
        stream=stream,
        deny=config.deny,
        mode=mode,
    )
