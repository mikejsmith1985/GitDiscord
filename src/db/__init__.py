"""
Public interface for the GitDiscord database package.

Import the engine factory, schema helper, ORM models, and repository
functions from this single entry point so the rest of the bot never needs
to reach into sub-modules directly.
"""

from src.db.models import (
    ChannelRepoLink,
    NlpChannel,
    NotificationChannelLink,
    create_all_tables,
    get_engine,
)
from src.db.repository import (
    create_channel_link,
    create_notification_channel_link,
    delete_channel_link,
    delete_notification_channel_link,
    disable_nlp_channel,
    enable_nlp_channel,
    get_channel_link,
    get_channel_link_for_repo,
    get_notification_channel_link,
    is_nlp_channel,
    list_guild_links,
    list_notification_links_for_channel,
)

__all__ = [
    # Schema helpers
    "get_engine",
    "create_all_tables",
    # ORM models
    "ChannelRepoLink",
    "NotificationChannelLink",
    "NlpChannel",
    # ChannelRepoLink repository functions
    "create_channel_link",
    "get_channel_link",
    "get_channel_link_for_repo",
    "delete_channel_link",
    "list_guild_links",
    # NotificationChannelLink repository functions
    "create_notification_channel_link",
    "get_notification_channel_link",
    "delete_notification_channel_link",
    "list_notification_links_for_channel",
    # NlpChannel repository functions
    "enable_nlp_channel",
    "disable_nlp_channel",
    "is_nlp_channel",
]
