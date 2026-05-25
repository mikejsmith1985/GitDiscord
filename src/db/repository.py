"""
Data-access layer for the GitDiscord bot database.

All functions accept an open SQLAlchemy Session and return ORM model instances
or simple Python types.  Keeping raw SQL out of the rest of the codebase means
the bot logic never has to know which database engine is in use.
"""

from sqlalchemy import select, delete
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from src.db.models import ChannelRepoLink, NlpChannel


# ── ChannelRepoLink operations ────────────────────────────────────────────────

def create_channel_link(
    session: Session,
    guild_id: str,
    channel_id: str,
    repo_owner: str,
    repo_name: str,
    github_pat: str,
) -> ChannelRepoLink:
    """
    Create or update the GitHub repository link for a Discord channel.

    Because each channel may only point to one repository, calling this
    function for a channel that already has a link replaces the existing
    record (upsert).  This lets users re-run the setup command to rotate
    their PAT or switch repositories without having to unlink first.

    Args:
        session:    An open SQLAlchemy Session.
        guild_id:   Discord snowflake ID of the server that owns the channel.
        channel_id: Discord snowflake ID of the channel being linked.
        repo_owner: GitHub user or organisation that owns the repository.
        repo_name:  GitHub repository name (without the owner prefix).
        github_pat: Personal Access Token with the required GitHub scopes.

    Returns:
        The newly created or updated ChannelRepoLink ORM instance.
    """
    # SQLite's INSERT OR REPLACE keeps the upsert atomic, avoiding the
    # race condition that a SELECT-then-INSERT/UPDATE pattern would introduce.
    upsert_statement = (
        sqlite_insert(ChannelRepoLink)
        .values(
            guild_id=guild_id,
            channel_id=channel_id,
            repo_owner=repo_owner,
            repo_name=repo_name,
            github_pat=github_pat,
        )
        .on_conflict_do_update(
            index_elements=[ChannelRepoLink.channel_id],
            set_={
                "guild_id": guild_id,
                "repo_owner": repo_owner,
                "repo_name": repo_name,
                "github_pat": github_pat,
                # created_at is intentionally not updated so the original
                # link date is preserved for audit purposes.
            },
        )
    )
    session.execute(upsert_statement)
    session.flush()

    # Re-fetch so the caller always gets a fully populated ORM instance,
    # regardless of whether the row was inserted or updated.
    return get_channel_link(session, channel_id)


def get_channel_link(session: Session, channel_id: str) -> ChannelRepoLink | None:
    """
    Retrieve the repository link for a specific Discord channel.

    Args:
        session:    An open SQLAlchemy Session.
        channel_id: Discord snowflake ID of the channel to look up.

    Returns:
        The ChannelRepoLink for this channel, or None if no link exists.
    """
    query = select(ChannelRepoLink).where(ChannelRepoLink.channel_id == channel_id)
    return session.scalars(query).first()


def delete_channel_link(session: Session, channel_id: str) -> bool:
    """
    Remove the repository link for a Discord channel.

    Args:
        session:    An open SQLAlchemy Session.
        channel_id: Discord snowflake ID of the channel whose link to remove.

    Returns:
        True if a row was deleted, False if no link existed for this channel.
    """
    delete_statement = (
        delete(ChannelRepoLink).where(ChannelRepoLink.channel_id == channel_id)
    )
    result = session.execute(delete_statement)
    # rowcount reflects how many rows were actually removed by the statement.
    was_deleted = result.rowcount > 0
    return was_deleted


def list_guild_links(session: Session, guild_id: str) -> list[ChannelRepoLink]:
    """
    Return all repository links registered within a Discord server.

    Useful for the bot's list/status commands so server admins can see
    every channel-to-repo mapping at a glance.

    Args:
        session:  An open SQLAlchemy Session.
        guild_id: Discord snowflake ID of the server to query.

    Returns:
        A list of ChannelRepoLink instances (may be empty).
    """
    query = select(ChannelRepoLink).where(ChannelRepoLink.guild_id == guild_id)
    return list(session.scalars(query).all())


# ── NlpChannel operations ─────────────────────────────────────────────────────

def enable_nlp_channel(session: Session, guild_id: str, channel_id: str) -> NlpChannel:
    """
    Mark a Discord channel as having NLP parsing enabled.

    Idempotent — calling this on an already-enabled channel is a no-op that
    still returns the existing NlpChannel row.

    Args:
        session:    An open SQLAlchemy Session.
        guild_id:   Discord snowflake ID of the server that owns the channel.
        channel_id: Discord snowflake ID of the channel to enable.

    Returns:
        The NlpChannel ORM instance (new or pre-existing).
    """
    # Use INSERT OR IGNORE so a duplicate channel_id never raises an error.
    upsert_statement = (
        sqlite_insert(NlpChannel)
        .values(guild_id=guild_id, channel_id=channel_id)
        .on_conflict_do_nothing(index_elements=[NlpChannel.channel_id])
    )
    session.execute(upsert_statement)
    session.flush()

    query = select(NlpChannel).where(NlpChannel.channel_id == channel_id)
    return session.scalars(query).first()


def disable_nlp_channel(session: Session, channel_id: str) -> bool:
    """
    Remove the NLP-enabled flag for a Discord channel.

    Args:
        session:    An open SQLAlchemy Session.
        channel_id: Discord snowflake ID of the channel to disable.

    Returns:
        True if NLP was previously enabled and has now been disabled,
        False if the channel was not in the NLP list.
    """
    delete_statement = delete(NlpChannel).where(NlpChannel.channel_id == channel_id)
    result = session.execute(delete_statement)
    was_disabled = result.rowcount > 0
    return was_disabled


def is_nlp_channel(session: Session, channel_id: str) -> bool:
    """
    Check whether a Discord channel has NLP parsing enabled.

    Args:
        session:    An open SQLAlchemy Session.
        channel_id: Discord snowflake ID of the channel to check.

    Returns:
        True if the channel is registered in the NlpChannel table,
        False otherwise.
    """
    query = select(NlpChannel.id).where(NlpChannel.channel_id == channel_id)
    # Using .first() instead of .one_or_none() avoids an unnecessary full-row
    # fetch — we only need to know if any row exists, not what it contains.
    existing_row = session.scalars(query).first()
    is_enabled = existing_row is not None
    return is_enabled
