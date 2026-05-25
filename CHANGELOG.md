# Changelog — DiscordLink

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Forge Workflow initialized with Forge Terminal Workflow Architect
- FastAPI webhook server (`src/webhooks/server.py`) with HMAC-SHA256 GitHub signature validation, `GET /health` liveness probe, and `POST /webhook/github` event receiver
- Push event handler (`src/webhooks/handlers/push_handler.py`) formats push payloads as Discord embeds
- Pull-request event handler (`src/webhooks/handlers/pr_handler.py`) routes opened / review_requested / closed(merged) / closed(unmerged) actions to the correct Discord embed formatter
- Exported `create_webhook_app` and `start_webhook_server` from `src/webhooks/__init__.py`
- `src/config.py`: pydantic-settings `Settings` class with `lru_cache` loader for all environment variables
- `src/main.py`: application entry point that starts the Discord bot and uvicorn webhook server concurrently via `asyncio.gather()`
- `README.md`: quick-start guide, Railway deploy steps, slash command reference, NLP mode table, and architecture diagram

### Changed

### Fixed

### Removed
