"""
issue_commands.py — Discord slash-command cog for GitHub issue management.

Provides the /issue command group, letting users list, view, create, comment
on, close, and draft issues from Discord thread discussions directly from a
linked channel.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from src.db import repository
from src.formatters.discord_embeds import format_issue_dict
from src.github import GitHubClient

logger = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────────────

# Discord embeds can hold a lot of text, but dumping hundreds of issues into one
# message becomes unreadable.  Cap the list so it stays a quick-glance summary.
MAX_ISSUES_DISPLAYED = 10
MAX_THREAD_MESSAGES_TO_COLLECT = 50
MAX_DISCUSSION_TITLE_CHARS = 100
MAX_DISCUSSION_MESSAGE_CHARS = 600

# Shared footer text to keep all bot-generated embeds visually consistent.
_FOOTER_TEXT = "GitDiscord"
GITHUB_COMMAND_SETUP_FAILURE_PREFIX = "❌ GitHub command setup failed:"


def _normalize_discussion_text(raw_text: str) -> str:
    """Flatten a Discord message body into a single readable line."""
    normalized_lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    return " ".join(normalized_lines)


def _format_discussion_message(message: discord.Message) -> str:
    """Render one Discord message as a bullet suitable for a GitHub issue draft."""
    author_name = getattr(message.author, "display_name", None) or getattr(
        message.author, "name", "unknown"
    )
    normalized_content = _normalize_discussion_text(message.content or "")
    if len(normalized_content) > MAX_DISCUSSION_MESSAGE_CHARS:
        normalized_content = normalized_content[: MAX_DISCUSSION_MESSAGE_CHARS - 1] + "…"
    return f"- **{author_name}**: {normalized_content or '(no text content)'}"


def _build_discussion_issue_title(
    discussion_messages: list[discord.Message],
    thread_name: str,
) -> str:
    """Derive a presentable issue title from the discussion context."""
    if discussion_messages:
        first_message_text = _normalize_discussion_text(discussion_messages[0].content)
        title_candidate = first_message_text or thread_name
    else:
        title_candidate = thread_name

    cleaned_title = title_candidate.strip() or "Discord discussion"
    return cleaned_title[:MAX_DISCUSSION_TITLE_CHARS]


def _build_discussion_issue_body(
    discussion_messages: list[discord.Message],
    thread_name: str,
) -> str:
    """Render the collected thread messages into a GitHub issue body draft."""
    body_lines = [
        f"Captured from Discord thread: **{thread_name}**",
        "",
        "## Discussion",
        "",
    ]

    body_lines.extend(
        _format_discussion_message(discussion_message)
        for discussion_message in discussion_messages
    )

    body_lines.extend(
        [
            "",
            "## Suggested next steps",
            "- Review the draft title and body before publishing.",
            "- Add acceptance criteria if the thread did not already include them.",
        ]
    )
    return "\n".join(body_lines)


# ── Cog ───────────────────────────────────────────────────────────────────────

class IssueCommands(commands.Cog):
    """
    Discord cog that registers the /issue slash-command group.

    Each subcommand maps to a GitHubClient method so that Discord users can
    interact with a linked repository's issues without leaving Discord.  The
    thread-draft command collects recent discussion messages first so users can
    turn a conversation into an issue without manual copy/paste.
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
        linked_repo_owner: str | None = None
        linked_repo_name: str | None = None

        # The session is opened synchronously; SQLite queries are fast enough
        # that running them on the event-loop thread is acceptable here.
        with self.bot.get_db_session() as db_session:
            channel_link = repository.get_channel_link(db_session, channel_id)
            if channel_link is not None:
                # Copy scalar values before session close so SQLAlchemy does not
                # attempt detached-object refreshes during command execution.
                linked_repo_owner = channel_link.repo_owner
                linked_repo_name = channel_link.repo_name

        if linked_repo_owner is None or linked_repo_name is None:
            # Guard: tell the user exactly what to do rather than just saying
            # "no link found", which would leave them guessing.
            await interaction.response.send_message(
                "No repo linked to this channel. Use `/link` first.",
                ephemeral=True,
            )
            return None

        if not self.bot.has_github_app_configuration():
            await interaction.response.send_message(
                "GitHub App credentials are not configured. Set "
                "`GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, and "
                "`GITHUB_APP_INSTALLATION_ID` before using issue commands.",
                ephemeral=True,
            )
            return None

        try:
            return GitHubClient(
                github_app_id=self.bot.github_app_id,
                github_app_private_key=self.bot.github_app_private_key,
                github_app_installation_id=self.bot.github_app_installation_id,
                repo_owner=linked_repo_owner,
                repo_name=linked_repo_name,
            )
        except Exception as github_authentication_error:
            logger.exception(
                "Failed to create GitHub client for channel_id=%s",
                channel_id,
            )
            await interaction.response.send_message(
                f"{GITHUB_COMMAND_SETUP_FAILURE_PREFIX} {github_authentication_error}",
                ephemeral=True,
            )
            return None

    async def _collect_discussion_messages(self, channel_history_source) -> list[discord.Message]:
        """Collect recent Discord messages from a thread or text channel."""
        discussion_messages: list[discord.Message] = []
        async for history_message in channel_history_source.history(
            limit=MAX_THREAD_MESSAGES_TO_COLLECT,
            oldest_first=True,
        ):
            if history_message.author.bot:
                continue

            normalized_content = _normalize_discussion_text(history_message.content or "")
            if not normalized_content and not history_message.attachments:
                continue

            discussion_messages.append(history_message)

        return discussion_messages

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

    # ── /issue create-thread ───────────────────────────────────────────────────

    @issue_group.command(
        name="create-thread",
        description="Create a GitHub issue from the current thread discussion.",
    )
    async def create_issue_from_thread(self, interaction: discord.Interaction) -> None:
        """
        Collect recent thread messages and turn them into a GitHub issue draft.

        This command is intentionally thread-centric so users can group the
        discussion they want to turn into an issue without copy/pasting every
        message into a slash-command body.
        """
        github_client = await self._get_github_client(interaction)
        if github_client is None:
            return

        discussion_source = interaction.channel
        if discussion_source is None or not hasattr(discussion_source, "history"):
            await interaction.response.send_message(
                "Run this command inside a thread or channel with message history.",
                ephemeral=True,
            )
            return

        discussion_messages = await self._collect_discussion_messages(discussion_source)
        if not discussion_messages:
            await interaction.response.send_message(
                "No non-bot messages were found to turn into an issue.",
                ephemeral=True,
            )
            return

        thread_name = getattr(discussion_source, "name", "Discord discussion")
        issue_title = _build_discussion_issue_title(discussion_messages, thread_name)
        issue_body = _build_discussion_issue_body(discussion_messages, thread_name)

        try:
            created_issue = github_client.create_issue(issue_title, issue_body)
        except ValueError as validation_error:
            await interaction.response.send_message(
                f"❌ Invalid request: {validation_error}",
                ephemeral=True,
            )
            return
        except Exception as unexpected_error:
            await interaction.response.send_message(
                f"❌ GitHub API error: {unexpected_error}",
                ephemeral=True,
            )
            return

        confirmation_embed = format_issue_dict(created_issue, action="created")
        confirmation_embed.set_footer(
            text=f"Drafted from {len(discussion_messages)} thread message(s)"
        )
        await interaction.response.send_message(embed=confirmation_embed)

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
