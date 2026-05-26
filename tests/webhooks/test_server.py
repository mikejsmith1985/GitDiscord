"""
test_server.py — Unit tests for the FastAPI webhook server.

Covers signature validation, health check endpoint, event routing,
and the RuntimeError raised when WEBHOOK_SECRET is absent.
"""

import hashlib
import hmac
import json
import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from src.db.models import (
    ChannelRepoLink,
    NotificationChannelLink,
    create_all_tables,
    get_engine,
)
from src.webhooks.server import (
    create_webhook_app,
    GITHUB_SIGNATURE_HEADER,
    GITHUB_EVENT_HEADER,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

_TEST_SECRET = "test-webhook-secret-abc123"


def _make_signature(body: bytes, secret: str = _TEST_SECRET) -> str:
    """Compute a valid GitHub-style HMAC-SHA256 signature for the given body."""
    digest = hmac.new(secret.encode("utf-8"), msg=body, digestmod=hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _build_test_app(monkeypatch):
    """
    Create a TestClient-wrapped webhook app with WEBHOOK_SECRET set.

    Uses a mock Discord bot and DB session factory so no real external
    connections are made during tests.
    """
    monkeypatch.setenv("WEBHOOK_SECRET", _TEST_SECRET)

    from contextlib import contextmanager

    temporary_database_folder = tempfile.mkdtemp(prefix="gitdiscord-webhook-tests-")
    temporary_database_path = os.path.join(temporary_database_folder, "webhooks.db")
    database_engine = get_engine(temporary_database_path)
    create_all_tables(database_engine)
    session_factory = sessionmaker(bind=database_engine)

    @contextmanager
    def mock_session_factory():
        database_session = session_factory()
        try:
            yield database_session
        finally:
            database_session.close()

    class MockDiscordBot:
        """Minimal Discord bot stub that records channel.send() calls."""

        def get_channel(self, channel_id):
            return None  # No channel found — tests focus on routing, not sending

    app = create_webhook_app(MockDiscordBot(), mock_session_factory)
    return TestClient(app)


def _build_routing_test_client(
    monkeypatch,
    *,
    command_link: dict | None = None,
    notification_link: dict | None = None,
):
    """Create a TestClient with seeded command and notification links."""
    monkeypatch.setenv("WEBHOOK_SECRET", _TEST_SECRET)

    from contextlib import contextmanager

    temporary_database_folder = tempfile.mkdtemp(prefix="gitdiscord-routing-tests-")
    temporary_database_path = os.path.join(temporary_database_folder, "routing.db")
    database_engine = get_engine(temporary_database_path)
    create_all_tables(database_engine)
    session_factory = sessionmaker(bind=database_engine)

    with session_factory() as seeded_session:
        if command_link is not None:
            seeded_session.add(
                ChannelRepoLink(
                    guild_id=command_link["guild_id"],
                    channel_id=command_link["channel_id"],
                    repo_owner=command_link["repo_owner"],
                    repo_name=command_link["repo_name"],
                    github_pat="GITHUB_APP_AUTH",
                )
            )
        if notification_link is not None:
            seeded_session.add(
                NotificationChannelLink(
                    guild_id=notification_link["guild_id"],
                    channel_id=notification_link["channel_id"],
                    repo_owner=notification_link["repo_owner"],
                    repo_name=notification_link["repo_name"],
                )
            )
        seeded_session.commit()

    class MockDiscordChannel:
        """Capture Discord send calls for a single channel."""

        def __init__(self) -> None:
            from unittest.mock import AsyncMock

            self.send = AsyncMock()

    class MockDiscordBot:
        """Discord bot stub that resolves known channels by ID."""

        def __init__(self, channels_by_id):
            self._channels_by_id = channels_by_id

        def get_channel(self, channel_id):
            return self._channels_by_id.get(channel_id)

    @contextmanager
    def mock_session_factory():
        database_session = session_factory()
        try:
            yield database_session
        finally:
            database_session.close()

    channels_by_id = {}
    command_channel = None
    notification_channel = None
    if command_link is not None:
        command_channel = MockDiscordChannel()
        channels_by_id[int(command_link["channel_id"])] = command_channel
    if notification_link is not None:
        notification_channel = MockDiscordChannel()
        channels_by_id[int(notification_link["channel_id"])] = notification_channel

    app = create_webhook_app(MockDiscordBot(channels_by_id), mock_session_factory)
    return TestClient(app), command_channel, notification_channel


# ── Health check ───────────────────────────────────────────────────────────────

def test_health_check_returns_ok(monkeypatch):
    """Confirms GET /health returns HTTP 200 with the expected body."""
    client = _build_test_app(monkeypatch)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "gitdiscord"}


# ── Signature validation ───────────────────────────────────────────────────────

def test_webhook_rejects_missing_signature(monkeypatch):
    """Confirms POST /webhook/github returns 401 when X-Hub-Signature-256 is absent."""
    client = _build_test_app(monkeypatch)
    response = client.post(
        "/webhook/github",
        content=b'{"action": "ping"}',
        headers={GITHUB_EVENT_HEADER: "ping"},
    )
    assert response.status_code == 401


def test_webhook_rejects_wrong_signature(monkeypatch):
    """Confirms POST /webhook/github returns 401 when the signature is wrong."""
    client = _build_test_app(monkeypatch)
    body = b'{"action": "ping"}'
    response = client.post(
        "/webhook/github",
        content=body,
        headers={
            GITHUB_SIGNATURE_HEADER: "sha256=deadbeefdeadbeef",
            GITHUB_EVENT_HEADER: "ping",
        },
    )
    assert response.status_code == 401


def test_webhook_accepts_valid_signature(monkeypatch):
    """Confirms POST /webhook/github returns 200 for a correctly signed request."""
    client = _build_test_app(monkeypatch)
    body = json.dumps(
        {
            "repository": {"full_name": "owner/repo"},
            "ref": "refs/heads/main",
            "commits": [{"id": "abc123", "message": "test commit"}],
        }
    ).encode()
    response = client.post(
        "/webhook/github",
        content=body,
        headers={
            GITHUB_SIGNATURE_HEADER: _make_signature(body),
            GITHUB_EVENT_HEADER: "push",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"received": True}


# ── Event routing ──────────────────────────────────────────────────────────────

def test_webhook_returns_200_for_unknown_event(monkeypatch):
    """
    Confirms unknown event types return 200 (not 4xx) so GitHub does not
    schedule a retry delivery.
    """
    client = _build_test_app(monkeypatch)
    body = json.dumps(
        {
            "repository": {"full_name": "owner/repo"},
            "ref": "refs/heads/main",
            "commits": [{"id": "abc123", "message": "test commit"}],
        }
    ).encode()
    response = client.post(
        "/webhook/github",
        content=body,
        headers={
            GITHUB_SIGNATURE_HEADER: _make_signature(body),
            GITHUB_EVENT_HEADER: "star",
        },
    )
    assert response.status_code == 200


# ── Notification routing ────────────────────────────────────────────────────────


def test_webhook_sends_notifications_to_dedicated_channel(monkeypatch):
    """Confirms webhook delivery prefers the configured notification channel."""
    client, command_channel, notification_channel = _build_routing_test_client(
        monkeypatch,
        command_link={
            "guild_id": "1",
            "channel_id": "111111111111111111",
            "repo_owner": "owner",
            "repo_name": "repo",
        },
        notification_link={
            "guild_id": "1",
            "channel_id": "222222222222222222",
            "repo_owner": "owner",
            "repo_name": "repo",
        },
    )
    body = json.dumps(
        {
            "repository": {"full_name": "owner/repo"},
            "ref": "refs/heads/main",
            "commits": [{"id": "abc123", "message": "test commit"}],
        }
    ).encode()

    response = client.post(
        "/webhook/github",
        content=body,
        headers={
            GITHUB_SIGNATURE_HEADER: _make_signature(body),
            GITHUB_EVENT_HEADER: "push",
        },
    )

    assert response.status_code == 200
    assert notification_channel is not None
    assert command_channel is not None
    assert notification_channel.send.await_count == 1
    assert command_channel.send.await_count == 0


def test_webhook_falls_back_to_command_channel_when_no_notification_channel_is_set(monkeypatch):
    """Confirms legacy channel delivery still works when no notification channel exists yet."""
    client, command_channel, notification_channel = _build_routing_test_client(
        monkeypatch,
        command_link={
            "guild_id": "1",
            "channel_id": "111111111111111111",
            "repo_owner": "owner",
            "repo_name": "repo",
        },
    )
    body = json.dumps(
        {
            "repository": {"full_name": "owner/repo"},
            "ref": "refs/heads/main",
            "commits": [{"id": "abc123", "message": "test commit"}],
        }
    ).encode()

    response = client.post(
        "/webhook/github",
        content=body,
        headers={
            GITHUB_SIGNATURE_HEADER: _make_signature(body),
            GITHUB_EVENT_HEADER: "push",
        },
    )

    assert response.status_code == 200
    assert command_channel is not None
    assert command_channel.send.await_count == 1
    assert notification_channel is None


# ── Startup safety ─────────────────────────────────────────────────────────────

def test_create_webhook_app_raises_without_secret(monkeypatch):
    """
    Confirms create_webhook_app() raises RuntimeError when WEBHOOK_SECRET
    is not set, preventing the server from starting in an insecure state.
    """
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)

    class StubBot:
        pass

    from contextlib import contextmanager

    @contextmanager
    def stub_session_factory():
        yield None

    with pytest.raises(RuntimeError, match="WEBHOOK_SECRET"):
        create_webhook_app(StubBot(), stub_session_factory)
