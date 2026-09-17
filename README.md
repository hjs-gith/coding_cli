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
- **Sees images** — opens screenshots and mockups itself via `view_image`, or
  attach one with `/image` (needs a vision-enabled Dify app).
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
CODING_CLI_DENY=.env,.git              # paths the file tools may not touch
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
`_BASE_PREAMBLE` string in [`protocol.py`](src/coding_cli/protocol.py). A
ready-to-paste version — including autonomy/persistence guidance and notes on
what to configure on the Dify side — is provided in
[`system_prompt.md`](system_prompt.md).

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
coding-cli --mode plan           # propose a plan first; make no changes
coding-cli --mode auto           # auto-apply file edits (still confirm shell)
coding-cli --no-stream           # blocking instead of streaming responses
coding-cli --undo                # revert the last recorded file change, then exit
```

In the REPL: `/plan`, `/auto`, `/normal` (switch permission mode), `/reset` (new
conversation), `/cd <path>` (change the working directory, or no argument to
print it), `/image <path>` (attach an image to your next message), `/diff`
(review this session's file changes), `/undo` (revert the most recent change,
repeatable), `/skills` (list skills), `/help`, `/exit` (or Ctrl-D). All file
access is sandboxed to the working directory (and re-rooted when you `/cd`).

### Images (vision)

The model can open images **on its own** — if a task involves a screenshot or
mockup, it calls `view_image(path)`, and the picture is uploaded and attached to
that tool result so it genuinely sees it on the next turn:

```
> check the header spacing against designs/header.png
  → list_dir: designs
  → view_image: designs/header.png
  ✓ view_image: Attached designs/header.png...
The header padding is 8px larger than the spec.
```

You can also attach one yourself, which is useful when you want a specific image
in front of the model from the start:

```
> /image designs/header.png
  attached designs/header.png — sent with your next message.
> does this header match the spacing in the spec?
```

`/image` with no arguments lists what's queued; `/image clear` empties it.
Non-interactively, use the repeatable `--image` flag:

```bash
coding-cli --once "does this layout look right?" --image designs/header.png
```

Details:

- Supported: `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`, up to 10 MB each.
- Attachments are **sandboxed to the working directory** and respect the
  denylist, same as the file tools — `/cd` first to reach an image elsewhere.
- They apply to **exactly one message** (consumed on send). The image is
  uploaded once and rides on the first request of that turn; Dify keeps it in
  conversation history for the rest of the agentic loop.
- **Requires the Dify app to have Vision enabled** and a vision-capable model.

#### "The model says it doesn't see any image"

A vision-capable *model* is not enough — the **Dify app** must also accept file
uploads, and this is the usual cause. coding-cli reads the app's published
settings and warns you when it can tell:

```
> /image shot.png
  attached shot.png — sent with your next message.
  ! This Dify app reports image upload disabled, so the model will not see
    the image. Enable Vision / file upload in the Dify app settings...
```

Checklist when the model still reports no image:

1. In the Dify console, open the app → **Features** → enable **Vision**
   (file upload), and confirm the app's model is a vision model.
2. If the app is a **Chatflow/Workflow** app rather than a simple chat app,
   top-level files do not reach the model automatically — the LLM node must have
   vision turned on and be wired to the `sys.files` variable.
3. Re-run with `CODING_CLI_DEBUG=1` to print the upload response and the exact
   `files` payload sent to Dify:

   ```bash
   CODING_CLI_DEBUG=1 coding-cli
   ```

   A successful upload prints `[dify:upload] {'id': ...}` and the attached
   request prints `[dify:chat.files] [...]`. If both appear and the model still
   sees nothing, the file is reaching Dify and the app config is the remaining
   suspect.

### Confirming tool calls

Each tool call shows a one-line `↳ purpose` explaining why the agent is making it
(the model supplies it), so complex shell commands are easier to judge at a
glance. At the confirm prompt you can answer `y` / `n`, press `d` to preview the
exact diff (for writes/edits), or **type a message** instead — that declines the
call *and* sends your words back to the model (e.g. "use uv instead, not pip"),
so it can adjust rather than just stop.

**Always-allow a shell command.** For `run_shell`, the prompt also offers
`[a] always allow`. Choosing it records the command in a per-project allowlist at
`<workdir>/.coding_cli/allowed_commands.txt` (gitignored, and off-limits to the
agent), and matching commands then run without prompting. Matching is
prefix-based: an entry `git status` also covers `git status --porcelain`, but any
command containing `&&`, `;`, `|`, or redirection always re-prompts — so a
dangerous command can't be tacked onto an allowed prefix. The file is plain text
(one command/prefix per line, `#` comments allowed) and is **meant to be
hand-edited**: `[a]` saves the full command, so shorten an entry to broaden it, or
delete a line to revoke. Edits take effect on the next command.

