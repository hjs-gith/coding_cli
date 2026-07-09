from coding_cli.agent import Agent
from coding_cli.dify_client import ChatResult
from coding_cli.history import ChangeHistory


class FakeClient:
    """A scripted DifyClient stand-in.

    ``responses`` is a list of answer strings returned in order. Each query is
    recorded so tests can assert on what the agent sent back.
    """

    def __init__(self, responses):
        self._responses = list(responses)
        self.queries = []
        self.conversation_id = ""

    def chat(self, query, stream=True, on_delta=None):
        self.queries.append(query)
        answer = self._responses.pop(0)
        if on_delta is not None and stream:
            # Simulate streaming by delivering the whole answer as one delta.
            on_delta(answer)
        return ChatResult(answer=answer, conversation_id="conv-1", message_id="m")

    def reset(self):
        self.conversation_id = ""


class FakeSink:
    """Records what the agent would render live."""

    def __init__(self):
        self.deltas = []
        self.answers = []
        self.began = 0
        self.ended = 0

    def begin(self):
        self.began += 1

    def delta(self, text):
        self.deltas.append(text)

    def end(self):
        self.ended += 1

    def answer(self, text):
        self.answers.append(text)

    @property
    def streamed(self):
        return "".join(self.deltas)


def make_agent(tmp_path, responses, **kw):
    return Agent(
        client=FakeClient(responses),
        workdir=tmp_path,
        skills=kw.pop("skills", {}),
        history=kw.pop("history", ChangeHistory(tmp_path)),
        confirm=kw.pop("confirm", lambda a, d, preview="": True),
        **kw,
    )


def test_plain_answer_no_tools(tmp_path):
    agent = make_agent(tmp_path, ["The answer is 42."])
    assert agent.run_turn("hi") == "The answer is 42."


def test_tool_call_then_final(tmp_path):
    (tmp_path / "a.txt").write_text("file contents here")
    responses = [
        '```tool\n{"tool": "read_file", "args": {"path": "a.txt"}}\n```',
        "It says: file contents here",
    ]
    agent = make_agent(tmp_path, responses)
    answer = agent.run_turn("read a.txt")
    assert answer == "It says: file contents here"
    # The second query should carry the tool result back to the model.
    assert "TOOL_RESULT[read_file]" in agent.client.queries[1]
    assert "file contents here" in agent.client.queries[1]


def test_preamble_injected_on_first_turn_only(tmp_path):
    agent = make_agent(tmp_path, ["one", "two"])
    agent.run_turn("first")
    agent.run_turn("second")
    assert "You are a coding assistant" in agent.client.queries[0]
    assert "You are a coding assistant" not in agent.client.queries[1]


def test_max_iters_guard(tmp_path):
    # Always returns a tool call -> never terminates on its own.
    loop = '```tool\n{"tool": "list_dir", "args": {"path": "."}}\n```'
    agent = make_agent(tmp_path, [loop] * 50, max_tool_iters=3)
    answer = agent.run_turn("loop forever")
    assert "maximum of 3 tool steps" in answer


def test_set_workdir_changes_where_writes_land(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    agent = make_agent(old, [
        '```tool\n{"tool": "write_file", "args": {"path": "f.txt", "content": "hi"}}\n```',
        "done",
    ])
    msg = agent.set_workdir(str(new))
    assert agent.workdir == new.resolve()
    assert str(new.resolve()) in msg
    agent.run_turn("make a file")
    assert (new / "f.txt").read_text() == "hi"
    assert not (old / "f.txt").exists()


def test_set_workdir_rediscovers_skills(tmp_path):
    proj = tmp_path / "proj"
    skill_dir = proj / "skills" / "greeter"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: greeter\ndescription: say hi\n---\nWave at the user.\n"
    )
    agent = make_agent(tmp_path, ["unused"])
    assert "greeter" not in agent.skills
    agent.set_workdir(str(proj))
    assert "greeter" in agent.skills


def test_set_workdir_invalid_path_unchanged(tmp_path):
    agent = make_agent(tmp_path, ["unused"])
    before = agent.workdir
    msg = agent.set_workdir(str(tmp_path / "does-not-exist"))
    assert msg.startswith("Not a directory:")
    assert agent.workdir == before


