from coding_cli import cli
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
