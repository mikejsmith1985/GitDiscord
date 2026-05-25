"""
Slash commands cog for linking Discord channels to GitHub repositories.

Provides /link, /unlink, /status, /nlp-enable, and /nlp-disable commands
that allow server admins to configure per-channel GitHub integrations.
"""

import re

import discord
from discord import app_commands
from discord.ext import commands

from src.db.repository import (
    create_channel_link,
    delete_channel_link,
    disable_nlp_channel,
    enable_nlp_channel,
    get_channel_link,
    is_nlp_channel,
)

# ── Constants ──────────────────────────────────────────────────────────────────

# Regex that enforces "owner/repo" format: both sides non-empty, exactly one slash.
VALID_REPO_FORMAT = r"^[^/]+/[^/]+$"

# Embed colours follow Discord convention: green = success, red = error, blue = info.
EMBED_COLOR_SUCCESS = discord.Color.green()
EMBED_COLOR_ERROR = discord.Color.red()
EMBED_COLOR_INFO = discord.Color.blue()


# ── Helper builders ────────────────────────────────────────────────────────────

def _build_success_embed(title: str, description: str) -> discord.Embed:
    """Return a green embed for successful operations."""
    return discord.Embed(title=title, description=description, color=EMBED_COLOR_SUCCESS)


def _build_error_embed(title: str, description: str) -> discord.Embed:
    """Return a red embed for validation failures and errors."""
    return discord.Embed(title=title, description=description, color=EMBED_COLOR_ERROR)


def _build_info_embed(title: str, description: str) -> discord.Embed:
    """Return a blue embed for neutral status information."""
    return discord.Embed(title=title, description=description, color=EMBED_COLOR_INFO)


def _is_valid_repo_slug(repo: str) -> bool:
    """
    Validate that a repo string follows 'owner/repo' format.

    Both the owner and repo name must be non-empty, and there must be
    exactly one forward-slash separator. This prevents accidental misuse
    such as bare repo names or multi-level paths.
    """
    return bool(re.match(VALID_REPO_FORMAT, repo))


# ── Cog ───────────────────────────────────────────────────────────────────────

