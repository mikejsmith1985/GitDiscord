"""Tests for src/config.py — Settings loading and caching behaviour."""

import pytest
from pydantic import ValidationError


def test_settings_requires_discord_bot_token_and_webhook_secret(monkeypatch):
    """Settings must raise ValidationError when required fields are missing."""
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)

    # Force a fresh import so the lru_cache does not return a stale instance
    from importlib import reload
    import src.config as config_module
    config_module.get_settings.cache_clear()

    with pytest.raises(ValidationError):
        config_module.Settings()


def test_settings_defaults_are_applied(monkeypatch):
    """Optional fields fall back to their documented defaults."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
    monkeypatch.setenv("WEBHOOK_SECRET", "test-secret")
    # Ensure no leftover overrides from the environment
    monkeypatch.delenv("WEBHOOK_PORT", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("ENABLE_MESSAGE_CONTENT_INTENT", raising=False)
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("GITHUB_APP_INSTALLATION_ID", raising=False)

    from importlib import reload
    import src.config as config_module
    config_module.get_settings.cache_clear()

    loaded_settings = config_module.Settings(_env_file=None)

    assert loaded_settings.webhook_port == 8080
    assert loaded_settings.database_path == "./data/gitdiscord.db"
    assert loaded_settings.log_level == "INFO"
    assert loaded_settings.enable_message_content_intent is False
    assert loaded_settings.github_app_id == ""
    assert loaded_settings.github_app_private_key == ""
    assert loaded_settings.github_app_installation_id == ""


def test_get_settings_returns_cached_instance(monkeypatch):
    """get_settings() must return the same object on repeated calls."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
    monkeypatch.setenv("WEBHOOK_SECRET", "test-secret")

    import src.config as config_module
    config_module.get_settings.cache_clear()

    first_call_result = config_module.get_settings()
    second_call_result = config_module.get_settings()

    assert first_call_result is second_call_result
