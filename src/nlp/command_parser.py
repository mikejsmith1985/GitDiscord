"""
NLP command parser and message handler for GitDiscord.

Parses natural-language Discord messages into structured ParsedCommand objects
and dispatches them to the GitHub API, translating results into Discord embed
responses.  This module is the single implementation point for the NLP channel
feature — any channel marked as NLP-enabled routes every message through here.
"""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Generator

import discord
from discord.ext import commands
from sqlalchemy.orm import Session, sessionmaker

from src.db import repository
from src.formatters.discord_embeds import format_issue_dict
from src.github import GitHubClient


logger = logging.getLogger(__name__)


# ── Action string constants ───────────────────────────────────────────────────

# Each constant names one possible ParsedCommand.action value so call sites
# and tests reference symbols instead of bare strings, preventing typo bugs.
ACTION_LIST = "list"
ACTION_VIEW = "view"
ACTION_CREATE = "create"
ACTION_COMMENT = "comment"
ACTION_CLOSE = "close"
ACTION_UNKNOWN = "unknown"

# State-filter values used when listing issues.
STATE_OPEN = "open"
STATE_CLOSED = "closed"

# Emoji used as a silent "I didn't understand" reaction — avoids cluttering
# the channel with text replies for messages the bot doesn't recognise.
EMOJI_UNKNOWN_COMMAND = "❓"

# Maximum number of characters shown for a comment body preview in embeds.
MAX_COMMENT_PREVIEW_CHARS = 300


# ── Regex patterns ────────────────────────────────────────────────────────────

# Matches list-style commands.  Two grammatical forms are supported:
#   1. (list|show) [open|closed] issues  — explicit verb-first sentences
#   2. (open|closed) issues              — adjective-as-verb shorthand
# Named groups modifier_a / modifier_b capture the state adjective from each
# form; the caller checks whichever is non-None to determine state_filter.
# The trailing "s?" makes both "issue" and "issues" valid.
PATTERN_LIST_ISSUES = re.compile(
    r"^(?:(?:list|show)\s+(?:(?P<modifier_a>open|closed)\s+)?issues?"
    r"|(?P<modifier_b>open|closed)\s+issues?)$",
    re.IGNORECASE,
)

# Matches view/show commands for a specific issue number.
# "show|view" is an optional prefix so bare "issue #5" and shorthand "#5" work.
# The # symbol is optional to accommodate both "issue 5" and "issue #5".
# Two named groups (issue_num_long, issue_num_short) capture the number from
# the "issue N" and standalone "#N" forms respectively.
PATTERN_VIEW_ISSUE = re.compile(
    r"^(?:(?:show|view)\s+)?issue\s+#?(?P<issue_num_long>\d+)$"
    r"|^#(?P<issue_num_short>\d+)$",
    re.IGNORECASE,
)

# Matches create commands delimited by a colon after the action keyword.
# Three verb choices (create/new/open) reflect how developers commonly phrase
# the action; "open issue" mirrors the button label GitHub itself uses.
# DOTALL allows the title_and_body group to span newlines so users can type a
# multi-line body without any special escaping.
PATTERN_CREATE_ISSUE = re.compile(
    r"^(?:create|new|open)\s+issue:\s*(?P<title_and_body>.+)$",
    re.IGNORECASE | re.DOTALL,
)

# Matches comment commands targeting a specific issue number.
# Both "on" and "issue" are optional filler words so the terse form
# "comment #5: text" and the natural form "comment on issue #5: text" match.
# DOTALL lets comment_text span newlines for multi-paragraph comments.
PATTERN_COMMENT_ON_ISSUE = re.compile(
    r"^comment(?:\s+on)?(?:\s+issue)?\s+#?(?P<issue_num>\d+):\s*(?P<comment_text>.+)$",
    re.IGNORECASE | re.DOTALL,
)

# Matches close/resolve commands.  "resolve" is included as a synonym because
# some teams describe completing work as "resolving" rather than "closing".
# "issue" is an optional filler word — "close #5" is as readable as "close issue #5".
PATTERN_CLOSE_ISSUE = re.compile(
    r"^(?:close|resolve)\s+(?:issue\s+)?#?(?P<issue_num>\d+)$",
    re.IGNORECASE,
)

