"""
pr_handler.py — Handles pull-request and issue-comment webhook events.

Routes supported GitHub event actions to Discord embed formatters and sends
them to the linked notification channel through the provided send function.
"""

import logging

from src.formatters import (
    format_commit_comment_event,
    format_issue_comment_event,
    format_issue_dict,
    format_pr_opened,
    format_pr_review_requested,
    format_pr_merged,
    format_pr_closed_without_merge,
)

logger = logging.getLogger(__name__)

# GitHub sends this action string when a PR is closed regardless of whether
# it was merged; we distinguish the two sub-cases by inspecting the merged flag.
_ACTION_CLOSED = "closed"
_ACTION_OPENED = "opened"
_ACTION_REVIEW_REQUESTED = "review_requested"
_SUPPORTED_ISSUE_ACTIONS = {"opened", "edited", "closed", "reopened"}
_SUPPORTED_COMMENT_ACTIONS = {"created", "edited", "deleted"}


async def handle_pr_event(payload: dict, send_embed_fn) -> None:
    """
    Handle a GitHub 'pull_request' webhook event.

    Routes the event to the correct formatter based on the action field, then
    delivers the resulting embed to the linked Discord channel.  Actions that
    GitDiscord does not support (e.g. 'labeled', 'synchronize') are silently
    skipped — this prevents unnecessary log noise while still being safe.

    Action routing:
        - "opened"           → format_pr_opened
        - "review_requested" → format_pr_review_requested
        - "closed" + merged  → format_pr_merged
        - "closed" + !merged → format_pr_closed_without_merge
        - anything else      → log at DEBUG level and return

    Args:
        payload:       The parsed JSON body of the GitHub pull_request webhook.
        send_embed_fn: An async callable that accepts (payload, embed) and
                       routes the embed to the correct Discord channel.
    """
    action = payload.get("action", "")
    repo_full_name = payload.get("repository", {}).get("full_name", "unknown/repo")
    logger.info(
        "Handling pull_request event: action=%r repository=%s", action, repo_full_name
    )

    if action == _ACTION_OPENED:
        embed = format_pr_opened(payload)

    elif action == _ACTION_REVIEW_REQUESTED:
        embed = format_pr_review_requested(payload)

    elif action == _ACTION_CLOSED:
        # GitHub uses the same 'closed' action for both merges and plain closes;
        # the merged boolean distinguishes which event actually occurred.
        was_merged = payload.get("pull_request", {}).get("merged", False)
        if was_merged:
            embed = format_pr_merged(payload)
        else:
            embed = format_pr_closed_without_merge(payload)

    else:
        # Many PR actions (labeled, unlabeled, synchronize, etc.) are not
        # meaningful for Discord notifications, so we skip them quietly.
        logger.debug(
            "Ignoring unsupported pull_request action %r for %s", action, repo_full_name
        )
        return

    await send_embed_fn(payload, embed)


async def handle_issue_event(payload: dict, send_embed_fn) -> None:
    """
    Handle a GitHub 'issues' webhook event.

    Sends lifecycle updates that matter in chat and skips noisy actions.
    """
    action = payload.get("action", "")
    repo_full_name = payload.get("repository", {}).get("full_name", "unknown/repo")
    logger.info(
        "Handling issues event: action=%r repository=%s", action, repo_full_name
    )
    if action not in _SUPPORTED_ISSUE_ACTIONS:
        logger.debug(
            "Ignoring unsupported issues action %r for %s", action, repo_full_name
        )
        return

    issue_dict = payload.get("issue", {})
    issue_number = issue_dict.get("number", "unknown")
    logger.info(
        "Processing issue #%s action=%r repository=%s",
        issue_number,
        action,
        repo_full_name,
    )
    embed = format_issue_dict(issue_dict, action=action)
    await send_embed_fn(payload, embed)
    logger.info(
        "Successfully sent embed for issue #%s (%s) to Discord",
        issue_number,
        repo_full_name,
    )


async def handle_issue_comment_event(payload: dict, send_embed_fn) -> None:
    """
    Handle a GitHub 'issue_comment' webhook event.

    Sends comment activity so issue discussion is visible in Discord.
    """
    action = payload.get("action", "")
    repo_full_name = payload.get("repository", {}).get("full_name", "unknown/repo")
    if action not in _SUPPORTED_COMMENT_ACTIONS:
        logger.debug(
            "Ignoring unsupported issue_comment action %r for %s",
            action,
            repo_full_name,
        )
        return

    embed = format_issue_comment_event(payload)
    await send_embed_fn(payload, embed)


async def handle_commit_comment_event(payload: dict, send_embed_fn) -> None:
    """
    Handle a GitHub 'commit_comment' webhook event.

    Sends commit discussion activity so review feedback reaches Discord.
    """
    action = payload.get("action", "")
    repo_full_name = payload.get("repository", {}).get("full_name", "unknown/repo")
    if action not in _SUPPORTED_COMMENT_ACTIONS:
        logger.debug(
            "Ignoring unsupported commit_comment action %r for %s",
            action,
            repo_full_name,
        )
        return

    embed = format_commit_comment_event(payload)
    await send_embed_fn(payload, embed)
