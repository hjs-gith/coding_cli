import pytest

from coding_cli import tools
from coding_cli.tools import ConfirmDecision, ToolContext


def ctx(tmp_path, confirm=None):
    return ToolContext(workdir=tmp_path, confirm=confirm)


def test_confirm_feedback_reaches_model(tmp_path):
    c = ctx(tmp_path, confirm=lambda a, d, p="": ConfirmDecision(False, "use npm instead"))
    out = tools.execute(c, "write_file", {"path": "a.txt", "content": "x"})
    assert out.startswith("ERROR")
    assert "Feedback: use npm instead" in out
    assert not (tmp_path / "a.txt").exists()


def test_confirm_decision_approve(tmp_path):
    c = ctx(tmp_path, confirm=lambda a, d, p="": ConfirmDecision(True))
    out = tools.execute(c, "write_file", {"path": "a.txt", "content": "hi"})
    assert "Created" in out
    assert (tmp_path / "a.txt").read_text() == "hi"


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


def test_edit_file_miss_guides_reread(tmp_path):
    (tmp_path / "a.txt").write_text("current contents")
    out = tools.execute(
        ctx(tmp_path), "edit_file", {"path": "a.txt", "old": "stale", "new": "x"}
    )
    assert out.startswith("ERROR")
    assert "not found" in out
    assert "read_file" in out
    assert "manually" in out  # instructs against punting to manual editing
    # File is untouched.
    assert (tmp_path / "a.txt").read_text() == "current contents"


def test_path_escape_rejected(tmp_path):
    out = tools.execute(ctx(tmp_path), "read_file", {"path": "../secret"})
    assert out.startswith("ERROR")
    assert "outside" in out


def test_coding_cli_dir_is_off_limits(tmp_path):
    (tmp_path / ".coding_cli" / "snapshots").mkdir(parents=True)
    (tmp_path / ".coding_cli" / "journal.json").write_text("{}")
    c = ctx(tmp_path)
    # Every tool that resolves a path refuses anything under .coding_cli, even
    # without any configured denylist (it is always reserved).
    for call in (
        ("read_file", {"path": ".coding_cli/journal.json"}),
        ("list_dir", {"path": ".coding_cli"}),
        ("write_file", {"path": ".coding_cli/journal.json", "content": "x"}),
        ("write_file", {"path": ".coding_cli/snapshots/0001.bak", "content": "x"}),
    ):
        out = tools.execute(c, *call)
        assert out.startswith("ERROR"), call
        assert "off-limits" in out, call
    # The journal was not modified.
    assert (tmp_path / ".coding_cli" / "journal.json").read_text() == "{}"


def test_plan_mode_blocks_all_mutations(tmp_path):
    (tmp_path / "a.txt").write_text("orig")
    c = ToolContext(
        workdir=tmp_path,
        confirm=lambda a, d, preview="": True,  # would approve, but plan blocks
        mode=tools.MODE_PLAN,
    )
    for call in (
        ("write_file", {"path": "b.txt", "content": "x"}),
        ("edit_file", {"path": "a.txt", "old": "orig", "new": "new"}),
        ("run_shell", {"command": "echo hi"}),
    ):
        out = tools.execute(c, *call)
        assert out.startswith("ERROR"), call
        assert "Plan mode" in out, call
    assert not (tmp_path / "b.txt").exists()
    assert (tmp_path / "a.txt").read_text() == "orig"


def test_auto_mode_approves_edits_but_still_confirms_shell(tmp_path):
    # A confirm that always declines — auto-edit must bypass it for file edits
    # but still consult it for run_shell.
    c = ToolContext(
        workdir=tmp_path,
        confirm=lambda a, d, preview="": False,
        mode=tools.MODE_AUTO,
    )
    out = tools.execute(c, "write_file", {"path": "a.txt", "content": "hi"})
    assert "Created" in out
    assert (tmp_path / "a.txt").read_text() == "hi"
    shell = tools.execute(c, "run_shell", {"command": "echo hi"})
    assert shell.startswith("ERROR")
    assert "declined" in shell


def test_coding_cli_dir_hidden_from_listing(tmp_path):
    (tmp_path / ".coding_cli" / "snapshots").mkdir(parents=True)
    (tmp_path / "real.txt").write_text("hi")
    out = tools.execute(ctx(tmp_path), "list_dir", {"path": "."})
    assert "real.txt" in out
    assert ".coding_cli" not in out


def deny_ctx(tmp_path, deny):
    return ToolContext(workdir=tmp_path, deny=tuple(deny))


def test_denylist_blocks_configured_paths(tmp_path):
    (tmp_path / ".env").write_text("DIFY_API_KEY=secret")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("[core]")
    c = deny_ctx(tmp_path, [".env", ".git"])
    for call in (
        ("read_file", {"path": ".env"}),
        ("edit_file", {"path": ".env", "old": "secret", "new": "x"}),
        ("read_file", {"path": ".git/config"}),
        ("write_file", {"path": ".git/hooks/pre-commit", "content": "x"}),
    ):
        out = tools.execute(c, *call)
        assert out.startswith("ERROR"), call
        assert "protected" in out, call
    assert (tmp_path / ".env").read_text() == "DIFY_API_KEY=secret"


def test_denylist_hides_entries_from_listing(tmp_path):
    (tmp_path / ".env").write_text("x")
    (tmp_path / "keep.txt").write_text("y")
    out = tools.execute(deny_ctx(tmp_path, [".env"]), "list_dir", {"path": "."})
    assert "keep.txt" in out
    assert ".env" not in out


def test_denylist_does_not_block_unlisted_paths(tmp_path):
    (tmp_path / "notes.txt").write_text("hello")
    out = tools.execute(deny_ctx(tmp_path, [".env"]), "read_file", {"path": "notes.txt"})
    assert out == "hello"


def test_run_shell(tmp_path):
    out = tools.execute(ctx(tmp_path), "run_shell", {"command": "echo hi"})
    assert "exit code: 0" in out
    assert "hi" in out


def test_run_shell_utf8_output(tmp_path):
    # bytes e2 86 92 = "→"; the byte 0xe2 is what crashed cp949 decoding.
    out = tools.execute(ctx(tmp_path), "run_shell", {"command": r"printf '\342\206\222'"})
    assert "→" in out


def test_run_shell_invalid_bytes_do_not_crash(tmp_path):
    # 0xff / 0xfe are invalid UTF-8; errors="replace" must keep it from raising.
    out = tools.execute(ctx(tmp_path), "run_shell", {"command": r"printf '\377\376'"})
    assert "exit code: 0" in out
    assert "�" in out  # replacement character, not an exception


def test_edit_file_non_utf8_returns_clean_error(tmp_path):
    p = tmp_path / "bin.dat"
    p.write_bytes(b"\xff\xfe hello world")
    out = tools.execute(
        ctx(tmp_path), "edit_file", {"path": "bin.dat", "old": "hello", "new": "bye"}
    )
    assert out.startswith("ERROR")
    assert "UTF-8" in out
    assert p.read_bytes() == b"\xff\xfe hello world"  # untouched


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