# Matches issue references embedded inside normal conversation text.
# Examples:
#   - "gh issue #123"
#   - "github issue 123"
#   - "please reference issue #123 in this thread"
PATTERN_INLINE_ISSUE_REFERENCE = re.compile(
    r"(?:\b(?:gh|github)\s+issue\s+#?(?P<issue_num_prefixed>\d+)\b)"
    r"|(?:\bissue\s+#(?P<issue_num_plain>\d+)\b)",
    re.IGNORECASE,
)


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class ParsedCommand:
    """
    Represents a parsed natural-language command extracted from a Discord message.

    All fields that are not applicable to a given action default to None so
    callers only need to inspect the fields relevant to the detected action.
    state_filter defaults to STATE_OPEN because listing open issues is the
    most common operation and an explicit "closed" keyword is always required.
    """

    action: str
    """One of ACTION_LIST, ACTION_VIEW, ACTION_CREATE, ACTION_COMMENT, ACTION_CLOSE, or ACTION_UNKNOWN."""

    issue_number: int | None = None
    """The GitHub issue number extracted from the message (view, comment, close actions)."""

    title: str | None = None
    """The issue title extracted after the colon in a create command."""

    body: str | None = None
    """Everything after the first newline in a create command (optional markdown body)."""

    comment_text: str | None = None
    """The comment body extracted after the colon in a comment command."""

    state_filter: str = STATE_OPEN
    """'open' or 'closed' — the issue state filter used when listing issues."""


# ── Pure parser ───────────────────────────────────────────────────────────────

def parse_command(text: str) -> ParsedCommand:
    """
    Parse a natural-language string into a structured ParsedCommand.

    This is a pure function with no side effects and no I/O.  All regex
    matching is case-insensitive.  Multi-line input is fully supported for
    create and comment commands.

    Patterns are tried in a deliberate order — close before list — to prevent
    ambiguous inputs from resolving to the wrong action.

    Args:
        text: The raw message content from a Discord channel.

    Returns:
        A ParsedCommand whose action field names the detected intent.
        Returns action=ACTION_UNKNOWN when no pattern matches.
    """
    stripped_text = text.strip()

    # ── List issues ──────────────────────────────────────────────────────────
    list_match = PATTERN_LIST_ISSUES.match(stripped_text)
    if list_match:
        # Either modifier group captures the state adjective; the other is None.
        raw_modifier = (
            list_match.group("modifier_a") or list_match.group("modifier_b") or ""
        )
        state_filter = (
            STATE_CLOSED if raw_modifier.lower() == STATE_CLOSED else STATE_OPEN
        )
        return ParsedCommand(action=ACTION_LIST, state_filter=state_filter)

    # ── View specific issue ──────────────────────────────────────────────────
    view_match = PATTERN_VIEW_ISSUE.match(stripped_text)
    if view_match:
        # One of the two groups captures the number depending on which form was used.
        raw_number = (
            view_match.group("issue_num_long") or view_match.group("issue_num_short")
        )
        return ParsedCommand(action=ACTION_VIEW, issue_number=int(raw_number))

    # ── Create issue ─────────────────────────────────────────────────────────
    create_match = PATTERN_CREATE_ISSUE.match(stripped_text)
    if create_match:
        title_and_body = create_match.group("title_and_body")
        # Split on the first newline: everything before is the title,
        # everything after is an optional multi-line markdown body.
        split_content = title_and_body.split("\n", 1)
        extracted_title = split_content[0].strip()
        extracted_body = split_content[1].strip() if len(split_content) > 1 else None
        return ParsedCommand(
            action=ACTION_CREATE,
            title=extracted_title,
            body=extracted_body,
        )

    # ── Comment on issue ─────────────────────────────────────────────────────
    comment_match = PATTERN_COMMENT_ON_ISSUE.match(stripped_text)
    if comment_match:
        return ParsedCommand(
            action=ACTION_COMMENT,
            issue_number=int(comment_match.group("issue_num")),
            comment_text=comment_match.group("comment_text").strip(),
        )

    # ── Close issue ──────────────────────────────────────────────────────────
    close_match = PATTERN_CLOSE_ISSUE.match(stripped_text)
    if close_match:
        return ParsedCommand(
            action=ACTION_CLOSE,
            issue_number=int(close_match.group("issue_num")),
        )

    # ── Inline issue reference inside free text ──────────────────────────────
    inline_issue_reference_match = PATTERN_INLINE_ISSUE_REFERENCE.search(stripped_text)
    if inline_issue_reference_match:
        raw_issue_number = (
            inline_issue_reference_match.group("issue_num_prefixed")
            or inline_issue_reference_match.group("issue_num_plain")
        )
        return ParsedCommand(
            action=ACTION_VIEW,
            issue_number=int(raw_issue_number),
        )

    # ── No pattern matched ────────────────────────────────────────────────────
    return ParsedCommand(action=ACTION_UNKNOWN)


