"""
push_handler.py — Handles GitHub 'push' webhook events for the GitDiscord bot.

Receives a parsed push payload, formats it as a Discord embed via the
shared formatter, and forwards it to the target channel using the provided
send function.
"""

import logging

from src.formatters import format_push_event

logger = logging.getLogger(__name__)

# GitHub ref prefix for annotated and lightweight tags — we skip these because
# tag pushes are not meaningful as Discord notifications in most workflows.
GIT_TAG_REF_PREFIX = "refs/tags/"


async def handle_push_event(payload: dict, send_embed_fn) -> None:
    """
    Handle a GitHub 'push' webhook event.

    Skips tag pushes (ref starts with "refs/tags/") — we only care about
    branch pushes.  Also skips events with an empty commits list, which
    GitHub sends for branch deletion events.

    Converts the raw push payload into a Discord embed and delivers it to
    the linked channel.  All channel resolution is delegated to send_embed_fn
    so this handler stays focused purely on formatting.

    Args:
        payload:       The parsed JSON body of the GitHub push webhook.
        send_embed_fn: An async callable that accepts (payload, embed) and
                       routes the embed to the correct Discord channel.
    """
    repo_full_name = payload.get("repository", {}).get("full_name", "unknown/repo")
    ref = payload.get("ref", "")

    # Tag pushes (e.g. "refs/tags/v1.2.3") produce a push event but carry no
    # commit list we would want to display; skip them entirely.
    is_tag_push = ref.startswith(GIT_TAG_REF_PREFIX)
    if is_tag_push:
        logger.debug(
            "Skipping tag push for ref=%r in repository %s", ref, repo_full_name
        )
        return

    commits = payload.get("commits", [])
    has_commits = bool(commits)
    if not has_commits:
        # An empty commits list signals a branch deletion event.  There is
        # nothing to display, so we drop it silently at DEBUG level.
        logger.debug(
            "Skipping push event with no commits (likely a branch deletion) "
            "for ref=%r in repository %s",
            ref,
            repo_full_name,
        )
        return

    logger.info("Handling push event for repository: %s ref=%s", repo_full_name, ref)

    embed = format_push_event(payload)
    await send_embed_fn(payload, embed)
