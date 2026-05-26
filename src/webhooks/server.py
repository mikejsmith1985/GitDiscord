"""
server.py — FastAPI webhook server for the GitDiscord bot.

Exposes two HTTP endpoints:
    GET  /health          — liveness check consumed by Railway / Docker healthchecks
    POST /webhook/github  — receives all GitHub webhook deliveries

Every inbound webhook is validated against an HMAC-SHA256 signature derived
from the WEBHOOK_SECRET environment variable before any business logic runs.
Validated events are routed to the appropriate handler (push, pull_request,
issues, issue_comment, commit_comment) which formats a Discord embed and sends
it to the linked channel.
"""

import hashlib
import hmac
import json
import logging
import os
from collections.abc import Callable
from typing import Any

import discord
import uvicorn
from fastapi import FastAPI, Request, Response
from sqlalchemy.orm import Session

from src.db import repository
from src.webhooks.handlers.pr_handler import (
    handle_commit_comment_event,
    handle_issue_comment_event,
    handle_issue_event,
    handle_pr_event,
)
from src.webhooks.handlers.push_handler import handle_push_event

logger = logging.getLogger(__name__)

# ── Module-level constants ──────────────────────────────────────────────────────

# Header names exactly as GitHub sends them.
GITHUB_SIGNATURE_HEADER = "X-Hub-Signature-256"
GITHUB_EVENT_HEADER = "X-GitHub-Event"
GITDISCORD_DEBUG_HEADER = "X-GitDiscord-Debug"

# Prefix GitHub prepends to the hex-encoded HMAC digest.
_SIGNATURE_PREFIX = "sha256="

# HTTP status codes used in this module kept as named constants for clarity.
_HTTP_UNAUTHORIZED = 401
_HTTP_OK = 200

# Delivery outcome strings are stable because they are surfaced in diagnostic
# webhook responses and GitHub delivery logs.
_DELIVERY_REASON_SENT = "sent"
_DELIVERY_REASON_INVALID_REPO = "invalid_repo_full_name"
_DELIVERY_REASON_NO_REPO_LINK = "no_repo_link"
_DELIVERY_REASON_CHANNEL_NOT_FOUND = "channel_not_found"
_DELIVERY_REASON_INVALID_CHANNEL_ID = "invalid_channel_id"
_DELIVERY_REASON_NOT_ROUTED = "not_routed"
_DELIVERY_ROUTE_NOTIFICATION = "notification_channel_links"
_DELIVERY_ROUTE_LEGACY = "channel_repo_links"


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


def _build_delivery_outcome(
    *,
    was_delivered: bool,
    reason: str,
    repo_full_name: str = "",
    route: str | None = None,
    channel_id: str | None = None,
) -> dict[str, Any]:
    """Create a compact delivery result for logs and signed debug responses."""
    return {
        "was_delivered": was_delivered,
        "reason": reason,
        "repo_full_name": repo_full_name,
        "route": route,
        "channel_id": channel_id,
    }