# ── Module-level embed helpers ────────────────────────────────────────────────

def _normalize_issue_dict_for_embed(issue_dict: dict) -> dict:
    """
    Adapt a GitHubClient issue dict to the shape expected by format_issue_dict.

    GitHubClient._issue_to_dict stores the URL under "url" and labels as a flat
    list of strings.  The Discord formatter (format_issue_dict) was written for
    webhook payloads that use "html_url" and represent each label as a dict with
    a "name" key.  This function bridges the two representations so the formatter
    can be reused without modification.

    Args:
        issue_dict: A dict returned by GitHubClient (get_issue, create_issue, etc.).

    Returns:
        A new dict compatible with format_issue_dict, leaving the original unchanged.
    """
    normalized = dict(issue_dict)

    # Map "url" → "html_url" so the embed includes a clickable link.
    if "html_url" not in normalized and "url" in normalized:
        normalized["html_url"] = normalized["url"]

    # Convert flat string labels ["bug", "help wanted"] to the dict form
    # [{"name": "bug"}, {"name": "help wanted"}] that format_issue_dict expects.
    raw_labels = normalized.get("labels", []) or []
    if raw_labels and isinstance(raw_labels[0], str):
        normalized["labels"] = [{"name": label_name} for label_name in raw_labels]

    return normalized


def _build_issues_list_embed(
    issues: list[dict], state_filter: str
) -> discord.Embed:
    """
    Build a Discord embed that summarises a list of GitHub issues.

    Creates a single embed with each issue on its own line so users can scan
    the list at a glance without opening GitHub.

    Args:
        issues:       Issue dicts as returned by GitHubClient.list_issues().
        state_filter: "open" or "closed" — shown in the embed title for context.

    Returns:
        A discord.Embed listing all issues, or a "no issues found" message.
    """
    embed_color = (
        discord.Color.gold() if state_filter == STATE_OPEN else discord.Color.greyple()
    )
    embed_title = f"📋 {state_filter.capitalize()} Issues"

    if not issues:
        empty_embed = discord.Embed(
            title=embed_title,
            description=f"No {state_filter} issues found.",
            color=embed_color,
        )
        empty_embed.set_footer(text="GitDiscord")
        return empty_embed

    # Build one line per issue: "#N — Title" with the number linked to GitHub.
    description_lines: list[str] = []
    for issue_dict in issues:
        issue_number = issue_dict.get("number", "?")
        issue_title = issue_dict.get("title", "Untitled")
        # GitHubClient uses "url"; webhook payloads use "html_url" — check both.
        issue_url = issue_dict.get("url") or issue_dict.get("html_url", "")

        if issue_url:
            description_lines.append(
                f"[#{issue_number}]({issue_url}) — {issue_title}"
            )
        else:
            description_lines.append(f"#{issue_number} — {issue_title}")

    issues_embed = discord.Embed(
        title=embed_title,
        description="\n".join(description_lines),
        color=embed_color,
    )
    issues_embed.set_footer(text="GitDiscord")
    return issues_embed


def _build_comment_added_embed(
    issue_number: int, comment_dict: dict
) -> discord.Embed:
    """
    Build a Discord embed confirming a comment was successfully posted.

    Args:
        issue_number: The GitHub issue number the comment was added to.
        comment_dict: The comment dict returned by GitHubClient.add_issue_comment().

    Returns:
        A discord.Embed with the author, issue reference, and a body preview.
    """
    comment_body = comment_dict.get("body", "")
    comment_url = comment_dict.get("url", "")
    author_login = comment_dict.get("user_login", "unknown")

    body_preview = (
        comment_body[:MAX_COMMENT_PREVIEW_CHARS] + "…"
        if len(comment_body) > MAX_COMMENT_PREVIEW_CHARS
        else comment_body
    )

    description_lines = [
        f"**By:** {author_login}",
        f"**On:** Issue #{issue_number}",
    ]
    if body_preview:
        description_lines += ["", body_preview]

    comment_embed = discord.Embed(
        title=f"💬 Comment added to Issue #{issue_number}",
        description="\n".join(description_lines),
        color=discord.Color.blurple(),
        url=comment_url or None,
    )
    comment_embed.set_footer(text="GitDiscord")
    return comment_embed


