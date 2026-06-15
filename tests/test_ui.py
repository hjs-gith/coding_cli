import re

import pytest

from coding_cli import ui

ANSI = re.compile(r"\x1b\[")


def test_gutter_prefixes_label_and_each_line():
    block = ui.gutter("assistant", "line one\nline two")
    assert block.splitlines() == [
        "▎ assistant",
        "▎ line one",
        "▎ line two",
    ]


def test_gutter_handles_empty_body():
    assert ui.gutter("you", "") == "▎ you\n▎ "


def test_tool_line_formats():
    assert ui.tool_line("read_file: a.py") == "  → read_file: a.py"
    assert ui.tool_done("read_file: ok") == "  ✓ read_file: ok"


def test_plain_assistant_has_no_ansi(capsys):
    ui.configure(force_plain=True)
    try:
        ui.assistant("# Title\nsome text")
        captured = capsys.readouterr().out
        assert "▎ assistant" in captured
        assert "some text" in captured
        assert not ANSI.search(captured)  # no escape codes in plain mode
    finally:
        ui.configure()  # restore default detection for other tests


def test_rich_assistant_runs_without_error(capsys):
    pytest.importorskip("rich")
    ui.configure(force_plain=False)
    try:
        ui.assistant("# Heading\n\n- a\n- b\n\n`code`")
        out = capsys.readouterr().out
        assert "assistant" in out
    finally:
        ui.configure()
