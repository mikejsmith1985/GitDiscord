"""Tests for src/main.py — entry point wiring and PORT override logic."""

import os
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.client import GitDiscordBot
from src.bot.commands.issue_commands import (
    GITHUB_COMMAND_SETUP_FAILURE_PREFIX,
    IssueCommands,
)
from src.bot.commands.link_commands import LinkCommands
from src.nlp.command_parser import NlpMessageHandler


def test_gitdiscord_bot_disables_message_content_intent_by_default():
    """Bot startup must not require Discord privileged intents for slash-command usage."""
    bot = GitDiscordBot(db_session_factory=MagicMock())

    assert bot.intents.message_content is False


def test_gitdiscord_bot_can_enable_message_content_intent_for_nlp_mode():
    """NLP deployments can opt into message content after enabling it in Discord."""
    bot = GitDiscordBot(
        db_session_factory=MagicMock(),
        should_enable_message_content_intent=True,
    )

    assert bot.intents.message_content is True


async def test_gitdiscord_bot_syncs_slash_commands_to_connected_guilds(monkeypatch):
    """on_ready() must guild-sync commands so Discord shows them immediately."""
    bot = GitDiscordBot(db_session_factory=MagicMock())
    fake_guild = MagicMock()
    fake_guild.id = 123456789
    fake_user = MagicMock()
    fake_user.id = 987654321

    monkeypatch.setattr(type(bot), "guilds", property(lambda _bot_instance: [fake_guild]))
    monkeypatch.setattr(type(bot), "user", property(lambda _bot_instance: fake_user))
    bot.tree.copy_global_to = MagicMock()
    synced_link_command = MagicMock()
    synced_link_command.name = "link"
    synced_status_command = MagicMock()
    synced_status_command.name = "status"
    bot.tree.sync = AsyncMock(return_value=[synced_link_command, synced_status_command])

    await bot.on_ready()
    await bot.on_ready()

    bot.tree.copy_global_to.assert_called_once_with(guild=fake_guild)
    bot.tree.sync.assert_awaited_once_with(guild=fake_guild)


def test_gitdiscord_bot_reports_loaded_application_command_names():
    """Startup diagnostics should list local slash commands before Discord sync."""
    bot = GitDiscordBot(db_session_factory=MagicMock())
    fake_link_command = MagicMock()
    fake_link_command.name = "link"
    fake_status_command = MagicMock()
    fake_status_command.name = "status"
    bot.tree.get_commands = MagicMock(return_value=[fake_status_command, fake_link_command])

    assert bot._get_loaded_application_command_names() == ["link", "status"]


def test_railway_port_env_var_overrides_settings_webhook_port(monkeypatch):
    """When Railway injects PORT, main() must bind uvicorn to that port, not webhook_port."""
    monkeypatch.setenv("PORT", "9000")

    # The PORT value should win over settings.webhook_port (8080 default)
    railway_port = int(os.environ.get("PORT", 8080))
    assert railway_port == 9000


def test_fallback_to_settings_webhook_port_when_port_not_set(monkeypatch):
    """When PORT is absent, main() must fall back to settings.webhook_port."""
    monkeypatch.delenv("PORT", raising=False)

    fallback_port = int(os.environ.get("PORT", 8080))
    assert fallback_port == 8080