class LinkCommands(commands.Cog):
    """
    Discord slash commands for managing channel ↔ GitHub repo links.

    All responses are ephemeral so credentials and configuration details
    remain private to the user who invoked the command.
    """

    def __init__(self, bot: commands.Bot) -> None:
        """Store a reference to the bot so commands can access the DB session."""
        self.bot = bot

    # ── /link ──────────────────────────────────────────────────────────────────

    @app_commands.command(name="link", description="Link this channel to a GitHub repository.")
    @app_commands.describe(
        repo="GitHub repository in owner/repo format (e.g. mikejsmith1985/GitDiscord)",
        token="GitHub Personal Access Token with repo scope — never shared back to you",
    )
    async def link(
        self,
        interaction: discord.Interaction,
        repo: str,
        token: str,
    ) -> None:
        """
        Create or update the link between this Discord channel and a GitHub repo.

        The PAT is stored for API calls on behalf of this channel but is never
        echoed in any response — even ephemerally — to reduce the risk of
        accidental exposure through screenshots or logs.
        """
        isRepoFormatValid = _is_valid_repo_slug(repo)
        if not isRepoFormatValid:
            error_embed = _build_error_embed(
                "❌ Invalid Repository Format",
                f"`{repo}` is not valid. Please use **owner/repo** format, "
                "e.g. `mikejsmith1985/GitDiscord`.",
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
            return

        repo_owner, repo_name = repo.split("/", maxsplit=1)

        async with self.bot.get_db_session() as session:
            create_channel_link(
                session=session,
                guild_id=interaction.guild_id,
                channel_id=interaction.channel_id,
                repo_owner=repo_owner,
                repo_name=repo_name,
                github_pat=token,
            )

        success_embed = _build_success_embed(
            "✅ Channel Linked",
            f"This channel is now linked to **{repo}**.\n\n"
            "GitHub events for that repository will be posted here, and you can "
            "interact with issues and PRs directly from this channel.",
        )
        await interaction.response.send_message(embed=success_embed, ephemeral=True)

    # ── /unlink ────────────────────────────────────────────────────────────────

    @app_commands.command(name="unlink", description="Remove the GitHub repo link from this channel.")
    async def unlink(self, interaction: discord.Interaction) -> None:
        """
        Delete the channel→repo link so no further GitHub activity is posted here.

        Returns a clear message when no link exists, so users aren't left
        wondering whether the command succeeded.
        """
        async with self.bot.get_db_session() as session:
            wasLinkRemoved = delete_channel_link(session=session, channel_id=interaction.channel_id)

        if not wasLinkRemoved:
            info_embed = _build_info_embed(
                "ℹ️ No Linked Repository",
                "This channel has no linked repo — nothing to remove.",
            )
            await interaction.response.send_message(embed=info_embed, ephemeral=True)
            return

        success_embed = _build_success_embed(
            "✅ Channel Unlinked",
            "The GitHub repository link for this channel has been removed. "
            "GitHub events will no longer be posted here.",
        )
        await interaction.response.send_message(embed=success_embed, ephemeral=True)

    # ── /status ────────────────────────────────────────────────────────────────

    @app_commands.command(name="status", description="Show the GitHub repo currently linked to this channel.")
    async def status(self, interaction: discord.Interaction) -> None:
        """
        Display the linked repository for this channel without revealing the PAT.

        The PAT is intentionally omitted from this response — it is a secret
        credential and should never appear in any user-facing output.
        """
        async with self.bot.get_db_session() as session:
            channel_link = get_channel_link(session=session, channel_id=interaction.channel_id)
            hasNlpEnabled = is_nlp_channel(session=session, channel_id=interaction.channel_id)

        if channel_link is None:
            info_embed = _build_info_embed(
                "ℹ️ No Repository Linked",
                "No repo is linked to this channel.\n\n"
                "Use `/link owner/repo <token>` to connect a GitHub repository.",
            )
            await interaction.response.send_message(embed=info_embed, ephemeral=True)
            return

        linked_repo = f"{channel_link.repo_owner}/{channel_link.repo_name}"
        nlp_status_label = "✅ Enabled" if hasNlpEnabled else "❌ Disabled"

        status_embed = _build_info_embed(
            "📋 Channel Status",
            f"**Linked Repository:** `{linked_repo}`\n"
            f"**NLP Command Parsing:** {nlp_status_label}",
        )
        await interaction.response.send_message(embed=status_embed, ephemeral=True)

    # ── /nlp-enable ────────────────────────────────────────────────────────────

    @app_commands.command(name="nlp-enable", description="Enable natural-language command parsing in this channel.")
    async def nlp_enable(self, interaction: discord.Interaction) -> None:
        """
        Turn on NLP mode so the bot interprets plain-English messages as commands.

        For example, typing "show open issues" will trigger a GitHub issues query
        without needing a slash command. Useful in dedicated project channels.
        """
        async with self.bot.get_db_session() as session:
            enable_nlp_channel(session=session, guild_id=interaction.guild_id, channel_id=interaction.channel_id)

        success_embed = _build_success_embed(
            "✅ NLP Mode Enabled",
            "**Natural-language command parsing is now active in this channel.**\n\n"
            "You can now type plain-English requests like:\n"
            "• `show open issues`\n"
            "• `list recent pull requests`\n"
            "• `what commits were made today`\n\n"
            "The bot will interpret these messages and respond with GitHub data.",
        )
        await interaction.response.send_message(embed=success_embed, ephemeral=True)

    # ── /nlp-disable ───────────────────────────────────────────────────────────

    @app_commands.command(name="nlp-disable", description="Disable natural-language command parsing in this channel.")
    async def nlp_disable(self, interaction: discord.Interaction) -> None:
        """
        Turn off NLP mode so the bot only responds to explicit slash commands.

        Use this to prevent the bot from misinterpreting regular conversation
        as GitHub commands in general-purpose channels.
        """
        async with self.bot.get_db_session() as session:
            disable_nlp_channel(session=session, channel_id=interaction.channel_id)

        success_embed = _build_success_embed(
            "✅ NLP Mode Disabled",
            "Natural-language command parsing has been turned off for this channel.\n\n"
            "The bot will now only respond to explicit `/` slash commands.",
        )
        await interaction.response.send_message(embed=success_embed, ephemeral=True)


# ── Registration ───────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot) -> None:
    """Register the LinkCommands cog with the bot at startup."""
    await bot.add_cog(LinkCommands(bot))
