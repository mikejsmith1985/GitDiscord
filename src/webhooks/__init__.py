"""
webhooks/__init__.py — Public API for the GitDiscord webhook server package.

Exports the two entry points that main.py needs: the app factory and the
server starter.  Keeping them here means main.py never has to know about
the internal module layout.
"""

from .server import create_webhook_app, start_webhook_server

__all__ = [
    "create_webhook_app",
    "start_webhook_server",
]
