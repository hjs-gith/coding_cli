"""The text protocol that turns a plain Dify chat app into an agentic loop.

Dify's chat-messages API only returns text and runs no tools locally, so we
instruct the model to emit tool calls as a fenced ```tool JSON block. This
module builds that instruction preamble and parses the model's replies.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterable, Optional

# Tools the model may call. ``use_skill`` is registered dynamically but always
# advertised so the skills catalog is meaningful.
KNOWN_TOOLS = {
    "read_file",
    "list_dir",
    "write_file",
    "edit_file",
    "run_shell",
    "use_skill",
}

_TOOL_BLOCK_RE = re.compile(r"```tool\s*(.*?)```", re.DOTALL)

_BASE_PREAMBLE = """\
You are a coding assistant running inside a terminal CLI on the user's machine.
You can act on the local filesystem and shell ONLY through tool calls.

When you need to take an action, reply with EXACTLY ONE fenced block and nothing
else, in this exact form:

```tool
{"tool": "run_shell", "args": {"command": "pytest -q"}, "purpose": "run the tests"}
```

Rules:
- Emit at most one tool call per message. After you see its TOOL_RESULT,
  immediately continue with the next tool call and keep going until the whole
  task is done. Do not stop to narrate your plan, summarize progress, or ask for
  permission between steps.
- The CLI already asks the user to confirm risky actions (writes, edits, shell
  commands), so never ask "should I proceed?" in prose — just make the tool call
  and the user is prompted if needed.
- Include a short one-line "purpose" in plain language saying why you're making
  this call (especially for run_shell, so the user can approve at a glance).
- Use double-quoted JSON. Do not add commentary around the tool block. If you
  cannot emit the fence, a bare JSON object on its own is still accepted.
- Reply in plain text (no tool block) ONLY when the task is fully complete, or
  when you genuinely cannot continue without a decision from the user. Plain text
  ends the turn and is shown to the user as the final answer, so do not use it to
  think out loud mid-task.

Available tools:
- read_file(path): return the contents of a file.
- list_dir(path): list entries in a directory.
- write_file(path, content): create or overwrite a file.
- edit_file(path, old, new): replace an exact unique substring in a file.
- run_shell(command): run a shell command and return its output.
- use_skill(name): load the full instructions for a named skill, then follow them.
"""


@dataclass
class ToolCall:
    """A parsed tool invocation extracted from a model reply."""

    name: str
    args: dict
    purpose: str = ""  # optional one-line explanation of why the call is made


def build_preamble(skill_catalog: Optional[Iterable[tuple[str, str]]] = None) -> str:
    """Build the protocol preamble, optionally appending a skills catalog.

    ``skill_catalog`` is an iterable of ``(name, description)`` pairs. Only the
    name and description are included (progressive disclosure) — the full body
    is fetched on demand via ``use_skill``.
    """
    preamble = _BASE_PREAMBLE
    catalog = list(skill_catalog or [])
    if catalog:
        lines = "\n".join(f"- {name}: {desc}" for name, desc in catalog)
        preamble += (
            "\nAvailable skills (invoke with use_skill(name) to load full "
            "instructions):\n" + lines + "\n"
        )
    else:
        preamble += "\nNo custom skills are currently available.\n"
    return preamble


def _payload_to_call(payload: object) -> Optional[ToolCall]:
    """Validate a decoded JSON value as a known tool call, else ``None``."""
    if not isinstance(payload, dict):
        return None
    name = payload.get("tool")
    args = payload.get("args", {})
    if not isinstance(name, str) or name not in KNOWN_TOOLS:
        return None
    if not isinstance(args, dict):
        return None
    purpose = payload.get("purpose", "")
    if not isinstance(purpose, str):
        purpose = ""
    return ToolCall(name=name, args=args, purpose=purpose)


def _iter_json_objects(text: str) -> Iterable[object]:
    """Yield every top-level JSON value in ``text``, in order.

    Uses ``raw_decode`` so nested braces and braces inside string values (e.g.
    ``write_file`` content) are handled correctly — a regex or naive
    brace-counter cannot do this reliably.
    """
    decoder = json.JSONDecoder()
    idx = 0
    while True:
        start = text.find("{", idx)
        if start == -1:
            return
        try:
            obj, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            idx = start + 1
            continue
        idx = end
        yield obj


def parse_tool_call(text: str) -> Optional[ToolCall]:
    """Extract a single tool call from a model reply.

    The model is asked to emit a ```tool fenced block, but real output often
    drops the fence, mislabels it (``json`` or a bare fence), or puts the JSON
    on the same line. We therefore first honor an explicit ```tool block, then
    fall back to the first JSON object anywhere in the reply that validates as a
    known tool call.

    Returns ``None`` when no valid tool call is present (the reply is a final
    answer) or when every candidate is malformed/unknown — callers treat
    ``None`` as "this is plain text to show the user".
    """
    text = text or ""
    match = _TOOL_BLOCK_RE.search(text)
    if match:
        try:
            call = _payload_to_call(json.loads(match.group(1).strip()))
        except json.JSONDecodeError:
            call = None
        if call is not None:
            return call
    for payload in _iter_json_objects(text):
        call = _payload_to_call(payload)
        if call is not None:
            return call
    return None


def strip_tool_block(text: str) -> str:
    """Remove the tool block from a reply, leaving any surrounding prose."""
    return _TOOL_BLOCK_RE.sub("", text or "").strip()


def format_tool_result(name: str, result: str) -> str:
    """Wrap a tool's output as the next query sent back to the model."""
    return f"TOOL_RESULT[{name}]:\n{result}"
