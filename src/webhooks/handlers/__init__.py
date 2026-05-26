"""
handlers/__init__.py — Public API for GitDiscord webhook event handlers.

Exports the top-level handler coroutines so callers can import them from
the package without knowing which submodule they live in.
"""

from src.webhooks.handlers.pr_handler import (
    handle_commit_comment_event,
    handle_issue_comment_event,
    handle_issue_event,
    handle_pr_event,
)
from src.webhooks.handlers.push_handler import handle_push_event

__all__ = [
    "handle_push_event",
    "handle_pr_event",
    "handle_issue_event",
    "handle_issue_comment_event",
    "handle_commit_comment_event",
]
