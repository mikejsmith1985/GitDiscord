"""
SQLAlchemy ORM model definitions for the GitDiscord bot database.

Defines the ChannelRepoLink and NlpChannel tables, along with engine
factory and table-creation helpers used at startup.
"""

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped


# ── Base class ──────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


# ── Models ───────────────────────────────────────────────────────────────────

class ChannelRepoLink(Base):
    """
    Maps a single Discord channel to a GitHub repository.

    One channel may only track one repository at a time, enforced by the
    unique constraint on channel_id.  The PAT is stored as plain text so the
    bot can forward it to the GitHub API without an extra decryption step —
    callers are responsible for ensuring the token is scoped to the minimum
    required permissions.
    """

    __tablename__ = "channel_repo_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(String, nullable=False)
    channel_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    repo_owner: Mapped[str] = mapped_column(String, nullable=False)
    repo_name: Mapped[str] = mapped_column(String, nullable=False)
    # PAT kept verbatim — transport security (TLS) protects it in transit;
    # at-rest encryption is left to the deployment environment.
    github_pat: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return (
            f"<ChannelRepoLink channel_id={self.channel_id!r} "
            f"repo={self.repo_owner}/{self.repo_name}>"
        )


class NlpChannel(Base):
    """
    Tracks which Discord channels have NLP (natural-language) parsing enabled.

    Presence of a row for a given channel_id means NLP is active; absence
    means it is off.  This avoids a nullable boolean column and makes
    enable/disable operations a simple insert/delete.
    """

    __tablename__ = "nlp_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(String, nullable=False)
    channel_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<NlpChannel channel_id={self.channel_id!r} guild_id={self.guild_id!r}>"


# ── Engine & schema helpers ───────────────────────────────────────────────────

def _ensure_sqlite_parent_directory(database_path: str) -> None:
    """
    Create the folder that will hold a file-backed SQLite database.

    SQLite creates the database file automatically, but it will not create a
    missing parent folder. Creating that folder here makes first-run setup work
    on developer machines and deployments that mount an empty data directory.
    """
    if database_path == ":memory:":
        return

    database_file_path = Path(database_path).expanduser()
    database_folder_path = database_file_path.parent
    if str(database_folder_path) == ".":
        return

    database_folder_path.mkdir(parents=True, exist_ok=True)


def get_engine(database_path: str):
    """
    Create and return a SQLAlchemy engine pointed at the given SQLite file.

    Using check_same_thread=False so the engine can be shared across async
    tasks that run in the same event loop but different OS threads (common
    in discord.py bot processes).

    Args:
        database_path: Filesystem path to the SQLite database file, e.g.
                       "data/gitdiscord.db".  The file is created on first
                       use if it does not already exist.

    Returns:
        A configured SQLAlchemy Engine instance.
    """
    _ensure_sqlite_parent_directory(database_path)

    # The connect_args key is SQLite-specific and prevents "ProgrammingError:
    # SQLite objects created in a thread can only be used in that same thread"
    # when the engine is shared across async contexts.
    sqlite_connection_url = f"sqlite:///{database_path}"
    return create_engine(
        sqlite_connection_url,
        connect_args={"check_same_thread": False},
    )


def create_all_tables(engine) -> None:
    """
    Create all ORM-defined tables in the target database if they do not exist.

    Safe to call on every bot startup — SQLAlchemy's CREATE TABLE IF NOT
    EXISTS semantics mean existing data is never touched.

    Args:
        engine: A SQLAlchemy Engine returned by get_engine().

    Returns:
        None
    """
    Base.metadata.create_all(engine)
