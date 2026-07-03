from coding_cli import protocol


def test_parse_valid_tool_call():
    text = '```tool\n{"tool": "read_file", "args": {"path": "a.py"}}\n```'
    call = protocol.parse_tool_call(text)
    assert call is not None
    assert call.name == "read_file"
    assert call.args == {"path": "a.py"}


def test_parse_captures_purpose():
    text = (
        '```tool\n{"tool": "run_shell", "args": {"command": "pytest -q"}, '
        '"purpose": "run the tests"}\n```'
    )
    call = protocol.parse_tool_call(text)
    assert call is not None
    assert call.purpose == "run the tests"


def test_parse_purpose_defaults_empty():
    text = '```tool\n{"tool": "read_file", "args": {"path": "a.py"}}\n```'
    call = protocol.parse_tool_call(text)
    assert call.purpose == ""


def test_parse_non_string_purpose_ignored():
    text = '```tool\n{"tool": "read_file", "args": {"path": "a.py"}, "purpose": 5}\n```'
    call = protocol.parse_tool_call(text)
    assert call is not None
    assert call.purpose == ""


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


def test_parse_bare_json_without_fence():
    text = '{"tool": "write_file", "args": {"path": "a.py", "content": "x"}}'
    call = protocol.parse_tool_call(text)
    assert call is not None
    assert call.name == "write_file"
    assert call.args == {"path": "a.py", "content": "x"}


def test_parse_json_fence_label():
    text = '```json\n{"tool": "list_dir", "args": {"path": "."}}\n```'
    call = protocol.parse_tool_call(text)
    assert call is not None
    assert call.name == "list_dir"


def test_parse_fence_and_json_on_one_line():
    text = '```tool {"tool": "list_dir", "args": {"path": "."}}```'
    call = protocol.parse_tool_call(text)
    assert call is not None
    assert call.name == "list_dir"


def test_parse_json_with_surrounding_prose():
    text = 'Sure, I will do that.\n{"tool": "read_file", "args": {"path": "a.py"}}'
    call = protocol.parse_tool_call(text)
    assert call is not None
    assert call.name == "read_file"
    assert call.args == {"path": "a.py"}


def test_parse_write_file_content_with_braces():
    text = (
        '{"tool": "write_file", "args": {"path": "a.json", '
        '"content": "{\\"a\\": 1, \\"b\\": {\\"c\\": 2}}"}}'
    )
    call = protocol.parse_tool_call(text)
    assert call is not None
    assert call.name == "write_file"
    assert call.args["content"] == '{"a": 1, "b": {"c": 2}}'


def test_parse_prose_with_stray_brace_returns_none():
    assert protocol.parse_tool_call("use the { key to open the menu") is None


def test_build_preamble_includes_catalog():
    pre = protocol.build_preamble([("commit-helper", "make a commit")])
    assert "commit-helper" in pre
    assert "make a commit" in pre
    assert "use_skill" in pre


def test_build_preamble_without_skills():
    pre = protocol.build_preamble([])
    assert "No custom skills" in pre


def test_preamble_has_persistence_instructions():
    pre = protocol.build_preamble([])
    # Keep-going cue and the "CLI already confirms, don't ask in prose" cue.
    assert "keep going until the whole" in pre
    assert "never ask" in pre
    assert "The CLI already asks the user to confirm" in pre


def test_format_tool_result():
    out = protocol.format_tool_result("read_file", "hello")
    assert out.startswith("TOOL_RESULT[read_file]:")
    assert "hello" in out
