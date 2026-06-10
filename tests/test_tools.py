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


def test_run_shell(tmp_path):
    out = tools.execute(ctx(tmp_path), "run_shell", {"command": "echo hi"})
    assert "exit code: 0" in out
    assert "hi" in out


def test_confirm_declined_blocks_write(tmp_path):
    c = ctx(tmp_path, confirm=lambda action, detail: False)
    out = tools.execute(c, "write_file", {"path": "a.txt", "content": "x"})
    assert out.startswith("ERROR")
    assert not (tmp_path / "a.txt").exists()


def test_bad_arguments(tmp_path):
    out = tools.execute(ctx(tmp_path), "read_file", {"wrong": "arg"})
    assert out.startswith("ERROR")