**Dangerous-command warning.** Commands matching a small heuristic list
(`rm -rf`, `sudo`, `mkfs`, `dd of=/dev/…`, `git push --force`, `curl … | sh`,
`shutdown`, …) show a red `DANGEROUS` warning, are never auto-approved from the
allowlist, and are not offered `[a]` — you must confirm them explicitly each time.
This is a best-effort safety net, not a security boundary.

### Permission modes

- **default** — confirm every file edit and shell command before it runs.
- **auto** (`--mode auto`, or the `--no-confirm` alias / `/auto`) — apply
  `write_file`/`edit_file` without asking; `run_shell` still prompts.
- **plan** (`--mode plan` / `/plan`) — make **no** changes; the agent researches
  read-only and replies with a numbered plan. After it does, you're asked
  `Approve plan? [a] auto-apply / [c] confirm-each / [N] no`; choosing `a` or `c`
  switches to that mode and tells the agent to implement. The current mode shows
  in the prompt, e.g. `you (plan) ›`.

#### Getting the agent to finish an approved plan

The agent decides it's "done" by returning a reply with no further tool call, and
one turn runs at most `CODING_CLI_MAX_TOOL_ITERS` tool steps (default 12). So on
longer tasks it can stop early or run out of steps. There is no built-in
checklist that forces every plan step to completion — these levers make it far
more reliable:

- **Raise the step budget.** Set `CODING_CLI_MAX_TOOL_ITERS` (e.g. `40`) in your
  `.env` so a single implementation turn has room to finish a multi-file task.
- **Add a persistence instruction to the Dify system prompt** (see the section
  above on moving the preamble into Dify). For example:

  > Work autonomously until the task is fully complete. Do not stop after a
  > single step — keep calling tools until every step of the approved plan is
  > done. Before finishing, run the project's tests or build and fix any
  > failures, then give a short summary of what changed.

- **Restate the plan when you approve it.** Instead of relying on the bare
  "implement it now", tell the agent: *"Implement the plan step by step. After
  each step, state which step you finished and what remains. Don't stop until all
  steps are done and the tests pass."*
- **If it stops early or hits the step cap, just type `continue`** — the same
  Dify conversation resumes where it left off.

### Output styling

With the `rich` extra installed, the three roles are visually distinct: your
prompt is a cyan `you ›`, tool steps show compact `→`/`✓` lines, and the
assistant's reply renders as Markdown (syntax-highlighted code, formatted lists)
behind a green left gutter bar. Set `NO_COLOR=1`, or install without the `rich`
extra, to get plain text with simple `▎` gutters and no escape codes.

