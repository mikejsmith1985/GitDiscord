"""
server.py — FastAPI webhook server for the GitDiscord bot.

Exposes two HTTP endpoints:
    GET  /health          — liveness check consumed by Railway / Docker healthchecks
    POST /webhook/github  — receives all GitHub webhook deliveries

Every inbound webhook is validated against an HMAC-SHA256 signature derived
from the WEBHOOK_SECRET environment variable before any business logic runs.
Validated events are routed to the appropriate handler (push, pull_request)
which formats a Discord embed and sends it to the linked channel.
"""

import hashlib
import hmac
import logging
import os
from collections.abc import Callable, Awaitable
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import ChannelRepoLink
from src.webhooks.handlers.push_handler import handle_push_event
from src.webhooks.handlers.pr_handler import handle_pr_event

logger = logging.getLogger(__name__)

# ── Module-level constants ──────────────────────────────────────────────────────

# Header names exactly as GitHub sends them.
GITHUB_SIGNATURE_HEADER = "X-Hub-Signature-256"
GITHUB_EVENT_HEADER = "X-GitHub-Event"

# Prefix GitHub prepends to the hex-encoded HMAC digest.
_SIGNATURE_PREFIX = "sha256="

# HTTP status codes used in this module kept as named constants for clarity.
_HTTP_UNAUTHORIZED = 401
_HTTP_OK = 200


# ── Signature validation ────────────────────────────────────────────────────────

