"""
test_server.py — Unit tests for the FastAPI webhook server.

Covers signature validation, health check endpoint, event routing,
and the RuntimeError raised when WEBHOOK_SECRET is absent.
"""

import hashlib
import hmac
import json
import os

import pytest
from fastapi.testclient import TestClient

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

    class MockDiscordBot:
        """Minimal Discord bot stub that records channel.send() calls."""
        def get_channel(self, channel_id):
            return None  # No channel found — tests focus on routing, not sending

    class MockSession:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def scalars(self, query):
            return _MockScalars()

    class _MockScalars:
        def first(self):
            return None

    from contextlib import contextmanager

    @contextmanager
    def mock_session_factory():
        yield MockSession()

    app = create_webhook_app(MockDiscordBot(), mock_session_factory)
    return TestClient(app)


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
    body = json.dumps({"repository": {"full_name": "owner/repo"}}).encode()
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
    body = json.dumps({"repository": {"full_name": "owner/repo"}}).encode()
    response = client.post(
        "/webhook/github",
        content=body,
        headers={
            GITHUB_SIGNATURE_HEADER: _make_signature(body),
            GITHUB_EVENT_HEADER: "star",
        },
    )
    assert response.status_code == 200


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
