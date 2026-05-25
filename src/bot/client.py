"""
Discord bot client for GitDiscord — the entry point for all Discord interactions.

This module defines GitDiscordBot, which extends discord.py's Bot class to wire
together the database session factory, loaded cog extensions, and bot lifecycle
hooks (startup logging, slash-command registration).  The module-level
start_bot() function is the single call-site used by __main__.py or any other
process launcher.
"""

import logging
from contextlib import contextmanager
from typing import Generator

import discord
from discord.ext import commands
from sqlalchemy.orm import Session, sessionmaker

from src.nlp.command_parser import NlpMessageHandler


# ── Constants ─────────────────────────────────────────────────────────────────

# Slash commands are the primary user interface for GitDiscord.  discord.py's
# Bot constructor requires a command_prefix argument even when text-prefix
# commands are not used, so this dummy value satisfies that requirement without
# accidentally enabling text-trigger commands in production.
DUMMY_COMMAND_PREFIX = "!"

# Fully-qualified Python module paths for each cog that the bot loads at
# startup.  Adding a new command group means appending its module path here.
EXTENSION_MODULE_PATHS: list[str] = [
    "src.bot.commands.link_commands",
    "src.bot.commands.issue_commands",
]

logger = logging.getLogger(__name__)


# ── Bot class ─────────────────────────────────────────────────────────────────

