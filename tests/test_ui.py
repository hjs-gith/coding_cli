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


def test_stream_sink_plain_is_append_only(capsys):
    # The regression: each chunk must print exactly once (no cumulative stacking).
    ui.configure(force_plain=True)
    try:
        assert ui._LIVE_STREAM is False
        s = ui.ConsoleSink()
        s.begin()
        s.delta("Hi")
        s.delta(", how are you")
        s.end()
        out = capsys.readouterr().out
        assert out.count("Hi, how are you") == 1  # assembled once
        assert "HiHi" not in out                  # no re-drawn cumulative frames
        assert not ANSI.search(out)               # plain, no escape codes
    finally:
        ui.configure()


def test_stream_env_plain_disables_live(monkeypatch):
    monkeypatch.setenv("CODING_CLI_STREAM", "plain")
    ui.configure(force_plain=False)
    try:
        assert ui._LIVE_STREAM is False
    finally:
        monkeypatch.delenv("CODING_CLI_STREAM", raising=False)
        ui.configure()


def test_stream_env_live_forces_panel(monkeypatch):
    pytest.importorskip("rich")
    monkeypatch.setenv("CODING_CLI_STREAM", "live")
    ui.configure(force_plain=False)
    try:
        if ui._console is not None:  # rich active (not forced plain by NO_COLOR)
            assert ui._LIVE_STREAM is True
    finally:
        monkeypatch.delenv("CODING_CLI_STREAM", raising=False)
        ui.configure()