async def _resolve_discord_channel(
    discord_bot: Any,
    channel_id: str,
    repo_full_name: str,
) -> Any | None:
    """
    Resolve a Discord channel from cache first, then the API when the cache is cold.

    GitHub can deliver webhooks immediately after a restart, before discord.py's
    gateway cache is fully warm. Fetching the channel from Discord avoids losing
    notifications during that startup race.
    """
    numeric_channel_id = int(channel_id)
    discord_channel = discord_bot.get_channel(numeric_channel_id)
    if discord_channel is not None:
        return discord_channel

    fetch_channel = getattr(discord_bot, "fetch_channel", None)
    if fetch_channel is None:
        return None

    try:
        return await fetch_channel(numeric_channel_id)
    except discord.DiscordException as discord_error:
        logger.warning(
            "discord_bot.fetch_channel failed for channel_id=%s (repo=%s): %s",
            channel_id,
            repo_full_name,
            discord_error,
        )
        return None


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

    # ── Diagnostic endpoint ────────────────────────────────────────────────────

    @app.get("/debug/channels/{channel_id}")
    async def debug_channel(channel_id: str):
        """Check whether the bot can resolve and send embeds to a Discord channel."""
        try:
            channel = await _resolve_discord_channel(discord_bot, channel_id, "debug")
        except ValueError as value_error:
            return {
                "status": "error",
                "channel_id": channel_id,
                "error": str(value_error),
            }

        if channel is None:
            return {
                "status": "error",
                "channel_id": channel_id,
                "issue": "Bot cannot see this channel. It may not be a member or the channel ID is invalid.",
            }

        channel_permissions = (
            channel.permissions_for(channel.guild.me) if channel.guild else None
        )
        return {
            "status": "ok",
            "channel_id": channel_id,
            "channel_name": channel.name,
            "guild_id": str(channel.guild.id) if channel.guild else None,
            "can_send": channel_permissions.send_messages if channel_permissions else None,
            "can_embed": channel_permissions.embed_links if channel_permissions else None,
        }

    # ── Channel send helper ─────────────────────────────────────────────────────

    async def _channel_send_fn(payload: dict, embed) -> dict[str, Any]:
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
            return _build_delivery_outcome(
                was_delivered=False,
                reason=_DELIVERY_REASON_INVALID_REPO,
                repo_full_name=repo_full_name,
            )

        # The DB stores owner and name in separate columns, so we split the
        # full_name string to query them individually.
        repo_owner, repo_name = repo_full_name.split("/", maxsplit=1)
        logger.debug(
            "Looking up channel link for %s/%s", repo_owner, repo_name
        )

        with db_session_factory() as session:
            notification_channel_link = repository.get_notification_channel_link(
                session,
                repo_owner,
                repo_name,
            )
            if notification_channel_link is not None:
                channel_id = notification_channel_link.channel_id
                delivery_route = _DELIVERY_ROUTE_NOTIFICATION
                logger.info(
                    "Found notification channel link: %s → %s", repo_full_name, channel_id
                )
            else:
                logger.debug(
                    "No notification channel link found; checking legacy channel_repo_links"
                )
                channel_link = repository.get_channel_link_for_repo(
                    session,
                    repo_owner,
                    repo_name,
                )
                if channel_link is None:
                    logger.warning(
                        "No Discord channel linked to repository %s — embed not sent.",
                        repo_full_name,
                    )
                    return _build_delivery_outcome(
                        was_delivered=False,
                        reason=_DELIVERY_REASON_NO_REPO_LINK,
                        repo_full_name=repo_full_name,
                    )
                channel_id = channel_link.channel_id
                delivery_route = _DELIVERY_ROUTE_LEGACY
                logger.info(
                    "Found legacy channel link: %s → %s", repo_full_name, channel_id
                )

        try:
            discord_channel = await _resolve_discord_channel(
                discord_bot,
                channel_id,
                repo_full_name,
            )
        except ValueError:
            logger.warning(
                "Stored channel_id=%s for repository %s is not a valid Discord ID.",
                channel_id,
                repo_full_name,
            )
            return _build_delivery_outcome(
                was_delivered=False,
                reason=_DELIVERY_REASON_INVALID_CHANNEL_ID,
                repo_full_name=repo_full_name,
                route=delivery_route,
                channel_id=channel_id,
            )

        if discord_channel is None:
            logger.warning(
                "Could not resolve Discord channel_id=%s for repo=%s. "
                "The bot may not be a member of that channel.",
                channel_id,
                repo_full_name,
            )
            return _build_delivery_outcome(
                was_delivered=False,
                reason=_DELIVERY_REASON_CHANNEL_NOT_FOUND,
                repo_full_name=repo_full_name,
                route=delivery_route,
                channel_id=channel_id,
            )

        await discord_channel.send(embed=embed)
        logger.info(
            "✓ Sent embed to channel_id=%s for repository %s",
            channel_id,
            repo_full_name,
        )
        return _build_delivery_outcome(
            was_delivered=True,
            reason=_DELIVERY_REASON_SENT,
            repo_full_name=repo_full_name,
            route=delivery_route,
            channel_id=channel_id,
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
        logger.info("━━ Received GitHub webhook event: %s ━━", event_type.upper())

        payload: dict = await request.json()
        delivery_outcome = _build_delivery_outcome(
            was_delivered=False,
            reason=_DELIVERY_REASON_NOT_ROUTED,
            repo_full_name=payload.get("repository", {}).get("full_name", ""),
        )

        async def tracked_channel_send_fn(
            tracked_payload: dict,
            tracked_embed: Any,
        ) -> dict[str, Any]:
            """Capture whether a routed webhook actually reached Discord."""
            nonlocal delivery_outcome
            delivery_outcome = await _channel_send_fn(tracked_payload, tracked_embed)
            return delivery_outcome

        if event_type == "push":
            await handle_push_event(payload, tracked_channel_send_fn)
        elif event_type == "pull_request":
            await handle_pr_event(payload, tracked_channel_send_fn)
        elif event_type == "issues":
            await handle_issue_event(payload, tracked_channel_send_fn)
        elif event_type == "issue_comment":
            await handle_issue_comment_event(payload, tracked_channel_send_fn)
        elif event_type == "commit_comment":
            await handle_commit_comment_event(payload, tracked_channel_send_fn)
        else:
            # Return 200 for unrecognised events so GitHub does not retry them.
            logger.debug("Ignoring unsupported GitHub event type: %s", event_type)

        response_body = {"received": True}
        should_include_debug_response = (
            request.headers.get(GITDISCORD_DEBUG_HEADER, "").lower() == "true"
        )
        if should_include_debug_response:
            response_body["delivery"] = delivery_outcome

        return Response(
            content=json.dumps(response_body),
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
