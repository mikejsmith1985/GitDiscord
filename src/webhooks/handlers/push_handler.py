"""
push_handler.py — Handles GitHub 'push' webhook events for the GitDiscord bot.

Receives a parsed push payload, formats it as a Discord embed via the
shared formatter, and forwards it to the target channel using the provided
send function.
"""

import logging

from src.formatters import format_push_event

logger = logging.getLogger(__name__)


async def handle_push_event(payload: dict, send_embed_fn) -> None:
    """
    Handle a GitHub 'push' webhook event.

    Converts the raw push payload into a Discord embed and delivers it to
    the linked channel.  All channel resolution is delegated to send_embed_fn
    so this handler stays focused purely on formatting.

    Args:
        payload:       The parsed JSON body of the GitHub push webhook.
        send_embed_fn: An async callable that accepts (payload, embed) and
                       routes the embed to the correct Discord channel.
    """
    repo_full_name = payload.get("repository", {}).get("full_name", "unknown/repo")
    logger.info("Handling push event for repository: %s", repo_full_name)

    embed = format_push_event(payload)
    await send_embed_fn(payload, embed)