**Streaming.** By default the assistant's text streams **live** as it arrives —
on a capable terminal (macOS/Linux, or **Windows Terminal**) it reflows as
formatted Markdown in the green panel while the model types. The raw ` ```tool `
call is never shown; only the `→`/`✓` tool lines and any short status prose
appear. `--no-stream` switches to a one-shot buffered render instead (the more
robust transport for very long single replies).

The live Markdown panel needs a terminal that supports in-place cursor updates.
On the **legacy Windows console** (old `conhost`), non-interactive output, or with
`NO_COLOR`/without `rich`, streaming automatically falls back to **append-only
plain text** (each chunk printed once — no duplication). Override with
`CODING_CLI_STREAM`: `auto` (default, detect), `live` (force the Markdown panel),
or `plain` (force append-only plain streaming).

### Reviewing and undoing changes

Before each `write_file`/`edit_file`, coding-cli snapshots the file's prior state
under a `.coding_cli/` directory in your workdir (which ignores itself, so it never
shows up in `git status`). This powers `/diff`, `/undo`, and `--undo` without
depending on your project's git, and the journal persists so you can `--undo` a
change even in a later session.

### Protected paths

The agent's file tools (`read_file`, `search_text`, `view_image`, `list_dir`, `write_file`, `edit_file`) refuse
to touch a denylist of workdir-relative paths, and those paths are hidden from
`list_dir`. The `.coding_cli/` snapshot directory is **always** reserved (so the
model can't corrupt your undo history); on top of that, `CODING_CLI_DENY`
configures additional protected paths and defaults to `.env,.git`. Set it to a
comma-separated list to change them, or to an empty value to keep only the
always-reserved `.coding_cli`. Deleting `.coding_cli/` yourself is safe — it
self-heals on the next change and only discards undo/diff history, never your files.

Note: this guards the **file tools** only. `run_shell` runs arbitrary commands and
is not path-sandboxed — it's gated by the per-command confirmation prompt instead,
so review shell commands (e.g. anything that reads `.env`) before approving them.

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

### Skills with scripts

A skill folder can bundle helper scripts (e.g. `run.py`) alongside its
`SKILL.md`. When the model calls `use_skill("<name>")`, the loader appends the
skill's **absolute directory** and a listing of its **bundled file paths**, so
the model can run a script by full path with `run_shell` (`python
.../skills/<name>/run.py`) no matter where the skill lives. Reference the script
in the `SKILL.md` body so the model knows to use it.

Two caveats to be aware of:

- **Script dependencies are yours to install.** A skill script runs via
  `run_shell` in whatever environment the shell resolves — coding-cli does not
  inspect or install its imports. If `run.py` needs a third-party package, make
  sure it's installed in that environment (e.g. `pip install …`), or have the
  skill install it as a first step.
- **Bundled skills vs. wheel installs.** Skills you add under `./skills/`
  (project) or `~/.config/coding-cli/skills/` are found on the live filesystem at
  runtime and always work. The repo's **built-in** `skills/` folder, however, is
  located relative to the source tree (`skills.py` looks two levels up from the
  package), so it only resolves for an **editable** install (`pip install -e`,
  the documented setup). A non-editable/wheel install may not ship those bundled
  skills — the `../../skills/**/*` `package-data` entry in `pyproject.toml`
  reaches outside the package and setuptools does not reliably honor it. If you
  package coding-cli as a wheel and want the built-in skills, move `skills/` under
  the package (or use a proper data-inclusion mechanism) and adjust
  `skill_search_dirs` accordingly.

## Develop

Run the test suite (157 unit tests covering the protocol, tools, skills, and the
agent loop with a mocked Dify client — no network required):

```bash
uv run pytest          # or: .venv/bin/pytest
```

## Architecture

| Module | Responsibility |
| --- | --- |
| `config.py` | Load `.env` / env settings |
| `dify_client.py` | Dify chat-messages wrapper (streaming + blocking) + image upload |
| `protocol.py` | Tool-call preamble + parse/format |
| `tools.py` | `read_file` (whole or line-range), `search_text` (regex grep), `view_image`, `list_dir`, `write_file`, `edit_file`, `run_shell`, `use_skill` |
| `skills.py` | Discover/parse Markdown skills, load on demand |
| `agent.py` | The ReAct loop |
| `cli.py` | REPL, argument parsing, confirmations, rendering |
