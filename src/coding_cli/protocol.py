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

_TOOL_BLOCK_RE = re.compile(r"```tool\s*\n(.*?)```", re.DOTALL)

_BASE_PREAMBLE = """\
You are a coding assistant running inside a terminal CLI on the user's machine.
You can act on the local filesystem and shell ONLY through tool calls.

When you need to take an action, reply with EXACTLY ONE fenced block and nothing
else, in this exact form:

```tool
{"tool": "read_file", "args": {"path": "src/foo.py"}}
```

Rules:
- Emit at most one tool call per message. After you see its TOOL_RESULT, decide
  the next step.
- Use double-quoted JSON. Do not add commentary around the tool block.
- When the task is complete, reply normally in plain text (no tool block); that
  text is shown to the user as the final answer.

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


def parse_tool_call(text: str) -> Optional[ToolCall]:
    """Extract a single tool call from a model reply.

    Returns ``None`` when no ```tool block is present (the reply is a final
    answer) or when the block is malformed/unknown — callers treat ``None`` as
    "this is plain text to show the user".
    """
    match = _TOOL_BLOCK_RE.search(text or "")
    if not match:
        return None
    try:
        payload = json.loads(match.group(1).strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    name = payload.get("tool")
    args = payload.get("args", {})
    if not isinstance(name, str) or name not in KNOWN_TOOLS:
        return None
    if not isinstance(args, dict):
        return None
    return ToolCall(name=name, args=args)


def strip_tool_block(text: str) -> str:
    """Remove the tool block from a reply, leaving any surrounding prose."""
    return _TOOL_BLOCK_RE.sub("", text or "").strip()


def format_tool_result(name: str, result: str) -> str:
    """Wrap a tool's output as the next query sent back to the model."""
    return f"TOOL_RESULT[{name}]:\n{result}"