@patch("src.main.get_settings")
@patch("src.main.get_engine")
@patch("src.main.create_all_tables")
@patch("src.main.sessionmaker")
@patch("src.main.GitDiscordBot")
@patch("src.main.create_webhook_app")
@patch("src.main.uvicorn.Server")
@patch("src.main.uvicorn.Config")
@patch("src.main.asyncio.gather", new_callable=AsyncMock)
async def test_main_wires_bot_and_webhook_app_together(
    mock_gather,
    mock_uvicorn_config,
    mock_uvicorn_server,
    mock_create_webhook_app,
    mock_discord_bot_class,
    mock_sessionmaker,
    mock_create_all_tables,
    mock_get_engine,
    mock_get_settings,
    monkeypatch,
):
    """main() must pass the same bot instance to create_webhook_app and bot.start()."""
    monkeypatch.delenv("PORT", raising=False)

    fake_settings = MagicMock()
    fake_settings.log_level = "INFO"
    fake_settings.database_path = "./test.db"
    fake_settings.discord_bot_token = "tok"
    fake_settings.webhook_port = 8080
    fake_settings.enable_message_content_intent = False
    fake_settings.github_app_id = "1234"
    fake_settings.github_app_private_key = "-----BEGIN PRIVATE KEY-----test-----END PRIVATE KEY-----"
    fake_settings.github_app_installation_id = "5678"
    mock_get_settings.return_value = fake_settings

    fake_bot_instance = MagicMock()
    fake_bot_instance.start = AsyncMock()
    mock_discord_bot_class.return_value = fake_bot_instance

    fake_server_instance = MagicMock()
    fake_server_instance.serve = AsyncMock()
    mock_uvicorn_server.return_value = fake_server_instance

    from src.main import main
    await main()

    # The same bot instance must be forwarded to the webhook app factory
    mock_discord_bot_class.assert_called_once_with(
        db_session_factory=mock_sessionmaker.return_value,
        should_enable_message_content_intent=False,
        github_app_id="1234",
        github_app_private_key="-----BEGIN PRIVATE KEY-----test-----END PRIVATE KEY-----",
        github_app_installation_id="5678",
    )
    mock_create_webhook_app.assert_called_once()
    call_kwargs = mock_create_webhook_app.call_args.kwargs
    assert call_kwargs["discord_bot"] is fake_bot_instance
    mock_sessionmaker.assert_called_once_with(
        bind=mock_get_engine.return_value,
        expire_on_commit=False,
    )


class FakeCommandBot:
    """Minimal bot test double for command-cog tests."""

    def __init__(self) -> None:
        self.github_app_id = "123"
        self.github_app_private_key = "pem"
        self.github_app_installation_id = "456"

    def has_github_app_configuration(self) -> bool:
        """Return true so command handlers continue to GitHub client creation."""
        return True

    @contextmanager
    def get_db_session(self):
        """Yield a throwaway session object compatible with cog expectations."""
        yield MagicMock()


class _AsyncHistoryIterator:
    """Simple async iterator for simulating Discord channel history in tests."""

    def __init__(self, items: list[MagicMock]) -> None:
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration as stop_iteration:
            raise StopAsyncIteration from stop_iteration


def _make_discussion_message(
    author_name: str,
    content: str,
    is_bot: bool = False,
) -> MagicMock:
    """Create a lightweight Discord message double for thread collection tests."""
    message = MagicMock()
    message.content = content
    message.attachments = []
    message.author = MagicMock()
    message.author.bot = is_bot
    message.author.display_name = author_name
    message.author.name = author_name
    return message


@pytest.mark.asyncio
async def test_get_github_client_returns_error_message_when_authentication_fails():
    """IssueCommands should respond ephemerally when GitHub client creation fails."""
    fake_command_bot = FakeCommandBot()
    issue_commands = IssueCommands(fake_command_bot)
    interaction = MagicMock()
    interaction.channel_id = 123456789
    interaction.response.send_message = AsyncMock()

    with patch(
        "src.bot.commands.issue_commands.repository.get_channel_link",
        return_value=SimpleNamespace(repo_owner="owner", repo_name="repo"),
    ), patch(
        "src.bot.commands.issue_commands.GitHubClient",
        side_effect=RuntimeError("invalid app credentials"),
    ):
        github_client = await issue_commands._get_github_client(interaction)

    assert github_client is None
    interaction.response.send_message.assert_awaited_once()
    sent_message_text = interaction.response.send_message.await_args.args[0]
    assert GITHUB_COMMAND_SETUP_FAILURE_PREFIX in sent_message_text
    assert "invalid app credentials" in sent_message_text
    assert interaction.response.send_message.await_args.kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_link_command_persists_guild_and_channel_ids_as_strings():
    """LinkCommands should persist Discord IDs as strings for stable lookups."""
    fake_command_bot = FakeCommandBot()
    link_commands = LinkCommands(fake_command_bot)
    interaction = MagicMock()
    interaction.guild_id = 111111111
    interaction.channel_id = 222222222
    interaction.response.send_message = AsyncMock()

    with patch("src.bot.commands.link_commands.create_channel_link") as mock_create_channel_link:
        await LinkCommands.link.callback(link_commands, interaction, "owner/repo")

    mock_create_channel_link.assert_called_once()
    assert mock_create_channel_link.call_args.kwargs["guild_id"] == "111111111"
    assert mock_create_channel_link.call_args.kwargs["channel_id"] == "222222222"


