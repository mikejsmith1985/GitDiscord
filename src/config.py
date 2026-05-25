"""Configuration loader for GitDiscord using pydantic-settings.

Reads all required and optional settings from environment variables (or a .env
file). A single cached Settings instance is shared across the entire application
via get_settings(), so the .env file is only parsed once at startup.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All runtime configuration for GitDiscord.

    Values are read from environment variables first, then from a .env file.
    Fields without defaults are required — the application will raise a
    ValidationError at startup if they are missing.
    """

    discord_bot_token: str
    webhook_secret: str
    webhook_port: int = 8080
    database_path: str = "/app/data/gitdiscord.db"
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache application settings from environment variables.

    The lru_cache ensures Settings() is only instantiated once — subsequent
    calls return the same object, avoiding redundant disk reads and validation.
    Call get_settings.cache_clear() in tests to force a fresh load.
    """
    return Settings()
