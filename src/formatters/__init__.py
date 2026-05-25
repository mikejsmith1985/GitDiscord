"""
formatters/__init__.py — Public API for the GitDiscord embed formatter package.

Import all format functions here so callers can do:
    from src.formatters import format_push_event, format_pr_opened, ...
"""

from .discord_embeds import (
    format_push_event,
    format_pr_opened,
    format_pr_review_requested,
    format_pr_merged,
    format_pr_closed_without_merge,
    format_issue_dict,
)

__all__ = [
    "format_push_event",
    "format_pr_opened",
    "format_pr_review_requested",
    "format_pr_merged",
    "format_pr_closed_without_merge",
    "format_issue_dict",
]
