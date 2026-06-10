"""Configuration loading for the coding CLI.

Reads settings from environment / a local ``.env`` file. The only required value
is ``DIFY_API_KEY``; everything else has a sensible default.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is a declared dependency
    def load_dotenv(*_args, **_kwargs):  # type: ignore
        return False


DEFAULT_BASE_URL = "https://api.dify.ai/v1"
DEFAULT_USER_ID = "coding-cli"
DEFAULT_MAX_TOOL_ITERS = 12


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@dataclass
class Config:
    """Resolved runtime configuration."""

    api_key: str
    base_url: str = DEFAULT_BASE_URL
    user_id: str = DEFAULT_USER_ID
    max_tool_iters: int = DEFAULT_MAX_TOOL_ITERS
    workdir: Path = field(default_factory=Path.cwd)

    @classmethod
    def load(cls, workdir: Path | None = None) -> "Config":
        """Load configuration from the environment and ``.env``.

        ``.env`` is searched from ``workdir`` (or CWD) upward. Values are
        stripped defensively because the project's ``.env`` may contain spaces
        around the ``=`` (e.g. ``DIFY_API_KEY =...``).
        """
        work = Path(workdir).resolve() if workdir else Path.cwd()
        load_dotenv()  # current dir / ancestors
        env_file = _find_env(work)
        if env_file:
            load_dotenv(env_file, override=False)

        api_key = _clean(os.environ.get("DIFY_API_KEY"))
        if not api_key:
            raise ConfigError(
                "DIFY_API_KEY is not set. Add it to your environment or a .env "
                "file (e.g. DIFY_API_KEY=app-xxxxxxxx)."
            )

        base_url = _clean(os.environ.get("DIFY_BASE_URL")) or DEFAULT_BASE_URL
        base_url = base_url.rstrip("/")
        user_id = _clean(os.environ.get("DIFY_USER_ID")) or DEFAULT_USER_ID

        max_iters = _clean(os.environ.get("CODING_CLI_MAX_TOOL_ITERS"))
        try:
            max_tool_iters = int(max_iters) if max_iters else DEFAULT_MAX_TOOL_ITERS
        except ValueError:
            max_tool_iters = DEFAULT_MAX_TOOL_ITERS

        return cls(
            api_key=api_key,
            base_url=base_url,
            user_id=user_id,
            max_tool_iters=max_tool_iters,
            workdir=work,
        )


def _clean(value: str | None) -> str:
    """Strip surrounding whitespace and matching quotes from an env value."""
    if value is None:
        return ""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value


def _find_env(start: Path) -> Path | None:
    """Walk up from ``start`` looking for a ``.env`` file."""
    for directory in [start, *start.parents]:
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    return None
