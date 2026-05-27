"""Application entry point for GitDiscord.

Starts both the Discord bot and the FastAPI webhook server concurrently on a
single asyncio event loop. Neither service is useful without the other:
- The webhook server needs the live bot to forward GitHub events to Discord channels.
- The bot needs to be running to process slash commands and NLP messages.
"""

import asyncio
import logging
import os

import uvicorn
from sqlalchemy.orm import sessionmaker

from src.bot.client import GitDiscordBot
from src.config import get_settings
from src.db.models import create_all_tables, get_engine
from src.webhooks.server import create_webhook_app


async def main() -> None:
    """Start the Discord bot and webhook server concurrently.

    Both processes must run together:
    - The webhook server needs the live Discord bot to send messages to channels
    - The bot needs to be running to process slash commands
    asyncio.gather() runs both coroutines on the same event loop.
    """
    settings = get_settings()

    # Configure logging before anything else so startup messages are captured
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)
    logger.info("Starting GitDiscord...")

    # Initialize the SQLite database and create tables if they don't exist yet
    database_engine = get_engine(settings.database_path)
    create_all_tables(database_engine)
    # Keep ORM attributes accessible after commit so command handlers can safely
    # render values after the context-managed session exits.
    db_session_factory = sessionmaker(
        bind=database_engine,
        expire_on_commit=False,
    )

    # Create bot instance — cogs receive the session factory so they can query the DB
    discord_bot = GitDiscordBot(
        db_session_factory=db_session_factory,
        should_enable_message_content_intent=settings.enable_message_content_intent,
        github_app_id=settings.github_app_id,
        github_app_private_key=settings.github_app_private_key,
        github_app_installation_id=settings.github_app_installation_id,
    )

    # Create FastAPI webhook app — needs the bot reference to post Discord messages
    webhook_app = create_webhook_app(
        discord_bot=discord_bot,
        db_session_factory=db_session_factory,
    )

    # Railway injects PORT at runtime and overrides the configured webhook_port.
    # Using os.environ.get("PORT", ...) lets local dev use the .env value while
    # Railway deployments automatically bind to the correct public port.
    railway_port = int(os.environ.get("PORT", settings.webhook_port))

    # Use uvicorn's async Server API (not the blocking uvicorn.run) so the webhook
    # server can share the event loop with the Discord bot inside asyncio.gather().
    uvicorn_config = uvicorn.Config(
        webhook_app,
        host="0.0.0.0",
        port=railway_port,
        log_level="warning",
    )
    uvicorn_server = uvicorn.Server(uvicorn_config)

    logger.info(
        "Starting webhook server on port %d and Discord bot", railway_port
    )
    await asyncio.gather(
        uvicorn_server.serve(),
        discord_bot.start(settings.discord_bot_token),
    )


if __name__ == "__main__":
    asyncio.run(main())
