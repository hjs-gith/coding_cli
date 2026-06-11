# coding-cli

A minimal **agentic coding CLI** for your terminal, backed by a [Dify](https://dify.ai)
chat app. It can chat, read files for context, propose and apply edits, run shell
commands, and load **custom skills** you author as Markdown.

Because Dify's chat API returns text (and runs no tools on your machine), the
agentic behavior is built client-side: the model emits a structured tool call,
the CLI parses and runs it locally, then feeds the result back into the same
Dify conversation (a ReAct loop).

## Features

- **Chat REPL** — an interactive terminal assistant with conversation memory.
- **Reads your code** — pulls files and directory listings in as context.
- **Edits files** — creates new files and makes precise, single-occurrence edits.
- **Runs shell commands** — executes commands and reasons over their output.
- **Custom skills** — author reusable, Markdown-defined workflows; auto-discovered.
- **Safe by default** — every write/edit/shell action asks for confirmation, and
  all file access is sandboxed to the working directory.

## Install

This project uses [uv](https://docs.astral.sh/uv/). Create a virtual environment
and install in editable mode:

```bash
uv venv                          # create .venv
uv pip install -e ".[rich]"      # core + colored output
uv pip install -e ".[dev,rich]"  # also include test dependencies
```

Then run via the venv (`.venv/bin/coding-cli`) or activate it first:

```bash
source .venv/bin/activate
coding-cli --help
```

> Plain `pip install -e .` works too if you prefer not to use uv.

## Configure

Create a `.env` in the project (or any parent) directory:

```dotenv
DIFY_API_KEY=app-xxxxxxxxxxxxxxxx
# optional:
DIFY_BASE_URL=https://api.dify.ai/v1   # change for self-hosted Dify
DIFY_USER_ID=coding-cli                # stable per-user id sent to Dify
```

The `DIFY_API_KEY` must belong to a Dify **Chat** (or Chatflow) app.

## Prompts, context, and the Dify system prompt

It's worth understanding where each piece of "prompt" lives, because it affects
how the CLI behaves over long sessions.

**How prompts and context flow today:**

- **The tool-call protocol is injected in-band, once per conversation.** On the
  first turn, [`agent.py`](src/coding_cli/agent.py) prepends the protocol preamble
  (the `_BASE_PREAMBLE` in [`protocol.py`](src/coding_cli/protocol.py)) plus a
  **skills catalog** (skill name + description only) to your message. Later turns
  send your raw input. Full skill bodies are loaded on demand via `use_skill`.
- **Conversation history lives on Dify's side.** The CLI never re-sends history —
  [`dify_client.py`](src/coding_cli/dify_client.py) just persists `conversation_id`
  and passes it back, and Dify reconstructs the thread. Each tool result is sent as
  a new `TOOL_RESULT[...]` query within that same conversation.
- **The only context guardrail the CLI owns is output truncation.** Single file
  reads and shell outputs are capped at `MAX_OUTPUT_CHARS` (20k) in
  [`tools.py`](src/coding_cli/tools.py). There is no token counting or client-side
  history trimming — that is entirely Dify's responsibility.

**The catch:** Dify chat apps have a **conversation memory window** (a configurable
number of recent messages included per call). Because the protocol is injected only
on turn 1, a long session can roll turn 1 out of that window — at which point the
model may "forget" the tool-call format and reply in plain prose, silently
degrading the agentic loop to plain chat.

### Recommendation: should you edit the Dify system prompt?

**Recommended for longer sessions — a hybrid:** move the *static* protocol into the
Dify app's system prompt, and keep the *dynamic* skills catalog injected in-band.

| Piece | Where it belongs | Why |
| --- | --- | --- |
| Tool-call format + tool list (static) | **Dify system prompt** | A true system prompt persists on *every* turn regardless of the memory window — fixes the degradation above and frees up query tokens. |
| Skills catalog (changes as you add skill folders) | **In-band** (as-is) | Discovered locally at runtime; Dify can't know your `./skills` contents. |

The text to paste into the Dify console's system prompt is essentially the
`_BASE_PREAMBLE` string in [`protocol.py`](src/coding_cli/protocol.py).

**Trade-offs:**

- *Leave it as-is (fully in-band, the default):* self-contained and portable — the
  CLI works against any Dify chat app with no console setup. Best for **short
  sessions**. Risk: protocol can fall out of the memory window on long sessions.
- *Move the protocol to the Dify system prompt (hybrid):* robust over **long,
  multi-step sessions** and saves query tokens. Cost: it **couples the Dify app to
  this CLI** — if you change the tool list, you must edit both the console prompt
  and the code.

> If you adopt the hybrid, you'll also want a code change so the CLI stops
> double-sending the static part — e.g. a `DIFY_SYSTEM_PROMPT_HAS_PROTOCOL=true`
> flag that makes `build_preamble` emit only the skills catalog. (Not implemented
> yet — noted here as the intended follow-up.)
>
> An alternative that keeps everything in-band: re-inject the preamble every N
> turns, or detect when the model stops emitting `​```tool` blocks and re-state the
> format.

## Usage

```bash
coding-cli                       # interactive REPL
coding-cli --once "list files"   # one-shot, then exit
coding-cli --workdir ./project   # operate in a specific directory
coding-cli --no-confirm          # auto-approve writes/shell (use with care)
coding-cli --no-stream           # blocking instead of streaming responses
coding-cli --undo                # revert the last recorded file change, then exit
```

In the REPL: `/reset` (new conversation), `/cd <path>` (change the working
directory, or no argument to print it), `/diff` (review this session's file
changes), `/undo` (revert the most recent change, repeatable), `/skills` (list
skills), `/help`, `/exit` (or Ctrl-D). File writes, edits, and shell commands ask
for confirmation before running (unless `--no-confirm`). At the `[y/N/d]` prompt
for a write or edit, press `d` to preview the exact diff before deciding. All file
access is sandboxed to the working directory (and re-rooted when you `/cd`).

### Reviewing and undoing changes

Before each `write_file`/`edit_file`, coding-cli snapshots the file's prior state
under a `.coding_cli/` directory in your workdir (which ignores itself, so it never
shows up in `git status`). This powers `/diff`, `/undo`, and `--undo` without
depending on your project's git, and the journal persists so you can `--undo` a
change even in a later session.

### Example: one-shot commands

```bash
# Ask a question with no file changes
coding-cli --once "What does src/coding_cli/agent.py do?"

# Create and run a file in a scratch directory, auto-approving actions
coding-cli --once "Create hello.py that prints hi, then run it" \
  --workdir /tmp/scratch --no-confirm
```

That last command drives the full agentic loop. You'll see each step as it happens:

```
  → write_file: hello.py
  ✓ write_file: Created hello.py (12 chars).
  → run_shell: python3 hello.py
  ✓ run_shell: exit code: 0
hi
```

### Example: an interactive session

```text
$ coding-cli
coding-cli — type a request, or /help. Ctrl-D to exit.
Skills available: commit-helper

› what files are in src/coding_cli?
  → list_dir: src/coding_cli
  ✓ list_dir: __init__.py
There are 8 modules: __init__, __main__, agent, cli, config, dify_client,
protocol, and tools.

› add a module-level docstring to config.py
  → read_file: src/coding_cli/config.py
  → edit_file: src/coding_cli/config.py

  ⚠  edit_file: Edit src/coding_cli/config.py: replace 1 occurrence
  Proceed? [y/N] y
  ✓ edit_file: Edited src/coding_cli/config.py (1 replacement).
Done — added a docstring describing the configuration loader.

› /reset
Started a new conversation.

› /exit
```

### Example: using a skill

Skills are invoked by the model when relevant. Here it loads `commit-helper`:

```text
› help me commit my changes
  → use_skill: commit-helper
  ✓ use_skill: # Skill: commit-helper
  → run_shell: git status --porcelain

  ⚠  run_shell: git status --porcelain
  Proceed? [y/N] y
  ✓ run_shell: exit code: 0
You have 2 modified files. I suggest this commit message:

  feat(config): add module docstring and defensive value parsing

Shall I run the commit? ...
```

## Authoring a skill

A skill is a folder with a `SKILL.md`. Drop it in `./skills/` (project),
`~/.config/coding-cli/skills/`, or the bundled `skills/` dir — it's discovered
automatically, no code changes. Only the name + description are shown to the
model up front; the full body is loaded on demand when the model calls
`use_skill("<name>")`.

```markdown
---
name: commit-helper
description: Stage changes and write a clean git commit message.
---

# Commit Helper

Step-by-step instructions the model follows when this skill is invoked...
```

See [`skills/commit-helper/SKILL.md`](skills/commit-helper/SKILL.md) for a complete
example. You can also place machine-wide skills in `~/.config/coding-cli/skills/`.

## Develop

Run the test suite (26 unit tests covering the protocol, tools, skills, and the
agent loop with a mocked Dify client — no network required):

```bash
uv run pytest          # or: .venv/bin/pytest
```

## Architecture

| Module | Responsibility |
| --- | --- |
| `config.py` | Load `.env` / env settings |
| `dify_client.py` | Dify chat-messages wrapper (streaming + blocking) |
| `protocol.py` | Tool-call preamble + parse/format |
| `tools.py` | `read_file`, `list_dir`, `write_file`, `edit_file`, `run_shell`, `use_skill` |
| `skills.py` | Discover/parse Markdown skills, load on demand |
| `agent.py` | The ReAct loop |
| `cli.py` | REPL, argument parsing, confirmations, rendering |
