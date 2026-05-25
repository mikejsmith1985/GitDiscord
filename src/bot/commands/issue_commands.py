"""
issue_commands.py — Discord slash-command cog for GitHub issue management.

Provides the /issue command group, letting users list, view, create, comment
on, and close GitHub issues directly from a linked Discord channel.
"""

import discord
from discord import app_commands
from discord.ext import commands

from src.db import repository
from src.formatters.discord_embeds import format_issue_dict
from src.github import GitHubClient


# ── Constants ─────────────────────────────────────────────────────────────────

# Discord embeds can hold a lot of text, but dumping hundreds of issues into one
# message becomes unreadable.  Cap the list so it stays a quick-glance summary.
MAX_ISSUES_DISPLAYED = 10

# Shared footer text to keep all bot-generated embeds visually consistent.
_FOOTER_TEXT = "GitDiscord"


# ── Cog ───────────────────────────────────────────────────────────────────────

class IssueCommands(commands.Cog):
    """
    Discord cog that registers the /issue slash-command group.

    Each subcommand maps to a GitHubClient method so that Discord users
    can interact with a linked repository's issues without leaving Discord.
    The cog resolves the correct GitHubClient from the channel → repo link
    stored in the database on every command invocation, so PAT rotation or
    repo changes are always picked up immediately.
    """

    def __init__(self, bot: commands.Bot) -> None:
        """
        Initialise the cog with a reference to the running bot instance.

        The bot is stored so the cog can call bot.get_db_session() to look
        up per-channel GitHub credentials at command time.

        Args:
            bot: The running GitDiscordBot instance that loaded this cog.
        """
        self.bot = bot

    # ── App-command group ─────────────────────────────────────────────────────

    # All /issue subcommands are nested under this group so Discord presents
    # them together in the autocomplete UI rather than as separate top-level
    # commands.
    issue_group = app_commands.Group(
        name="issue",
        description="Manage GitHub issues for the repository linked to this channel.",
    )

    # ── Helper ────────────────────────────────────────────────────────────────

    async def _get_github_client(
        self, interaction: discord.Interaction
    ) -> GitHubClient | None:
        """
        Resolve a GitHubClient scoped to the current Discord channel.

        Looks up the channel → repository link in the database.  If no link
        exists, the interaction receives an ephemeral error message and this
        method returns None so callers can exit early with a simple ``if``
        guard instead of repeating the error-handling boilerplate.

        Args:
            interaction: The Discord interaction that triggered the command.

        Returns:
            A configured GitHubClient, or None if the channel has no repo link.
        """
        channel_id = str(interaction.channel_id)

        # The session is opened synchronously; SQLite queries are fast enough
        # that running them on the event-loop thread is acceptable here.
        with self.bot.get_db_session() as db_session:
            channel_link = repository.get_channel_link(db_session, channel_id)

        if channel_link is None:
            # Guard: tell the user exactly what to do rather than just saying
            # "no link found", which would leave them guessing.
            await interaction.response.send_message(
                "No repo linked to this channel. Use `/link` first.",
                ephemeral=True,
            )
            return None

        return GitHubClient(
            personal_access_token=channel_link.github_pat,
            repo_owner=channel_link.repo_owner,
            repo_name=channel_link.repo_name,
        )

    # ── /issue list ───────────────────────────────────────────────────────────

    @issue_group.command(name="list", description="List open or closed GitHub issues.")
    @app_commands.describe(state="Filter issues by state (default: open).")
    @app_commands.choices(state=[
        app_commands.Choice(name="open", value="open"),
        app_commands.Choice(name="closed", value="closed"),
    ])
    async def list_issues(
        self,
        interaction: discord.Interaction,
        state: app_commands.Choice[str] = None,  # type: ignore[assignment]
    ) -> None:
        """
        List GitHub issues in the linked repository, filtered by state.

        Shows up to MAX_ISSUES_DISPLAYED issues in a single embed.  If more
        issues exist than the display cap, a note is appended so users know
        the list has been truncated.

        Args:
            interaction: The Discord interaction that triggered the command.
            state:       An app_commands.Choice for "open" or "closed".
                         Defaults to "open" when not provided.
        """
        # Resolve the state string early so we can use it in messages
        # regardless of whether the user passed a choice or took the default.
        resolved_state: str = state.value if state is not None else "open"

        github_client = await self._get_github_client(interaction)
        if github_client is None:
            # _get_github_client already sent an ephemeral error.
            return

        try:
            issues: list[dict] = github_client.list_issues(resolved_state)
        except ValueError as validation_error:
            # list_issues raises ValueError for bad state strings; surface it
            # clearly rather than letting an unhelpful traceback go unnoticed.
            await interaction.response.send_message(
                f"❌ Invalid request: {validation_error}", ephemeral=True
            )
            return
        except Exception as unexpected_error:
            # Broad catch: the GitHub API can fail for auth, rate-limit, or
            # network reasons outside our control.  We catch all of them here
            # so the bot never crashes on a user-facing command.
            await interaction.response.send_message(
                f"❌ GitHub API error: {unexpected_error}", ephemeral=True
            )
            return

        if not issues:
            await interaction.response.send_message(
                f"No {resolved_state} issues found.", ephemeral=True
            )
            return

        # Build a line per issue: "#42 — Fix login bug"
        repo_label = f"{github_client._repo_owner}/{github_client._repo_name}"
        displayed_issues = issues[:MAX_ISSUES_DISPLAYED]
        issue_lines = [
            f"**#{issue['number']}** — {issue['title']}"
            for issue in displayed_issues
        ]
        description = "\n".join(issue_lines)

        has_more_issues = len(issues) > MAX_ISSUES_DISPLAYED
        if has_more_issues:
            remaining_count = len(issues) - MAX_ISSUES_DISPLAYED
            description += f"\n\n_… and {remaining_count} more. Visit GitHub to see all._"

        embed = discord.Embed(
            title=f"📋 {resolved_state.title()} Issues — {repo_label}",
            description=description,
            color=discord.Color.blue(),
        )
        embed.set_footer(text=_FOOTER_TEXT)
        await interaction.response.send_message(embed=embed)

    # ── /issue view ───────────────────────────────────────────────────────────

    @issue_group.command(name="view", description="Show details for a specific issue.")
    @app_commands.describe(number="The GitHub issue number to look up.")
    async def view_issue(
        self,
        interaction: discord.Interaction,
        number: int,
    ) -> None:
        """
        Display detailed information about a single GitHub issue.

        Retrieves the issue by number and renders it as a rich embed using the
        shared format_issue_dict formatter so it matches the style of webhook
        notifications that the bot posts automatically.

        Args:
            interaction: The Discord interaction that triggered the command.
            number:      The integer issue number (e.g. 42 for issue #42).
        """
        github_client = await self._get_github_client(interaction)
        if github_client is None:
            return

        try:
            issue: dict | None = github_client.get_issue(number)
        except ValueError as validation_error:
            await interaction.response.send_message(
                f"❌ Invalid request: {validation_error}", ephemeral=True
            )
            return
        except Exception as unexpected_error:
            await interaction.response.send_message(
                f"❌ GitHub API error: {unexpected_error}", ephemeral=True
            )
            return

        if issue is None:
            await interaction.response.send_message(
                f"Issue #{number} not found.", ephemeral=True
            )
            return

        embed = format_issue_dict(issue, action="opened")
        await interaction.response.send_message(embed=embed)

    # ── /issue create ─────────────────────────────────────────────────────────

    @issue_group.command(name="create", description="Create a new GitHub issue.")
    @app_commands.describe(
        title="Short summary of the problem or feature request.",
        body="Optional longer description, steps to reproduce, or acceptance criteria.",
    )
    async def create_issue(
        self,
        interaction: discord.Interaction,
        title: str,
        body: str = "",
    ) -> None:
        """
        Create a new GitHub issue in the linked repository.

        Posts the issue via the GitHub API and responds with a formatted embed
        so the creator gets immediate confirmation of what was created and can
        follow the direct link to GitHub.

        Args:
            interaction: The Discord interaction that triggered the command.
            title:       Required one-line summary for the issue title.
            body:        Optional markdown body with additional context.
        """
        github_client = await self._get_github_client(interaction)
        if github_client is None:
            return

        try:
            # Pass None instead of empty string when no body was provided so
            # the GitHub API creates the issue without a blank body field.
            issue_body: str | None = body if body else None
            created_issue: dict = github_client.create_issue(title, issue_body)
        except ValueError as validation_error:
            await interaction.response.send_message(
                f"❌ Invalid request: {validation_error}", ephemeral=True
            )
            return
        except Exception as unexpected_error:
            await interaction.response.send_message(
                f"❌ GitHub API error: {unexpected_error}", ephemeral=True
            )
            return

        embed = format_issue_dict(created_issue, action="created")
        await interaction.response.send_message(embed=embed)

    # ── /issue comment ────────────────────────────────────────────────────────

    @issue_group.command(name="comment", description="Add a comment to an existing issue.")
    @app_commands.describe(
        number="The issue number to comment on.",
        text="The comment body to post.",
    )
    async def comment_issue(
        self,
        interaction: discord.Interaction,
        number: int,
        text: str,
    ) -> None:
        """
        Post a comment on an existing GitHub issue.

        Sends a success acknowledgement as an ephemeral message so the channel
        is not cluttered — only the command invoker needs to know the comment
        was accepted.

        Args:
            interaction: The Discord interaction that triggered the command.
            number:      The integer issue number to comment on.
            text:        The markdown comment body to post.
        """
        github_client = await self._get_github_client(interaction)
        if github_client is None:
            return

        try:
            github_client.add_issue_comment(number, text)
        except ValueError as validation_error:
            await interaction.response.send_message(
                f"❌ Invalid request: {validation_error}", ephemeral=True
            )
            return
        except Exception as unexpected_error:
            await interaction.response.send_message(
                f"❌ GitHub API error: {unexpected_error}", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"✅ Comment added to issue #{number}.", ephemeral=True
        )

    # ── /issue close ──────────────────────────────────────────────────────────

    @issue_group.command(name="close", description="Close an open GitHub issue.")
    @app_commands.describe(number="The issue number to close.")
    async def close_issue(
        self,
        interaction: discord.Interaction,
        number: int,
    ) -> None:
        """
        Close an open GitHub issue and display its updated state in an embed.

        Uses format_issue_dict with action="closed" so the embed clearly
        indicates the issue has been resolved, matching the visual language
        used by automated webhook notifications.

        Args:
            interaction: The Discord interaction that triggered the command.
            number:      The integer issue number to close.
        """
        github_client = await self._get_github_client(interaction)
        if github_client is None:
            return

        try:
            closed_issue: dict = github_client.close_issue(number)
        except ValueError as validation_error:
            await interaction.response.send_message(
                f"❌ Invalid request: {validation_error}", ephemeral=True
            )
            return
        except Exception as unexpected_error:
            await interaction.response.send_message(
                f"❌ GitHub API error: {unexpected_error}", ephemeral=True
            )
            return

        embed = format_issue_dict(closed_issue, action="closed")
        await interaction.response.send_message(embed=embed)


# ── Cog setup ─────────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot) -> None:
    """
    Entry point called by discord.py when this extension is loaded.

    discord.py's load_extension() convention requires a module-level async
    setup() function that adds the cog to the bot.  This is the only place
    where the cog is instantiated so there is never more than one IssueCommands
    registered at a time.

    Args:
        bot: The running bot instance that is loading this extension.
    """
    await bot.add_cog(IssueCommands(bot))
