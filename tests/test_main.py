"""Tests for src/main.py — entry point wiring and PORT override logic."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

from src.bot.client import GitDiscordBot


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
    )
    mock_create_webhook_app.assert_called_once()
    call_kwargs = mock_create_webhook_app.call_args.kwargs
    assert call_kwargs["discord_bot"] is fake_bot_instance
