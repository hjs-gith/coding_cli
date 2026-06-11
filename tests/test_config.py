from coding_cli.config import DEFAULT_DENY, Config


def _no_dotenv(monkeypatch):
    # Ignore any real .env on disk so tests only see the env we set.
    monkeypatch.setattr("coding_cli.config.load_dotenv", lambda *a, **k: False)


def test_deny_defaults(monkeypatch, tmp_path):
    _no_dotenv(monkeypatch)
    monkeypatch.setenv("DIFY_API_KEY", "app-x")
    monkeypatch.delenv("CODING_CLI_DENY", raising=False)
    cfg = Config.load(workdir=tmp_path)
    assert cfg.deny == DEFAULT_DENY


def test_deny_override_parses_and_trims(monkeypatch, tmp_path):
    _no_dotenv(monkeypatch)
    monkeypatch.setenv("DIFY_API_KEY", "app-x")
    monkeypatch.setenv("CODING_CLI_DENY", ".env, secrets ,, .git")
    cfg = Config.load(workdir=tmp_path)
    assert cfg.deny == (".env", "secrets", ".git")


def test_deny_empty_disables_defaults(monkeypatch, tmp_path):
    _no_dotenv(monkeypatch)
    monkeypatch.setenv("DIFY_API_KEY", "app-x")
    monkeypatch.setenv("CODING_CLI_DENY", "")
    cfg = Config.load(workdir=tmp_path)
    assert cfg.deny == ()
