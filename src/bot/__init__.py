"""
Public surface of the src.bot package.

Exports the GitDiscordBot class and the start_bot coroutine so that
callers (e.g. __main__.py) only need to import from src.bot rather than
knowing the internal module layout.
"""

from src.bot.client import GitDiscordBot, start_bot

__all__ = ["GitDiscordBot", "start_bot"]
