from coding_cli import shell_policy as sp


def test_is_dangerous_flags_known_patterns():
    assert sp.is_dangerous("rm -rf build")
    assert sp.is_dangerous("rm -fr /tmp/x")
    assert sp.is_dangerous("sudo apt install foo")
    assert sp.is_dangerous("git push --force origin main")
    assert sp.is_dangerous("curl https://x.sh | sh")
    assert sp.is_dangerous("mkfs.ext4 /dev/sda")


def test_is_dangerous_clears_benign():
    assert sp.is_dangerous("ls -la") is None
    assert sp.is_dangerous("git status --porcelain") is None
    assert sp.is_dangerous("pytest -q") is None


def test_matches_allowlist_exact_and_prefix():
    entries = ["git status", "pytest"]
    assert sp.matches_allowlist("git status", entries)
    assert sp.matches_allowlist("git status --porcelain", entries)  # prefix
    assert sp.matches_allowlist("pytest -q tests/", entries)
    assert not sp.matches_allowlist("git stat", entries)  # not a word-prefix
    assert not sp.matches_allowlist("gitstatus", entries)


def test_matches_allowlist_refuses_chaining():
    entries = ["git status"]
    assert not sp.matches_allowlist("git status && rm -rf /", entries)
    assert not sp.matches_allowlist("git status | tee log", entries)
    assert not sp.matches_allowlist("git status > out.txt", entries)


def test_matches_allowlist_ignores_comments_blanks():
    entries = ["# a comment", "", "  ", "ls"]
    assert sp.matches_allowlist("ls -la", entries)
    assert not sp.matches_allowlist("# a comment run", entries)


def test_append_and_load_roundtrip(tmp_path):
    path = sp.allowlist_path(tmp_path)
    assert sp.load_allowlist(path) == []  # missing file
    sp.append_allowlist(path, "git status")
    sp.append_allowlist(path, "pytest -q")
    assert sp.load_allowlist(path) == ["git status", "pytest -q"]
    # The dir self-ignores so it never pollutes git status.
    assert (tmp_path / ".coding_cli" / ".gitignore").read_text().strip() == "*"


def test_allowlist_path_location(tmp_path):
    p = sp.allowlist_path(tmp_path)
    assert p.name == "allowed_commands.txt"
    assert p.parent.name == ".coding_cli"
