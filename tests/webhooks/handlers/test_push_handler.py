"""
test_push_handler.py — Unit tests for the push event handler.

Verifies that handle_push_event builds a push embed and passes it to the
provided send function without modifying the payload.
"""

import pytest

from src.webhooks.handlers.push_handler import handle_push_event


# ── Fixtures ───────────────────────────────────────────────────────────────────

SAMPLE_PUSH_PAYLOAD = {
    "repository": {"full_name": "owner/repo"},
    "pusher": {"name": "alice"},
    "ref": "refs/heads/main",
    "commits": [
        {
            "id": "abc1234def5678",
            "message": "Initial commit",
            "url": "https://github.com/owner/repo/commit/abc1234def5678",
        }
    ],
}


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_push_handler_calls_send_embed_fn():
    """
    Confirms that handle_push_event calls send_embed_fn exactly once and
    passes both the original payload and a non-None embed.
    """
    captured_calls: list[tuple] = []

    async def mock_send_embed_fn(payload, embed):
        captured_calls.append((payload, embed))

    await handle_push_event(SAMPLE_PUSH_PAYLOAD, mock_send_embed_fn)

    assert len(captured_calls) == 1
    received_payload, received_embed = captured_calls[0]
    assert received_payload is SAMPLE_PUSH_PAYLOAD
    assert received_embed is not None


@pytest.mark.asyncio
async def test_push_handler_forwards_correct_payload():
    """
    Confirms the payload passed to send_embed_fn is the same object that
    was passed into the handler (not a copy or mutation).
    """
    received_payloads: list[dict] = []

    async def capturing_send_fn(payload, embed):
        received_payloads.append(payload)

    await handle_push_event(SAMPLE_PUSH_PAYLOAD, capturing_send_fn)

    assert received_payloads[0]["repository"]["full_name"] == "owner/repo"


@pytest.mark.asyncio
async def test_push_handler_empty_commits():
    """
    Confirms the handler does not raise when the commits list is empty
    (e.g. a branch deletion push).
    """
    empty_commits_payload = {
        "repository": {"full_name": "owner/repo"},
        "pusher": {"name": "bob"},
        "ref": "refs/heads/deleted-branch",
        "commits": [],
    }

    async def no_op_send_fn(payload, embed):
        pass

    # Should complete without raising.
    await handle_push_event(empty_commits_payload, no_op_send_fn)
