import shutil

from coding_cli import tools
from coding_cli.history import ChangeHistory
from coding_cli.tools import ToolContext


def ctx(tmp_path):
    return ToolContext(workdir=tmp_path, history=ChangeHistory(tmp_path))


def test_undo_missing_snapshot_does_not_crash(tmp_path):
    (tmp_path / "a.txt").write_text("original")
    c = ctx(tmp_path)
    tools.execute(
        c, "edit_file", {"path": "a.txt", "old": "original", "new": "changed"}
    )
    # Simulate the user deleting .coding_cli mid-session.
    shutil.rmtree(tmp_path / ".coding_cli")
    msg = c.history.undo()  # must not raise
    assert "missing" in msg
    # The file is left as the edited content (we couldn't restore it).
    assert (tmp_path / "a.txt").read_text() == "changed"


def test_undo_after_deletion_is_repeatable(tmp_path):
    (tmp_path / "a.txt").write_text("v0")
    c = ctx(tmp_path)
    tools.execute(c, "edit_file", {"path": "a.txt", "old": "v0", "new": "v1"})
    tools.execute(c, "write_file", {"path": "b.txt", "content": "new"})
    shutil.rmtree(tmp_path / ".coding_cli")
    # First undo (b.txt was newly created) still works without a snapshot.
    assert "removed" in c.history.undo()
    assert not (tmp_path / "b.txt").exists()
    # Next undo hits the missing snapshot for a.txt and reports gracefully.
    assert "missing" in c.history.undo()
    # Nothing left to undo.
    assert c.history.undo() == "Nothing to undo."


def test_save_recreates_deleted_dir(tmp_path):
    c = ctx(tmp_path)
    tools.execute(c, "write_file", {"path": "a.txt", "content": "x"})
    shutil.rmtree(tmp_path / ".coding_cli")
    # A subsequent record self-heals the directory and journal.
    tools.execute(c, "write_file", {"path": "b.txt", "content": "y"})
    assert (tmp_path / ".coding_cli" / "journal.json").is_file()


def test_undo_missing_snapshot_across_restart(tmp_path):
    (tmp_path / "a.txt").write_text("original")
    c = ctx(tmp_path)
    tools.execute(
        c, "edit_file", {"path": "a.txt", "old": "original", "new": "changed"}
    )
    # Journal survives but the snapshot is removed; a fresh process (--undo)
    # hydrates from the journal and must not crash.
    shutil.rmtree(tmp_path / ".coding_cli" / "snapshots")
    reloaded = ChangeHistory(tmp_path)
    assert "missing" in reloaded.undo()


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
