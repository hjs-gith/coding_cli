from coding_cli import cli
from coding_cli import shell_policy as sp
from coding_cli.tools import MODE_AUTO, MODE_DEFAULT, MODE_PLAN


class _StubAgent:
    """Minimal stand-in mirroring Agent.set_mode for /plan //auto //normal."""

    def __init__(self):
        self.mode = MODE_DEFAULT
        self._exit_plan_pending = False

    def set_mode(self, mode):
        if self.mode == MODE_PLAN and mode != MODE_PLAN:
            self._exit_plan_pending = True
        self.mode = mode


def test_mode_commands_set_mode():
    a = _StubAgent()
    assert cli._handle_command(a, "/plan") is False
    assert a.mode == MODE_PLAN
    cli._handle_command(a, "/auto")
    assert a.mode == MODE_AUTO
    # Leaving plan mode via a command arms the one-shot exit-plan hint.
    assert a._exit_plan_pending is True
    cli._handle_command(a, "/normal")
    assert a.mode == MODE_DEFAULT


def test_mode_label():
    assert cli._mode_label(MODE_DEFAULT) == ""
    assert cli._mode_label(MODE_PLAN) == "plan"
    assert cli._mode_label(MODE_AUTO) == "auto"


def _no_input(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("input() should not have been called")
    monkeypatch.setattr("builtins.input", boom)


def test_shell_allowlisted_auto_approves(monkeypatch, tmp_path):
    sp.append_allowlist(sp.allowlist_path(tmp_path), "git status")
    confirm = cli._make_confirm(lambda: tmp_path)
    _no_input(monkeypatch)  # must not prompt
    decision = confirm("run_shell", "git status --porcelain")
    assert decision.approved is True


def test_shell_always_allow_persists(monkeypatch, tmp_path):
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "a")
    confirm = cli._make_confirm(lambda: tmp_path)
    decision = confirm("run_shell", "pytest -q")
    assert decision.approved is True
    assert "pytest -q" in sp.load_allowlist(sp.allowlist_path(tmp_path))


def test_dangerous_not_auto_approved(monkeypatch, tmp_path):
    # Even though "rm" is allowlisted, a dangerous rm -rf must still prompt.
    sp.append_allowlist(sp.allowlist_path(tmp_path), "rm")
    calls = []
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: calls.append(1) or "n")
    confirm = cli._make_confirm(lambda: tmp_path)
    decision = confirm("run_shell", "rm -rf build")
    assert decision.approved is False
    assert calls  # was prompted, not silently auto-approved


# --- /image -----------------------------------------------------------------

class _VisionClient:
    def __init__(self, enabled):
        self._enabled = enabled

    def image_upload_enabled(self):
        return self._enabled


class _ImageAgent:
    """Stand-in exposing just what /image touches."""

    def __init__(self, workdir, vision=None):
        self.workdir = workdir
        self.pending_images = []
        self.mode = MODE_DEFAULT
        self.client = _VisionClient(vision)


def _png(tmp_path, name="shot.png"):
    p = tmp_path / name
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    return p


def test_image_command_queues(tmp_path):
    _png(tmp_path)
    a = _ImageAgent(tmp_path)
    assert cli._handle_command(a, "/image shot.png") is False
    assert a.pending_images == ["shot.png"]


def test_image_command_queues_multiple(tmp_path):
    _png(tmp_path, "a.png")
    _png(tmp_path, "b.jpg")
    a = _ImageAgent(tmp_path)
    cli._handle_command(a, "/image a.png b.jpg")
    assert a.pending_images == ["a.png", "b.jpg"]


def test_image_command_clear(tmp_path):
    _png(tmp_path)
    a = _ImageAgent(tmp_path)
    cli._handle_command(a, "/image shot.png")
    cli._handle_command(a, "/image clear")
    assert a.pending_images == []


def test_image_command_rejects_missing_and_non_image(tmp_path):
    (tmp_path / "notes.txt").write_text("hi")
    a = _ImageAgent(tmp_path)
    cli._handle_command(a, "/image nope.png")
    cli._handle_command(a, "/image notes.txt")
    assert a.pending_images == []  # neither queued


def test_image_warns_when_vision_disabled(tmp_path, capsys):
    _png(tmp_path)
    a = _ImageAgent(tmp_path, vision=False)
    cli._handle_command(a, "/image shot.png")
    out = capsys.readouterr().out
    assert "image upload disabled" in out
    assert a.pending_images == ["shot.png"]  # still queued; just warned


def test_image_quiet_when_vision_unknown(tmp_path, capsys):
    _png(tmp_path)
    a = _ImageAgent(tmp_path, vision=None)
    cli._handle_command(a, "/image shot.png")
    assert "image upload disabled" not in capsys.readouterr().out


def test_help_mentions_image(capsys):
    cli._handle_command(_StubAgent(), "/help")
    assert "/image" in capsys.readouterr().out
