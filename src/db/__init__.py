"""
Public interface for the GitDiscord database package.

Import the engine factory, schema helper, ORM models, and repository
functions from this single entry point so the rest of the bot never needs
to reach into sub-modules directly.
"""

from src.db.models import (
    ChannelRepoLink,
    NlpChannel,
    create_all_tables,
    get_engine,
)
from src.db.repository import (
    create_channel_link,
    delete_channel_link,
    disable_nlp_channel,
    enable_nlp_channel,
    get_channel_link,
    is_nlp_channel,
    list_guild_links,
)

__all__ = [
    # Schema helpers
    "get_engine",
    "create_all_tables",
    # ORM models
    "ChannelRepoLink",
    "NlpChannel",
    # ChannelRepoLink repository functions
    "create_channel_link",
    "get_channel_link",
    "delete_channel_link",
    "list_guild_links",
    # NlpChannel repository functions
    "enable_nlp_channel",
    "disable_nlp_channel",
    "is_nlp_channel",
]
