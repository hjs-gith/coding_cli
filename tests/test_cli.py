from coding_cli import cli
from coding_cli.tools import MODE_AUTO, MODE_DEFAULT, MODE_PLAN


class _StubAgent:
    """Minimal stand-in: /plan //auto //normal only touch ``mode``."""

    mode = MODE_DEFAULT


def test_mode_commands_set_mode():
    a = _StubAgent()
    assert cli._handle_command(a, "/plan") is False
    assert a.mode == MODE_PLAN
    cli._handle_command(a, "/auto")
    assert a.mode == MODE_AUTO
    cli._handle_command(a, "/normal")
    assert a.mode == MODE_DEFAULT


def test_mode_label():
    assert cli._mode_label(MODE_DEFAULT) == ""
    assert cli._mode_label(MODE_PLAN) == "plan"
    assert cli._mode_label(MODE_AUTO) == "auto"
