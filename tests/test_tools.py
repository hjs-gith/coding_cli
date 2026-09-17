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


# --- ranged read_file -------------------------------------------------------

def test_read_file_whole_still_raw(tmp_path):
    # Backward compat: no offset/limit returns exact raw content, no footer.
    (tmp_path / "a.txt").write_text("l1\nl2\nl3")
    out = tools.execute(ctx(tmp_path), "read_file", {"path": "a.txt"})
    assert out == "l1\nl2\nl3"


def test_read_file_offset_limit(tmp_path):
    (tmp_path / "a.txt").write_text("\n".join(f"line{n}" for n in range(1, 11)))
    out = tools.execute(ctx(tmp_path), "read_file", {"path": "a.txt", "offset": 3, "limit": 2})
    assert out == "line3\nline4\n[lines 3-4 of 10]"


def test_read_file_offset_to_end(tmp_path):
    (tmp_path / "a.txt").write_text("a\nb\nc")
    out = tools.execute(ctx(tmp_path), "read_file", {"path": "a.txt", "offset": 2})
    assert out == "b\nc\n[lines 2-3 of 3]"


def test_read_file_offset_past_end(tmp_path):
    (tmp_path / "a.txt").write_text("a\nb")
    out = tools.execute(ctx(tmp_path), "read_file", {"path": "a.txt", "offset": 9})
    assert "past end" in out and "2 lines" in out


def test_read_file_bad_offset(tmp_path):
    (tmp_path / "a.txt").write_text("a\nb")
    out = tools.execute(ctx(tmp_path), "read_file", {"path": "a.txt", "offset": 0})
    assert out.startswith("ERROR")


# --- search_text ------------------------------------------------------------

def test_search_text_finds_matches(tmp_path):
    (tmp_path / "a.py").write_text("def foo():\n    return 1\n")
    (tmp_path / "b.py").write_text("x = 2\n")
    sub = tmp_path / "pkg"
    sub.mkdir()
    (sub / "c.py").write_text("def foo_bar():\n    pass\n")
    out = tools.execute(ctx(tmp_path), "search_text", {"pattern": r"def foo"})
    assert "a.py:1: def foo():" in out
    assert "pkg/c.py:1: def foo_bar():" in out
    assert "b.py" not in out


def test_search_text_no_match(tmp_path):
    (tmp_path / "a.py").write_text("hello\n")
    out = tools.execute(ctx(tmp_path), "search_text", {"pattern": "zzz"})
    assert "No matches" in out


def test_search_text_ignore_case(tmp_path):
    (tmp_path / "a.txt").write_text("Hello World\n")
    miss = tools.execute(ctx(tmp_path), "search_text", {"pattern": "hello world"})
    assert "No matches" in miss
    hit = tools.execute(
        ctx(tmp_path), "search_text", {"pattern": "hello world", "ignore_case": True}
    )
    assert "a.txt:1:" in hit


def test_search_text_glob_filter(tmp_path):
    (tmp_path / "a.py").write_text("TODO here\n")
    (tmp_path / "a.md").write_text("TODO there\n")
    out = tools.execute(ctx(tmp_path), "search_text", {"pattern": "TODO", "glob": "*.py"})
    assert "a.py:1:" in out
    assert "a.md" not in out


def test_search_text_invalid_regex(tmp_path):
    (tmp_path / "a.txt").write_text("x\n")
    out = tools.execute(ctx(tmp_path), "search_text", {"pattern": "("})
    assert out.startswith("ERROR")
    assert "Invalid regex" in out


def test_search_text_skips_reserved_and_denied(tmp_path):
    (tmp_path / "keep.txt").write_text("SECRET token\n")
    (tmp_path / ".env").write_text("SECRET token\n")
    gitdir = tmp_path / ".git"
    gitdir.mkdir()
    (gitdir / "config").write_text("SECRET token\n")
    out = tools.execute(deny_ctx(tmp_path, [".env"]), "search_text", {"pattern": "SECRET"})
    assert "keep.txt:1:" in out
    assert ".env" not in out
    assert ".git" not in out


def test_search_text_skips_binary(tmp_path):
    (tmp_path / "ok.txt").write_text("match me\n")
    (tmp_path / "blob.bin").write_bytes(b"\xff\xfe\x00match\x00")
    out = tools.execute(ctx(tmp_path), "search_text", {"pattern": "match"})
    assert "ok.txt:1:" in out
    assert "blob.bin" not in out


def test_search_text_rejects_escape(tmp_path):
    out = tools.execute(ctx(tmp_path), "search_text", {"pattern": "x", "path": "../.."})
    assert out.startswith("ERROR")


# --- view_image -------------------------------------------------------------

def _png(path):
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)


def image_ctx(tmp_path, queue, **kw):
    return ToolContext(workdir=tmp_path, attach_image=queue.append, **kw)


def test_view_image_queues_absolute_path(tmp_path):
    _png(tmp_path / "shot.png")
    queue = []
    out = tools.execute(image_ctx(tmp_path, queue), "view_image", {"path": "shot.png"})
    assert queue == [str(tmp_path / "shot.png")]
    assert "Attached shot.png" in out


def test_view_image_rejects_non_image(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    queue = []
    out = tools.execute(image_ctx(tmp_path, queue), "view_image", {"path": "a.txt"})
    assert out.startswith("ERROR")
    assert queue == []


def test_view_image_missing_file(tmp_path):
    queue = []
    out = tools.execute(image_ctx(tmp_path, queue), "view_image", {"path": "no.png"})
    assert out.startswith("ERROR")
    assert queue == []


def test_view_image_rejects_escape(tmp_path):
    queue = []
    out = tools.execute(image_ctx(tmp_path, queue), "view_image", {"path": "../x.png"})
    assert out.startswith("ERROR")
    assert queue == []


def test_view_image_respects_denylist(tmp_path):
    (tmp_path / ".git").mkdir()
    _png(tmp_path / ".git" / "s.png")
    queue = []
    c = ToolContext(workdir=tmp_path, attach_image=queue.append, deny=(".git",))
    out = tools.execute(c, "view_image", {"path": ".git/s.png"})
    assert out.startswith("ERROR")
    assert "protected" in out
    assert queue == []


def test_view_image_unavailable_without_callback(tmp_path):
    _png(tmp_path / "shot.png")
    out = tools.execute(ctx(tmp_path), "view_image", {"path": "shot.png"})
    assert out.startswith("ERROR")
    assert "not available" in out


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