def _validate_github_signature(raw_body: bytes, signature_header: str, webhook_secret: str) -> bool:
    """
    Verify that a GitHub webhook signature matches the expected HMAC-SHA256 digest.

    GitHub computes HMAC-SHA256 over the raw request body using the shared
    webhook secret and sends the result as "sha256=<hex>" in the
    X-Hub-Signature-256 header.  We recompute the digest and compare using
    hmac.compare_digest to prevent timing-based attacks.

    Args:
        raw_body:         The unmodified bytes of the request body.
        signature_header: Value of the X-Hub-Signature-256 header.
        webhook_secret:   The shared secret configured in GitHub and this server.

    Returns:
        True if the signature is valid, False if it is absent or wrong.
    """
    if not signature_header or not signature_header.startswith(_SIGNATURE_PREFIX):
        return False

    expected_digest = hmac.new(
        webhook_secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    # Use compare_digest so the comparison takes constant time regardless of
    # how many leading bytes match — this closes a timing-oracle side channel.
    received_hex = signature_header[len(_SIGNATURE_PREFIX):]
    return hmac.compare_digest(expected_digest, received_hex)


# ── App factory ─────────────────────────────────────────────────────────────────

def create_webhook_app(discord_bot: Any, db_session_factory: Callable[[], Session]) -> FastAPI:
    """
    Create and configure the FastAPI application for receiving GitHub webhooks.

    This factory pattern injects the Discord bot and DB session factory as
    closure variables so the route handlers can access them without relying on
    global state or FastAPI's dependency-injection system (which doesn't work
    well with the discord.py event loop).

    The function validates at startup that WEBHOOK_SECRET is set; if it is
    missing the server would accept unsigned requests from anyone, so we raise
    immediately rather than silently running in an insecure configuration.

    Args:
        discord_bot:         The discord.py Client (or Bot) instance used to
                             fetch channels and send embeds.
        db_session_factory:  A zero-argument callable that returns an open
                             SQLAlchemy Session.  Typically a contextmanager
                             such as sessionmaker(engine).

    Returns:
        A configured FastAPI instance ready to be passed to start_webhook_server.

    Raises:
        RuntimeError: If the WEBHOOK_SECRET environment variable is not set.
    """
    webhook_secret = os.environ.get("WEBHOOK_SECRET")
    if not webhook_secret:
        raise RuntimeError(
            "WEBHOOK_SECRET environment variable is not set. "
            "The webhook server cannot start without it because all inbound "
            "requests would be accepted without signature verification."
        )

    app = FastAPI(title="GitDiscord Webhook Server", version="1.0.0")

    # ── Health check ────────────────────────────────────────────────────────────

    @app.get("/health")
    async def health_check():
        """
        Liveness probe endpoint.

        Returns a minimal JSON body that deployment platforms (Railway, Docker,
        Kubernetes) can poll to confirm the server is alive and accepting requests.
        """
        return {"status": "ok", "service": "gitdiscord"}

    # ── Channel send helper ─────────────────────────────────────────────────────

    async def _channel_send_fn(payload: dict, embed) -> None:
        """
        Resolve the target Discord channel from the payload and send an embed.

        Looks up the channel_repo_links table using the repository's full name
        (owner/repo) from the webhook payload.  If a linked channel is found,
        the embed is posted there.  If no link exists, a warning is logged and
        the embed is silently dropped — this avoids errors for repositories that
        are tracked in GitHub but not yet configured in a Discord channel.

        Args:
            payload: The parsed webhook JSON — must contain payload["repository"]["full_name"].
            embed:   A discord.Embed object ready to be posted.
        """
        repo_full_name: str = payload.get("repository", {}).get("full_name", "")

        if not repo_full_name or "/" not in repo_full_name:
            logger.warning(
                "Webhook payload is missing a valid repository.full_name; cannot route embed."
            )
            return

        # The DB stores owner and name in separate columns, so we split the
        # full_name string to query them individually.
        repo_owner, repo_name = repo_full_name.split("/", maxsplit=1)

        with db_session_factory() as session:
            query = select(ChannelRepoLink).where(
                ChannelRepoLink.repo_owner == repo_owner,
                ChannelRepoLink.repo_name == repo_name,
            )
            channel_link: ChannelRepoLink | None = session.scalars(query).first()

        if channel_link is None:
            logger.warning(
                "No Discord channel linked to repository %s — embed not sent.",
                repo_full_name,
            )
            return

        discord_channel = discord_bot.get_channel(int(channel_link.channel_id))
        if discord_channel is None:
            logger.warning(
                "discord_bot.get_channel returned None for channel_id=%s (repo=%s). "
                "The bot may not be a member of that channel.",
                channel_link.channel_id,
                repo_full_name,
            )
            return

        await discord_channel.send(embed=embed)
        logger.debug(
            "Sent embed to channel_id=%s for repository %s",
            channel_link.channel_id,
            repo_full_name,
        )

    # ── GitHub webhook receiver ─────────────────────────────────────────────────

    @app.post("/webhook/github")
    async def receive_github_webhook(request: Request) -> Response:
        """
        Receive and process all incoming GitHub webhook deliveries.

        Security flow:
            1. Read the raw request body (must be done before any parsing).
            2. Validate the HMAC-SHA256 signature in X-Hub-Signature-256.
            3. Parse the JSON payload.
            4. Route to the correct event handler based on X-GitHub-Event.

        Unknown event types return HTTP 200 (not 4xx) because GitHub treats
        any non-200 response as a delivery failure and schedules a retry,
        which would cause duplicate embeds when support for that event is added.
        """
        raw_body = await request.body()
        signature_header = request.headers.get(GITHUB_SIGNATURE_HEADER, "")

        is_signature_valid = _validate_github_signature(raw_body, signature_header, webhook_secret)
        if not is_signature_valid:
            logger.warning(
                "Rejected webhook: invalid or missing %s header.", GITHUB_SIGNATURE_HEADER
            )
            return Response(
                content='{"error": "invalid signature"}',
                status_code=_HTTP_UNAUTHORIZED,
                media_type="application/json",
            )

        event_type = request.headers.get(GITHUB_EVENT_HEADER, "unknown")
        logger.info("Received GitHub webhook event: %s", event_type)

        payload: dict = await request.json()

        if event_type == "push":
            await handle_push_event(payload, _channel_send_fn)
        elif event_type == "pull_request":
            await handle_pr_event(payload, _channel_send_fn)
        else:
            # Return 200 for unrecognised events so GitHub does not retry them.
            logger.debug("Ignoring unsupported GitHub event type: %s", event_type)

        return Response(
            content='{"received": true}',
            status_code=_HTTP_OK,
            media_type="application/json",
        )

    return app


# ── Server entrypoint ───────────────────────────────────────────────────────────

def start_webhook_server(app: FastAPI, port: int) -> None:
    """
    Start the uvicorn ASGI server hosting the FastAPI webhook application.

    This is a blocking call intended for use in main.py when running the
    webhook server in its own thread or process alongside the Discord bot.

    Args:
        app:  The FastAPI application returned by create_webhook_app().
        port: TCP port number the server will bind to (e.g. 8080).
    """
    logger.info("Starting webhook server on port %d", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