# ── Message handler ───────────────────────────────────────────────────────────

class NlpMessageHandler:
    """
    Async Discord message handler that routes natural-language commands to GitHub.

    Attached to the bot's on_message event, this handler checks whether the
    receiving channel is NLP-enabled and, if so, parses the message text and
    dispatches the appropriate GitHubClient operation, then replies with a
    formatted Discord embed.
    """

    def __init__(
        self,
        db_session_factory: sessionmaker,
        discord_bot: commands.Bot,
    ) -> None:
        """
        Initialise the handler with the database factory and bot reference.

        Args:
            db_session_factory: SQLAlchemy sessionmaker for opening DB sessions.
                                 Stored so each message opens its own short-lived
                                 session, preventing cross-request state leakage.
            discord_bot:        The running GitDiscordBot instance.  Stored for
                                 future use (e.g., logging, guild lookups) without
                                 coupling this class to bot internals today.
        """
        self._db_session_factory: sessionmaker = db_session_factory
        self._bot: commands.Bot = discord_bot

    # ── Public entry point ────────────────────────────────────────────────────

    async def handle_message(self, message: discord.Message) -> None:
        """
        Process a Discord message received in a guild channel.

        Steps:
          1. Ignore messages sent by bots (prevents infinite loops).
          2. Check the DB to see if this channel has NLP parsing enabled.
          3. If yes, look up the channel's linked GitHub repository credentials.
          4. Parse the message, dispatch to GitHub, and reply with an embed.

        Args:
            message: The discord.Message received from the gateway event.
        """
        # Bot messages must be silently ignored to prevent the handler from
        # reacting to its own output and entering an infinite response loop.
        if message.author.bot:
            return

        channel_id = str(message.channel.id)

        # Open one session for both the NLP check and the link lookup so we
        # make a single round-trip to the database per message.
        with self._open_db_session() as db_session:
            is_nlp_enabled = repository.is_nlp_channel(db_session, channel_id)
            if not is_nlp_enabled:
                # Silently ignore — this channel has not opted in to NLP parsing.
                return
            channel_link = repository.get_channel_link(db_session, channel_id)

        if channel_link is None:
            # The channel is marked NLP-enabled but has no repository link.
            # Reacting with ❓ signals misconfiguration without cluttering the
            # channel with a text reply for every unlinked message.
            await message.add_reaction(EMOJI_UNKNOWN_COMMAND)
            logger.warning(
                "NLP channel %s has no repository link configured; ignoring message.",
                channel_id,
            )
            return

        try:
            github_client = GitHubClient(
                personal_access_token=channel_link.github_pat,
                repo_owner=channel_link.repo_owner,
                repo_name=channel_link.repo_name,
            )
        except Exception as client_creation_error:
            logger.exception(
                "Failed to create GitHubClient for channel %s: %s",
                channel_id,
                client_creation_error,
            )
            await message.reply(
                f"⚠️ GitHub connection failed: {client_creation_error}"
            )
            return

        parsed_command = parse_command(message.content)
        await self._dispatch_command(message, parsed_command, github_client)

    # ── Command dispatch ──────────────────────────────────────────────────────

    async def _dispatch_command(
        self,
        message: discord.Message,
        parsed_command: ParsedCommand,
        github_client: GitHubClient,
    ) -> None:
        """
        Route a ParsedCommand to its action handler and send the response.

        All action handlers are wrapped in a single try/except so any GitHub
        API failure (rate limit, bad credentials, deleted issue) produces a
        readable error reply rather than a silent crash or unhandled exception.

        Args:
            message:        The original Discord message (used for replies/reactions).
            parsed_command: The parsed intent and extracted fields.
            github_client:  An authenticated GitHubClient for this channel's repo.
        """
        # Map each known action to its handler coroutine so the dispatch logic
        # stays readable as new actions are added in future iterations.
        action_handler_map = {
            ACTION_LIST:    self._handle_list,
            ACTION_VIEW:    self._handle_view,
            ACTION_CREATE:  self._handle_create,
            ACTION_COMMENT: self._handle_comment,
            ACTION_CLOSE:   self._handle_close,
        }

        handler_coroutine = action_handler_map.get(parsed_command.action)

        if handler_coroutine is None:
            # Action is "unknown" — react silently so the user knows the bot
            # received their message but didn't recognise the intent.
            await message.add_reaction(EMOJI_UNKNOWN_COMMAND)
            return

        try:
            await handler_coroutine(message, parsed_command, github_client)
        except Exception as handler_error:
            logger.exception(
                "Error handling NLP '%s' command in channel %s: %s",
                parsed_command.action,
                message.channel.id,
                handler_error,
            )
            await message.reply(f"⚠️ Command failed: {handler_error}")

    # ── Action handlers ───────────────────────────────────────────────────────

    async def _handle_list(
        self,
        message: discord.Message,
        parsed_command: ParsedCommand,
        github_client: GitHubClient,
    ) -> None:
        """Fetch and display the current list of issues from the linked repository."""
        issues = github_client.list_issues(state=parsed_command.state_filter)
        response_embed = _build_issues_list_embed(
            issues, state_filter=parsed_command.state_filter
        )
        await message.reply(embed=response_embed)

    async def _handle_view(
        self,
        message: discord.Message,
        parsed_command: ParsedCommand,
        github_client: GitHubClient,
    ) -> None:
        """Fetch and display a single issue by its number."""
        issue_dict = github_client.get_issue(parsed_command.issue_number)

        if issue_dict is None:
            await message.reply(
                f"❌ Issue #{parsed_command.issue_number} was not found."
            )
            return

        response_embed = format_issue_dict(
            _normalize_issue_dict_for_embed(issue_dict), action="viewed"
        )
        await message.reply(embed=response_embed)

    async def _handle_create(
        self,
        message: discord.Message,
        parsed_command: ParsedCommand,
        github_client: GitHubClient,
    ) -> None:
        """Create a new GitHub issue and post the resulting issue as an embed."""
        new_issue_dict = github_client.create_issue(
            title=parsed_command.title,
            body=parsed_command.body or "",
        )
        response_embed = format_issue_dict(
            _normalize_issue_dict_for_embed(new_issue_dict), action="created"
        )
        await message.reply(embed=response_embed)

    async def _handle_comment(
        self,
        message: discord.Message,
        parsed_command: ParsedCommand,
        github_client: GitHubClient,
    ) -> None:
        """Post a comment on an existing issue and confirm with an embed."""
        comment_dict = github_client.add_issue_comment(
            issue_number=parsed_command.issue_number,
            comment_text=parsed_command.comment_text,
        )
        response_embed = _build_comment_added_embed(
            issue_number=parsed_command.issue_number,
            comment_dict=comment_dict,
        )
        await message.reply(embed=response_embed)

    async def _handle_close(
        self,
        message: discord.Message,
        parsed_command: ParsedCommand,
        github_client: GitHubClient,
    ) -> None:
        """Close a GitHub issue and display the updated issue state as an embed."""
        closed_issue_dict = github_client.close_issue(parsed_command.issue_number)
        response_embed = format_issue_dict(
            _normalize_issue_dict_for_embed(closed_issue_dict), action="closed"
        )
        await message.reply(embed=response_embed)

    # ── Database session helper ───────────────────────────────────────────────

    @contextmanager
    def _open_db_session(self) -> Generator[Session, None, None]:
        """
        Open a short-lived SQLAlchemy session for a single database operation.

        Commits automatically on success and rolls back on any exception, keeping
        the database consistent without requiring callers to manage transactions.

        Yields:
            An open SQLAlchemy Session ready for queries and mutations.

        Raises:
            Re-raises any exception thrown inside the ``with`` block after
            rolling back, so the caller sees the original error.
        """
        db_session: Session = self._db_session_factory()
        try:
            yield db_session
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise
        finally:
            db_session.close()
