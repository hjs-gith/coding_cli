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

    def chat(self, query, stream=True):
        self.queries.append(query)
        answer = self._responses.pop(0)
        return ChatResult(answer=answer, conversation_id="conv-1", message_id="m")

    def reset(self):
        self.conversation_id = ""


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
