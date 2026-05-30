"""Importing this package registers every built-in provider."""

from .base import Provider, build, register  # noqa: F401
from . import command  # noqa: F401  (registers "command")
from . import claude_code  # noqa: F401  (registers "claude_code")
from . import codex  # noqa: F401  (registers "codex")
from . import manual  # noqa: F401  (registers "manual")

__all__ = ["Provider", "build", "register"]