def test_set_workdir_relative_resolves_against_current(tmp_path):
    (tmp_path / "sub").mkdir()
    agent = make_agent(tmp_path, ["unused"])
    agent.set_workdir("sub")
    assert agent.workdir == (tmp_path / "sub").resolve()


def test_sandbox_holds_after_cd(tmp_path):
    # A secret in the parent dir; after cd into the child, it is out of sandbox.
    (tmp_path / "secret.txt").write_text("TOP SECRET")
    child = tmp_path / "child"
    child.mkdir()
    agent = make_agent(tmp_path, [
        '```tool\n{"tool": "read_file", "args": {"path": "../secret.txt"}}\n```',
        '```tool\n{"tool": "read_file", "args": {"path": "SECRET_ABS"}}\n```'.replace(
            "SECRET_ABS", str(tmp_path / "secret.txt")
        ),
        "final",
    ])
    agent.set_workdir(str(child))
    agent.run_turn("try to read the secret")
    # Both the relative escape and the absolute out-of-sandbox path are blocked,
    # and the secret never leaks back into the queries sent to the model.
    relative_result = agent.client.queries[1]
    absolute_result = agent.client.queries[2]
    assert "outside the working directory" in relative_result
    assert "outside the working directory" in absolute_result
    assert "TOP SECRET" not in relative_result
    assert "TOP SECRET" not in absolute_result


def test_plan_mode_prepends_hint(tmp_path):
    from coding_cli import tools

    agent = make_agent(tmp_path, ["here is the plan"], mode=tools.MODE_PLAN)
    agent.run_turn("add a feature")
    assert "PLAN MODE" in agent.client.queries[0]


def test_plan_mode_blocks_edits_end_to_end(tmp_path):
    from coding_cli import tools

    responses = [
        '```tool\n{"tool": "write_file", "args": {"path": "a.txt", "content": "x"}}\n```',
        "I cannot edit in plan mode; here is the plan instead.",
    ]
    agent = make_agent(tmp_path, responses, mode=tools.MODE_PLAN)
    answer = agent.run_turn("create a file")
    # The blocked write is fed back to the model as a plan-mode error...
    assert "Plan mode" in agent.client.queries[1]
    # ...and no file was created.
    assert not (tmp_path / "a.txt").exists()
    assert answer == "I cannot edit in plan mode; here is the plan instead."


def test_purpose_is_announced(tmp_path):
    (tmp_path / "a.txt").write_text("hi")
    responses = [
        '```tool\n{"tool": "read_file", "args": {"path": "a.txt"}, '
        '"purpose": "inspect the file"}\n```',
        "done",
    ]
    events = []
    agent = make_agent(tmp_path, responses, report=lambda e, d: events.append((e, d)))
    agent.run_turn("look at a.txt")
    assert ("tool_purpose", "inspect the file") in events


def test_no_purpose_no_event(tmp_path):
    (tmp_path / "a.txt").write_text("hi")
    responses = [
        '```tool\n{"tool": "read_file", "args": {"path": "a.txt"}}\n```',
        "done",
    ]
    events = []
    agent = make_agent(tmp_path, responses, report=lambda e, d: events.append((e, d)))
    agent.run_turn("look at a.txt")
    assert not any(e == "tool_purpose" for e, _ in events)


def test_exit_plan_hint_emitted_once_after_leaving_plan(tmp_path):
    from coding_cli import tools

    agent = make_agent(tmp_path, ["done1", "done2"], mode=tools.MODE_PLAN)
    agent.set_mode(tools.MODE_AUTO)
    assert agent._exit_plan_pending is True
    agent.run_turn("first after switch")
    assert "Plan mode is over" in agent.client.queries[0]
    assert agent._exit_plan_pending is False
    # The hint is one-shot: the next turn does not repeat it.
    agent.run_turn("second")
    assert "Plan mode is over" not in agent.client.queries[1]


def test_set_mode_no_hint_when_not_leaving_plan(tmp_path):
    from coding_cli import tools

    agent = make_agent(tmp_path, ["x"], mode=tools.MODE_DEFAULT)
    agent.set_mode(tools.MODE_AUTO)
    assert agent._exit_plan_pending is False
    agent.run_turn("go")
    assert "Plan mode is over" not in agent.client.queries[0]