class GitDiscordBot(commands.Bot):
    """
    The main GitDiscord bot client.

    Extends discord.py's commands.Bot to carry a SQLAlchemy session factory so
    that every slash-command cog can open a database session without relying on
    module-level singletons.  Cog extensions are loaded automatically inside
    setup_hook so all slash commands are registered before the bot starts
    receiving gateway events.
    """

    def __init__(
        self,
        db_session_factory: sessionmaker,
        should_enable_message_content_intent: bool = False,
    ) -> None:
        """
        Initialise the bot with safe Discord intents and the database factory.

        Slash commands and GitHub webhook notifications do not need privileged
        gateway access.  Message Content stays disabled by default so first-run
        bot setup works without extra Discord Developer Portal toggles.

        Set should_enable_message_content_intent only after enabling Message
        Content Intent in the Discord Developer Portal.  That opt-in is required
        for NLP channels that read ordinary user messages.

        Args:
            db_session_factory: A configured SQLAlchemy sessionmaker bound to
                                 the application's SQLite database.  All cogs
                                 share this factory so each request opens its
                                 own short-lived session, preventing hidden
                                 transaction leaks across command invocations.
            should_enable_message_content_intent: Whether to request Discord's
                                                 privileged Message Content
                                                 Intent for NLP channel mode.
        """
        required_intents = discord.Intents.default()
        required_intents.message_content = should_enable_message_content_intent

        super().__init__(
            command_prefix=DUMMY_COMMAND_PREFIX,
            intents=required_intents,
        )

        self._db_session_factory: sessionmaker = db_session_factory

        # Create the NLP handler once at startup and reuse it for every message
        # so we don't allocate a new object per Discord gateway event.
        self._nlp_handler = NlpMessageHandler(
            db_session_factory=db_session_factory,
            discord_bot=self,
        )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def channel_session_factory(self) -> sessionmaker:
        """
        Return the SQLAlchemy sessionmaker held by this bot instance.

        Cogs that need direct factory access (e.g. to inspect pool state or
        pass the factory to a helper class) should use this property rather
        than importing a module-level global, so the dependency path stays
        explicit and testable.
        """
        return self._db_session_factory

    # ── Database helpers ──────────────────────────────────────────────────────

    @contextmanager
    def get_db_session(self) -> Generator[Session, None, None]:
        """
        Open a short-lived SQLAlchemy session scoped to a single operation.

        Commits automatically on success and rolls back if an exception is
        raised, so callers never need to manage transaction state themselves.

        The underlying SQLAlchemy sessions are synchronous (matching the rest
        of the db layer).  SQLite queries return fast enough that running them
        on the event-loop thread is acceptable for this project's scale.  If a
        future migration to PostgreSQL demands true async I/O, switch to an
        AsyncSession here without changing any cog code.

        Usage in an async command handler::

            with self.bot.get_db_session() as db_session:
                link = repository.get_channel_link(db_session, channel_id)

        Yields:
            An open SQLAlchemy Session ready for queries and mutations.

        Raises:
            Re-raises any exception thrown inside the ``with`` block after
            rolling back the session so the database stays consistent.
        """
        db_session: Session = self._db_session_factory()
        try:
            yield db_session
            db_session.commit()
        except Exception:
            # Roll back any partial writes to avoid leaving the database in an
            # inconsistent state when a command handler raises mid-transaction.
            db_session.rollback()
            raise
        finally:
            db_session.close()

    # ── Lifecycle hooks ───────────────────────────────────────────────────────

    async def setup_hook(self) -> None:
        """
        Load all cog extensions before the bot connects to the Discord gateway.

        discord.py calls setup_hook once after a successful login but before
        the WebSocket connection opens.  This is the right moment to load cogs
        because it ensures every slash command is registered with discord.py's
        internal command tree before the bot can receive any interactions.

        Extensions that have not been created yet (during incremental
        development) produce a warning rather than a crash so the bot remains
        usable with a partial feature set.
        """
        for extension_module_path in EXTENSION_MODULE_PATHS:
            try:
                await self.load_extension(extension_module_path)
                logger.info("Loaded extension: %s", extension_module_path)
            except commands.ExtensionNotFound:
                # Warn instead of crash so the bot can start before all cog
                # files have been written — useful during iterative development.
                logger.warning(
                    "Extension not found (not yet implemented): %s",
                    extension_module_path,
                )
            except commands.ExtensionFailed as extension_error:
                # An extension that exists but raises during import is a real
                # problem that should surface immediately rather than silently
                # leaving the bot with missing commands.
                logger.error(
                    "Failed to load extension %s: %s",
                    extension_module_path,
                    extension_error,
                )
                raise

    async def on_ready(self) -> None:
        """
        Log confirmation that the bot is connected and ready to serve requests.

        discord.py fires this event once the initial guild data has been
        received from the gateway.  Logging the username and guild count here
        makes it easy to confirm that the correct bot account and token are in
        use after a deployment or token rotation.
        """
        guild_count = len(self.guilds)
        logger.info(
            "GitDiscord bot is ready. Logged in as %s (id=%s) across %d guild(s).",
            self.user,
            self.user.id,  # type: ignore[union-attr]  # user is guaranteed non-None when on_ready fires
            guild_count,
        )

    async def on_message(self, message: discord.Message) -> None:
        """
        Handle every message the bot can see in guild channels.

        Routes NLP-enabled channel messages through NlpMessageHandler and then
        calls process_commands() so any prefix-based commands still work.
        Direct messages (DMs) are ignored because NLP channels only exist inside
        Discord servers (guilds), and there is no repository link concept for DMs.

        Args:
            message: The discord.Message received from the gateway event.
        """
        # DMs have no guild association and cannot be NLP channels, so skip them
        # up front rather than letting the handler open a DB session for nothing.
        if message.guild is None:
            return

        await self._nlp_handler.handle_message(message)

        # Always call process_commands() so prefix-based slash command triggers
        # (e.g. cog text commands) continue to work alongside NLP parsing.
        await self.process_commands(message)


# ── Module-level entry point ──────────────────────────────────────────────────

async def start_bot(token: str, db_session_factory: sessionmaker) -> None:
    """
    Create a GitDiscordBot instance and run it until the process is interrupted.

    This function is the single call-site that __main__.py (or a process
    supervisor) uses to bring the bot online.  Keeping bot construction and
    bot.start() together here means callers pass only the two pieces of
    external configuration they own (the token and the DB factory) without
    needing to know anything about discord.py internals.

    Args:
        token:              The Discord bot token from the Developer Portal.
                            This value is sensitive — never log it, and load it
                            exclusively from environment variables or a secrets
                            manager.
        db_session_factory: A configured SQLAlchemy sessionmaker to pass to
                            the GitDiscordBot constructor.

    Returns:
        None.  This coroutine runs until the bot disconnects or the process
        receives a termination signal.
    """
    bot = GitDiscordBot(db_session_factory=db_session_factory)

    # bot.start() is the async equivalent of bot.run().  It blocks until the
    # connection is cleanly closed (e.g. SIGTERM) or an unrecoverable error
    # propagates up from the discord.py event loop.
    await bot.start(token)
