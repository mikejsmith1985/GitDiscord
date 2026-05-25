"""
test_pr_handler.py — Unit tests for the pull-request event handler.

Verifies that handle_pr_event routes each supported action to send_embed_fn
and silently ignores unsupported actions without raising.
"""

import pytest

from src.webhooks.handlers.pr_handler import handle_pr_event


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