def test_status_note_reported_and_loop_continues(tmp_path):
    (tmp_path / "a.txt").write_text("data")
    responses = [
        'Reading the file now.\n```tool\n{"tool": "read_file", "args": {"path": "a.txt"}}\n```',
        "All done.",
    ]
    events = []
    agent = make_agent(tmp_path, responses, report=lambda e, d: events.append((e, d)))
    answer = agent.run_turn("look at a.txt")
    assert ("note", "Reading the file now.") in events
    # The tool still ran (its result went back to the model) and the turn finished.
    assert "TOOL_RESULT[read_file]" in agent.client.queries[1]
    assert answer == "All done."


def test_bare_json_tool_call_emits_no_note(tmp_path):
    (tmp_path / "a.txt").write_text("data")
    responses = [
        'ignore me {"tool": "read_file", "args": {"path": "a.txt"}}',
        "done",
    ]
    events = []
    agent = make_agent(tmp_path, responses, report=lambda e, d: events.append((e, d)))
    agent.run_turn("go")
    assert not any(e == "note" for e, _ in events)


def _run_emitter(deltas):
    from coding_cli.agent import StreamEmitter

    sink = FakeSink()
    em = StreamEmitter(sink)
    for d in deltas:
        em.feed(d)
    em.finish()
    return sink


def test_stream_emitter_streams_plain_answer():
    sink = _run_emitter(["Hello ", "world", ", done."])
    assert sink.streamed == "Hello world, done."


def test_stream_emitter_suppresses_tool_block():
    sink = _run_emitter([
        "Reading the file now.\n",
        '```tool\n{"tool": "read_file", "args": {"path": "a"}}\n```',
    ])
    assert sink.streamed == "Reading the file now.\n"
    assert "tool" not in "".join(sink.deltas).split("\n")[-1]  # no JSON
    assert "read_file" not in sink.streamed


def test_stream_emitter_sentinel_split_across_deltas():
    # The fence arrives one/two chars at a time; must still be caught.
    sink = _run_emitter(["note ", "`", "`", "`", "tool\n{}", "```"])
    assert sink.streamed == "note "


def test_stream_emitter_keeps_python_fence():
    sink = _run_emitter(["Here:\n", "```python\n", "x = 1\n", "```\n"])
    assert "```python" in sink.streamed
    assert "x = 1" in sink.streamed


def test_streaming_shows_note_and_answer_not_tool_json(tmp_path):
    (tmp_path / "a.txt").write_text("data")
    responses = [
        'Checking the file.\n```tool\n{"tool": "read_file", "args": {"path": "a.txt"}}\n```',
        "All good — the file has data.",
    ]
    sink = FakeSink()
    events = []
    agent = make_agent(
        tmp_path, responses, sink=sink, stream=True,
        report=lambda e, d: events.append((e, d)),
    )
    agent.run_turn("look")
    assert "Checking the file." in sink.streamed
    assert "All good — the file has data." in sink.streamed
    assert "read_file" not in sink.streamed  # tool JSON never streamed
    # In streaming mode the note is streamed, not sent through report().
    assert not any(e == "note" for e, _ in events)


def test_non_streaming_uses_answer_and_note(tmp_path):
    (tmp_path / "a.txt").write_text("data")
    responses = [
        'Checking.\n```tool\n{"tool": "read_file", "args": {"path": "a.txt"}}\n```',
        "Done.",
    ]
    sink = FakeSink()
    events = []
    agent = make_agent(
        tmp_path, responses, sink=sink, stream=False,
        report=lambda e, d: events.append((e, d)),
    )
    agent.run_turn("look")
    assert sink.deltas == []          # nothing streamed
    assert sink.answers == ["Done."]  # final answer rendered in one shot
    assert ("note", "Checking.") in events


def test_use_skill_loads_body(tmp_path):
    from coding_cli.skills import Skill

    skills = {
        "greeter": Skill(
            name="greeter",
            description="say hi",
            path=tmp_path / "SKILL.md",
            body="Wave at the user.",
        )
    }
    responses = [
        '```tool\n{"tool": "use_skill", "args": {"name": "greeter"}}\n```',
        "Done following the skill.",
    ]
    agent = make_agent(tmp_path, responses, skills=skills)
    agent.run_turn("greet")
    assert "Wave at the user." in agent.client.queries[1]
