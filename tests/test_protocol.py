from coding_cli import protocol


def test_parse_valid_tool_call():
    text = '```tool\n{"tool": "read_file", "args": {"path": "a.py"}}\n```'
    call = protocol.parse_tool_call(text)
    assert call is not None
    assert call.name == "read_file"
    assert call.args == {"path": "a.py"}


def test_parse_no_block_returns_none():
    assert protocol.parse_tool_call("just a plain final answer") is None


def test_parse_malformed_json_returns_none():
    text = "```tool\n{not valid json}\n```"
    assert protocol.parse_tool_call(text) is None


def test_parse_unknown_tool_returns_none():
    text = '```tool\n{"tool": "delete_everything", "args": {}}\n```'
    assert protocol.parse_tool_call(text) is None


def test_parse_args_must_be_dict():
    text = '```tool\n{"tool": "read_file", "args": [1, 2]}\n```'
    assert protocol.parse_tool_call(text) is None


def test_build_preamble_includes_catalog():
    pre = protocol.build_preamble([("commit-helper", "make a commit")])
    assert "commit-helper" in pre
    assert "make a commit" in pre
    assert "use_skill" in pre


def test_build_preamble_without_skills():
    pre = protocol.build_preamble([])
    assert "No custom skills" in pre


def test_format_tool_result():
    out = protocol.format_tool_result("read_file", "hello")
    assert out.startswith("TOOL_RESULT[read_file]:")
    assert "hello" in out