@pytest.mark.asyncio
async def test_notification_link_command_persists_guild_and_channel_ids_as_strings():
    """Notifications links should persist Discord IDs as strings for stable lookups."""
    fake_command_bot = FakeCommandBot()
    link_commands = LinkCommands(fake_command_bot)
    interaction = MagicMock()
    interaction.guild_id = 111111111
    interaction.channel_id = 222222222
    interaction.response.send_message = AsyncMock()

    with patch(
        "src.bot.commands.link_commands.create_notification_channel_link"
    ) as mock_create_notification_channel_link:
        await LinkCommands.link_notifications.callback(link_commands, interaction, "owner/repo")

    mock_create_notification_channel_link.assert_called_once()
    assert mock_create_notification_channel_link.call_args.kwargs["guild_id"] == "111111111"
    assert mock_create_notification_channel_link.call_args.kwargs["channel_id"] == "222222222"


@pytest.mark.asyncio
async def test_status_reports_command_and_notification_channels():
    """Status should show both command and notification routing when configured."""
    fake_command_bot = FakeCommandBot()
    link_commands = LinkCommands(fake_command_bot)
    interaction = MagicMock()
    interaction.channel_id = 333333333
    interaction.response.send_message = AsyncMock()

    notification_link = SimpleNamespace(repo_owner="owner", repo_name="repo")
    additional_notification_link = SimpleNamespace(repo_owner="other", repo_name="repo-two")

    with patch(
        "src.bot.commands.link_commands.get_channel_link",
        return_value=SimpleNamespace(repo_owner="owner", repo_name="repo"),
    ), patch(
        "src.bot.commands.link_commands.list_notification_links_for_channel",
        return_value=[notification_link, additional_notification_link],
    ), patch(
        "src.bot.commands.link_commands.is_nlp_channel",
        return_value=True,
    ):
        await LinkCommands.status.callback(link_commands, interaction)

    interaction.response.send_message.assert_awaited_once()
    sent_embed = interaction.response.send_message.await_args.kwargs["embed"]
    assert "Issue Commands" in sent_embed.description
    assert "GitHub Notifications" in sent_embed.description
    assert "`owner/repo`" in sent_embed.description
    assert "`other/repo-two`" in sent_embed.description
    assert "NLP Command Parsing" in sent_embed.description


@pytest.mark.asyncio
async def test_help_command_shows_capability_guide():
    """The /help command should return an embed with setup and command guidance."""
    fake_command_bot = FakeCommandBot()
    link_commands = LinkCommands(fake_command_bot)
    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()

    await LinkCommands.show_help.callback(link_commands, interaction)

    interaction.response.send_message.assert_awaited_once()
    sent_embed = interaction.response.send_message.await_args.kwargs["embed"]
    assert "GitDiscord Help" in sent_embed.title
    assert "/link <owner/repo>" in sent_embed.description
    assert "/issue create <title> [body]" in sent_embed.description
    assert "/nlp-enable" in sent_embed.description
    assert interaction.response.send_message.await_args.kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_help_public_command_posts_pin_ready_guide():
    """The /help-public command should post a public pin-ready help embed."""
    fake_command_bot = FakeCommandBot()
    link_commands = LinkCommands(fake_command_bot)
    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()

    await LinkCommands.show_help_public.callback(link_commands, interaction)

    interaction.response.send_message.assert_awaited_once()
    sent_message_text = interaction.response.send_message.await_args.args[0]
    sent_embed = interaction.response.send_message.await_args.kwargs["embed"]
    assert "Pin this message" in sent_message_text
    assert "GitDiscord Help" in sent_embed.title
    assert "/notifications link <owner/repo>" in sent_embed.description
    assert interaction.response.send_message.await_args.kwargs["ephemeral"] is False


