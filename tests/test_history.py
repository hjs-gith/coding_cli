from coding_cli import tools
from coding_cli.history import ChangeHistory
from coding_cli.tools import ToolContext


def ctx(tmp_path):
    return ToolContext(workdir=tmp_path, history=ChangeHistory(tmp_path))


def test_undo_restores_prior_content(tmp_path):
    (tmp_path / "a.txt").write_text("original")
    c = ctx(tmp_path)
    tools.execute(c, "write_file", {"path": "a.txt", "content": "changed"})
    assert (tmp_path / "a.txt").read_text() == "changed"
    msg = c.history.undo()
    assert "restored" in msg
    assert (tmp_path / "a.txt").read_text() == "original"


def test_undo_of_created_file_deletes_it(tmp_path):
    c = ctx(tmp_path)
    tools.execute(c, "write_file", {"path": "new.txt", "content": "hi"})
    assert (tmp_path / "new.txt").exists()
    c.history.undo()
    assert not (tmp_path / "new.txt").exists()


def test_repeated_undo_walks_back_changes(tmp_path):
    c = ctx(tmp_path)
    tools.execute(c, "write_file", {"path": "a.txt", "content": "v1"})
    tools.execute(c, "write_file", {"path": "a.txt", "content": "v2"})
    tools.execute(c, "write_file", {"path": "a.txt", "content": "v3"})
    assert (tmp_path / "a.txt").read_text() == "v3"
    c.history.undo()
    assert (tmp_path / "a.txt").read_text() == "v2"
    c.history.undo()
    assert (tmp_path / "a.txt").read_text() == "v1"
    # v1 created the file; the final undo removes it.
    c.history.undo()
    assert not (tmp_path / "a.txt").exists()


def test_undo_when_empty(tmp_path):
    assert ChangeHistory(tmp_path).undo() == "Nothing to undo."


def test_session_diff_shows_net_change(tmp_path):
    (tmp_path / "a.txt").write_text("line one\nline two\n")
    c = ctx(tmp_path)
    tools.execute(
        c, "edit_file", {"path": "a.txt", "old": "line two", "new": "line TWO"}
    )
    diff = c.history.session_diff()
    assert "-line two" in diff
    assert "+line TWO" in diff


def test_journal_persists_and_reloads(tmp_path):
    c = ctx(tmp_path)
    tools.execute(c, "write_file", {"path": "a.txt", "content": "first"})
    # A fresh ChangeHistory (e.g. a new process) hydrates from journal.json.
    reloaded = ChangeHistory(tmp_path)
    msg = reloaded.undo()
    assert "removed" in msg
    assert not (tmp_path / "a.txt").exists()


def test_snapshot_dir_is_self_ignored(tmp_path):
    c = ctx(tmp_path)
    tools.execute(c, "write_file", {"path": "a.txt", "content": "x"})
    gitignore = tmp_path / ".coding_cli" / ".gitignore"
    assert gitignore.is_file()
    assert gitignore.read_text().strip() == "*"
