import pytest

from coding_cli import tools
from coding_cli.tools import ToolContext


def ctx(tmp_path, confirm=None):
    return ToolContext(workdir=tmp_path, confirm=confirm)


def test_write_then_read(tmp_path):
    c = ctx(tmp_path)
    out = tools.execute(c, "write_file", {"path": "a.txt", "content": "hello"})
    assert "Created" in out
    read = tools.execute(c, "read_file", {"path": "a.txt"})
    assert read == "hello"


def test_read_missing_file(tmp_path):
    out = tools.execute(ctx(tmp_path), "read_file", {"path": "nope.txt"})
    assert out.startswith("ERROR")


def test_list_dir(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "f.txt").write_text("x")
    out = tools.execute(ctx(tmp_path), "list_dir", {"path": "."})
    assert "sub/" in out
    assert "f.txt" in out


def test_edit_file_unique(tmp_path):
    (tmp_path / "a.txt").write_text("foo bar baz")
    out = tools.execute(
        ctx(tmp_path), "edit_file", {"path": "a.txt", "old": "bar", "new": "QUX"}
    )
    assert "Edited" in out
    assert (tmp_path / "a.txt").read_text() == "foo QUX baz"


def test_edit_file_not_unique(tmp_path):
    (tmp_path / "a.txt").write_text("x x x")
    out = tools.execute(
        ctx(tmp_path), "edit_file", {"path": "a.txt", "old": "x", "new": "y"}
    )
    assert out.startswith("ERROR")
    assert "not unique" in out


def test_path_escape_rejected(tmp_path):
    out = tools.execute(ctx(tmp_path), "read_file", {"path": "../secret"})
    assert out.startswith("ERROR")
    assert "outside" in out


def test_coding_cli_dir_is_off_limits(tmp_path):
    (tmp_path / ".coding_cli" / "snapshots").mkdir(parents=True)
    (tmp_path / ".coding_cli" / "journal.json").write_text("{}")
    c = ctx(tmp_path)
    # Every tool that resolves a path refuses anything under .coding_cli.
    for call in (
        ("read_file", {"path": ".coding_cli/journal.json"}),
        ("list_dir", {"path": ".coding_cli"}),
        ("write_file", {"path": ".coding_cli/journal.json", "content": "x"}),
        ("write_file", {"path": ".coding_cli/snapshots/0001.bak", "content": "x"}),
    ):
        out = tools.execute(c, *call)
        assert out.startswith("ERROR"), call
        assert "reserved" in out, call
    # The journal was not modified.
    assert (tmp_path / ".coding_cli" / "journal.json").read_text() == "{}"


def test_coding_cli_dir_hidden_from_listing(tmp_path):
    (tmp_path / ".coding_cli" / "snapshots").mkdir(parents=True)
    (tmp_path / "real.txt").write_text("hi")
    out = tools.execute(ctx(tmp_path), "list_dir", {"path": "."})
    assert "real.txt" in out
    assert ".coding_cli" not in out


def test_run_shell(tmp_path):
    out = tools.execute(ctx(tmp_path), "run_shell", {"command": "echo hi"})
    assert "exit code: 0" in out
    assert "hi" in out


def test_confirm_declined_blocks_write(tmp_path):
    c = ctx(tmp_path, confirm=lambda action, detail, preview="": False)
    out = tools.execute(c, "write_file", {"path": "a.txt", "content": "x"})
    assert out.startswith("ERROR")
    assert not (tmp_path / "a.txt").exists()


def test_confirm_receives_diff_preview(tmp_path):
    (tmp_path / "a.txt").write_text("old line\n")
    seen = {}

    def confirm(action, detail, preview=""):
        seen["preview"] = preview
        return True

    c = ctx(tmp_path, confirm=confirm)
    tools.execute(c, "edit_file", {"path": "a.txt", "old": "old", "new": "new"})
    assert "-old line" in seen["preview"]
    assert "+new line" in seen["preview"]


def test_bad_arguments(tmp_path):
    out = tools.execute(ctx(tmp_path), "read_file", {"wrong": "arg"})
    assert out.startswith("ERROR")