@pytest.mark.asyncio
async def test_create_issue_from_thread_collects_messages_and_creates_issue():
    """The thread collector should turn conversation history into a GitHub issue draft."""
    fake_command_bot = FakeCommandBot()
    issue_commands = IssueCommands(fake_command_bot)
    interaction = MagicMock()
    interaction.channel_id = 333333333
    interaction.response.send_message = AsyncMock()
    interaction.channel = MagicMock()
    interaction.channel.name = "Login bug triage"

    collected_messages = [
        _make_discussion_message("alice", "The app crashes on startup"),
        _make_discussion_message("bot", "ignore this", is_bot=True),
        _make_discussion_message("bob", "I think the database path is wrong"),
    ]
    interaction.channel.history.return_value = _AsyncHistoryIterator(collected_messages)

    fake_created_issue = {
        "number": 42,
        "title": "The app crashes on startup",
        "state": "open",
        "body": "draft body",
        "url": "https://github.com/owner/repo/issues/42",
        "created_at": "2024-01-01T00:00:00",
        "user_login": "alice",
        "labels": [],
        "assignees": [],
    }

    with patch(
        "src.bot.commands.issue_commands.repository.get_channel_link",
        return_value=SimpleNamespace(repo_owner="owner", repo_name="repo"),
    ), patch(
        "src.bot.commands.issue_commands.GitHubClient",
    ) as mock_github_client_class:
        mock_github_client = mock_github_client_class.return_value
        mock_github_client.create_issue.return_value = fake_created_issue

        await IssueCommands.create_issue_from_thread.callback(issue_commands, interaction)

    mock_github_client_class.assert_called_once()
    mock_github_client.create_issue.assert_called_once()
    issue_title = mock_github_client.create_issue.call_args.args[0]
    issue_body = mock_github_client.create_issue.call_args.args[1]

    assert issue_title == "The app crashes on startup"
    assert "Captured from Discord thread: **Login bug triage**" in issue_body
    assert "- **alice**: The app crashes on startup" in issue_body
    assert "- **bob**: I think the database path is wrong" in issue_body
    assert "ignore this" not in issue_body
    interaction.response.send_message.assert_awaited_once()
    sent_embed = interaction.response.send_message.await_args.kwargs["embed"]
    assert sent_embed is not None


@pytest.mark.asyncio
async def test_nlp_handler_resolves_inline_issue_reference_and_replies_with_embed():
    """Inline 'gh issue #N' references should fetch and reply with a clickable issue embed."""
    fake_db_session = MagicMock()
    fake_db_session_factory = MagicMock(return_value=fake_db_session)
    nlp_handler = NlpMessageHandler(
        db_session_factory=fake_db_session_factory,
        discord_bot=MagicMock(),
    )

    message = MagicMock()
    message.author.bot = False
    message.channel.id = 444444444
    message.content = "Hey team, please reference gh issue #123 in this thread."
    message.reply = AsyncMock()
    message.add_reaction = AsyncMock()

    issue_lookup_result = {
        "number": 123,
        "title": "Fix startup crash",
        "state": "open",
        "body": "Details",
        "url": "https://github.com/owner/repo/issues/123",
        "created_at": "2024-01-01T00:00:00",
        "user_login": "alice",
        "labels": [],
        "assignees": [],
    }

    with patch(
        "src.nlp.command_parser.repository.is_nlp_channel",
        return_value=True,
    ), patch(
        "src.nlp.command_parser.repository.get_channel_link",
        return_value=SimpleNamespace(
            github_pat="GITHUB_APP_AUTH",
            repo_owner="owner",
            repo_name="repo",
        ),
    ), patch(
        "src.nlp.command_parser.GitHubClient",
    ) as mock_github_client_class:
        mock_github_client = mock_github_client_class.return_value
        mock_github_client.get_issue.return_value = issue_lookup_result

        await nlp_handler.handle_message(message)

    mock_github_client.get_issue.assert_called_once_with(123)
    message.reply.assert_awaited_once()
    reply_embed = message.reply.await_args.kwargs["embed"]
    assert reply_embed is not None
    assert reply_embed.url == "https://github.com/owner/repo/issues/123"


