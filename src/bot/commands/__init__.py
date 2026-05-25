"""
Slash-command cog modules for the GitDiscord bot.

Each submodule in this package defines a discord.py Cog containing a
related group of slash commands (e.g. link_commands for channel-to-repo
linking, issue_commands for GitHub issue management).  The bot's
setup_hook loads every cog from EXTENSION_MODULE_PATHS in client.py.
"""
