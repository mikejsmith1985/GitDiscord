"""
test_pr_handler.py — Unit tests for pull-request and issue-related handlers.

Verifies event handlers route supported actions to send_embed_fn and silently
ignore unsupported actions without raising.
"""

import pytest

from src.webhooks.handlers.pr_handler import (
    handle_commit_comment_event,
    handle_issue_comment_event,
    handle_issue_event,
    handle_pr_event,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_pr_payload(action: str, is_merged: bool = False) -> dict:
    """Build a minimal pull_request webhook payload for the given action."""
    return {
        "action": action,
        "repository": {"full_name": "owner/repo"},
        "pull_request": {
            "number": 42,
            "title": "Test PR",
            "html_url": "https://github.com/owner/repo/pull/42",
            "user": {"login": "alice"},
            "base": {"ref": "main"},
            "head": {"ref": "feature/test"},
            "body": "PR body text",
            "merged": is_merged,
            "merged_by": {"login": "alice"} if is_merged else None,
        },
        "sender": {"login": "alice"},
        "requested_reviewer": {"login": "bob"},
    }


def _make_issue_payload(action: str) -> dict:
    """Build a minimal issues webhook payload for the given action."""
    return {
        "action": action,
        "repository": {"full_name": "owner/repo"},
        "issue": {
            "number": 5,
            "title": "Issue title",
            "state": "open",
            "body": "Issue body",
            "html_url": "https://github.com/owner/repo/issues/5",
            "labels": [{"name": "bug"}],
        },
    }


def _make_issue_comment_payload(action: str) -> dict:
    """Build a minimal issue_comment webhook payload for the given action."""
    return {
        "action": action,
        "repository": {"full_name": "owner/repo"},
        "issue": {
            "number": 7,
            "title": "Issue with comments",
            "state": "open",
        },
        "comment": {
            "html_url": "https://github.com/owner/repo/issues/7#issuecomment-1",
            "body": "Looks good to me",
            "user": {"login": "alice"},
        },
    }


def _make_commit_comment_payload(action: str) -> dict:
    """Build a minimal commit_comment webhook payload for the given action."""
    return {
        "action": action,
        "repository": {"full_name": "owner/repo"},
        "comment": {
            "html_url": "https://github.com/owner/repo/commit/abc123#commitcomment-1",
            "body": "Please rename this variable",
            "commit_id": "abc1234def5678",
            "user": {"login": "bob"},
        },
    }


# ── Tests — supported actions ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pr_handler_opened_calls_send_fn():
    """
    Confirms that an 'opened' action results in send_embed_fn being called once.
    """
    received_embeds: list = []

    async def capturing_send_fn(payload, embed):
        received_embeds.append(embed)

    await handle_pr_event(_make_pr_payload("opened"), capturing_send_fn)

    assert len(received_embeds) == 1
    assert received_embeds[0] is not None


@pytest.mark.asyncio
async def test_pr_handler_review_requested_calls_send_fn():
    """
    Confirms that a 'review_requested' action results in send_embed_fn being called.
    """
    received_embeds: list = []

    async def capturing_send_fn(payload, embed):
        received_embeds.append(embed)

    await handle_pr_event(_make_pr_payload("review_requested"), capturing_send_fn)

    assert len(received_embeds) == 1


@pytest.mark.asyncio
async def test_pr_handler_closed_merged_calls_send_fn():
    """
    Confirms that a 'closed' action with merged=True calls send_embed_fn once.
    """
    received_embeds: list = []

    async def capturing_send_fn(payload, embed):
        received_embeds.append(embed)

    await handle_pr_event(_make_pr_payload("closed", is_merged=True), capturing_send_fn)

    assert len(received_embeds) == 1


@pytest.mark.asyncio
async def test_pr_handler_closed_without_merge_calls_send_fn():
    """
    Confirms that a 'closed' action with merged=False calls send_embed_fn once.
    """
    received_embeds: list = []

    async def capturing_send_fn(payload, embed):
        received_embeds.append(embed)

    await handle_pr_event(_make_pr_payload("closed", is_merged=False), capturing_send_fn)

    assert len(received_embeds) == 1


# ── Tests — unsupported / noisy actions ───────────────────────────────────────

@pytest.mark.asyncio
async def test_pr_handler_ignores_labeled_action():
    """
    Confirms that a 'labeled' action (not in our supported set) does NOT
    call send_embed_fn — we should not spam Discord with label changes.
    """
    received_embeds: list = []

    async def capturing_send_fn(payload, embed):
        received_embeds.append(embed)

    await handle_pr_event(_make_pr_payload("labeled"), capturing_send_fn)

    assert len(received_embeds) == 0


@pytest.mark.asyncio
async def test_pr_handler_ignores_synchronize_action():
    """
    Confirms that a 'synchronize' action (new commits pushed to an open PR)
    is silently skipped without raising or sending an embed.
    """
    received_embeds: list = []

    async def capturing_send_fn(payload, embed):
        received_embeds.append(embed)

    await handle_pr_event(_make_pr_payload("synchronize"), capturing_send_fn)

    assert len(received_embeds) == 0


@pytest.mark.asyncio
async def test_issue_handler_sends_embed_for_supported_action():
    """Confirms that an 'opened' issues action sends one embed."""
    received_embeds: list = []

    async def capturing_send_fn(payload, embed):
        received_embeds.append(embed)

    await handle_issue_event(_make_issue_payload("opened"), capturing_send_fn)

    assert len(received_embeds) == 1


@pytest.mark.asyncio
async def test_issue_handler_ignores_unsupported_action():
    """Confirms unsupported issue actions do not send embeds."""
    received_embeds: list = []

    async def capturing_send_fn(payload, embed):
        received_embeds.append(embed)

    await handle_issue_event(_make_issue_payload("pinned"), capturing_send_fn)

    assert len(received_embeds) == 0


@pytest.mark.asyncio
async def test_issue_comment_handler_sends_embed_for_supported_action():
    """Confirms created issue comments send one embed."""
    received_embeds: list = []

    async def capturing_send_fn(payload, embed):
        received_embeds.append(embed)

    await handle_issue_comment_event(
        _make_issue_comment_payload("created"),
        capturing_send_fn,
    )

    assert len(received_embeds) == 1


@pytest.mark.asyncio
async def test_issue_comment_handler_ignores_unsupported_action():
    """Confirms unsupported issue_comment actions do not send embeds."""
    received_embeds: list = []

    async def capturing_send_fn(payload, embed):
        received_embeds.append(embed)

    await handle_issue_comment_event(
        _make_issue_comment_payload("resolved"),
        capturing_send_fn,
    )

    assert len(received_embeds) == 0


@pytest.mark.asyncio
async def test_commit_comment_handler_sends_embed_for_supported_action():
    """Confirms created commit comments send one embed."""
    received_embeds: list = []

    async def capturing_send_fn(payload, embed):
        received_embeds.append(embed)

    await handle_commit_comment_event(
        _make_commit_comment_payload("created"),
        capturing_send_fn,
    )

    assert len(received_embeds) == 1


@pytest.mark.asyncio
async def test_commit_comment_handler_ignores_unsupported_action():
    """Confirms unsupported commit_comment actions do not send embeds."""
    received_embeds: list = []

    async def capturing_send_fn(payload, embed):
        received_embeds.append(embed)

    await handle_commit_comment_event(
        _make_commit_comment_payload("resolved"),
        capturing_send_fn,
    )

    assert len(received_embeds) == 0