@pytest.mark.asyncio
async def test_nlp_handler_resolves_inline_pr_reference_and_replies_with_embed():
    """Inline 'github PR #N' references should fetch and reply with a clickable PR embed."""
    fake_db_session = MagicMock()
    fake_db_session_factory = MagicMock(return_value=fake_db_session)
    nlp_handler = NlpMessageHandler(
        db_session_factory=fake_db_session_factory,
        discord_bot=MagicMock(),
    )

    message = MagicMock()
    message.author.bot = False
    message.channel.id = 444444444
    message.content = "Hey team, please check github PR #23 before merging."
    message.reply = AsyncMock()
    message.add_reaction = AsyncMock()

    pull_request_lookup_result = {
        "number": 23,
        "title": "Add review workflow",
        "state": "open",
        "body": "Details",
        "url": "https://github.com/owner/repo/pull/23",
        "created_at": "2024-01-01T00:00:00",
        "user_login": "alice",
        "base_ref": "main",
        "head_ref": "feature/review-workflow",
        "merged": False,
        "merged_by_login": None,
        "labels": [],
        "assignees": [],
    }

    with patch(
        "src.nlp.command_parser.repository.is_nlp_channel",
        return_value=True,
    ), patch(
        "src.nlp.command_parser.repository.get_channel_link",
        return_value=SimpleNamespace(
            github_pat="GITHUB_APP_AUTH",
            repo_owner="owner",
            repo_name="repo",
        ),
    ), patch(
        "src.nlp.command_parser.GitHubClient",
    ) as mock_github_client_class:
        mock_github_client = mock_github_client_class.return_value
        mock_github_client.get_pull_request.return_value = pull_request_lookup_result

        await nlp_handler.handle_message(message)

    mock_github_client.get_pull_request.assert_called_once_with(23)
    message.reply.assert_awaited_once()
    reply_embed = message.reply.await_args.kwargs["embed"]
    assert reply_embed is not None
    assert reply_embed.url == "https://github.com/owner/repo/pull/23"


@pytest.mark.asyncio
async def test_nlp_handler_silently_ignores_unknown_messages():
    """Unknown NLP inputs should be ignored without reactions or replies."""
    fake_db_session = MagicMock()
    fake_db_session_factory = MagicMock(return_value=fake_db_session)
    nlp_handler = NlpMessageHandler(
        db_session_factory=fake_db_session_factory,
        discord_bot=MagicMock(),
    )

    message = MagicMock()
    message.author.bot = False
    message.channel.id = 444444444
    message.content = "This is normal conversation and not a command."
    message.reply = AsyncMock()
    message.add_reaction = AsyncMock()

    with patch(
        "src.nlp.command_parser.repository.is_nlp_channel",
        return_value=True,
    ), patch(
        "src.nlp.command_parser.repository.get_channel_link",
        return_value=SimpleNamespace(
            github_pat="GITHUB_APP_AUTH",
            repo_owner="owner",
            repo_name="repo",
        ),
    ), patch(
        "src.nlp.command_parser.GitHubClient",
    ):
        await nlp_handler.handle_message(message)

    message.reply.assert_not_awaited()
    message.add_reaction.assert_not_awaited()


@pytest.mark.asyncio
async def test_nlp_handler_silently_ignores_unlinked_nlp_channel():
    """NLP-enabled channels without repo links should be ignored without reactions."""
    fake_db_session = MagicMock()
    fake_db_session_factory = MagicMock(return_value=fake_db_session)
    nlp_handler = NlpMessageHandler(
        db_session_factory=fake_db_session_factory,
        discord_bot=MagicMock(),
    )

    message = MagicMock()
    message.author.bot = False
    message.channel.id = 444444444
    message.content = "hello team"
    message.reply = AsyncMock()
    message.add_reaction = AsyncMock()

    with patch(
        "src.nlp.command_parser.repository.is_nlp_channel",
        return_value=True,
    ), patch(
        "src.nlp.command_parser.repository.get_channel_link",
        return_value=None,
    ), patch("src.nlp.command_parser.GitHubClient") as mock_github_client_class:
        await nlp_handler.handle_message(message)

    mock_github_client_class.assert_not_called()
    message.reply.assert_not_awaited()
    message.add_reaction.assert_not_awaited()
