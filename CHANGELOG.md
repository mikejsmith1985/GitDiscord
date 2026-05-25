# Changelog — GitDiscord

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **NLP command parser** (`src/nlp/command_parser.py`): `parse_command()` pure function recognises list, view, create, comment, close, and unknown actions from natural-language Discord messages; `NlpMessageHandler` async class dispatches parsed commands to `GitHubClient` and replies with Discord embeds; `_normalize_issue_dict_for_embed()` bridges GitHubClient dict shape with `format_issue_dict()`; 46-test suite in `tests/nlp/test_command_parser.py`
- **NLP on_message wiring** (`src/bot/client.py`): `GitDiscordBot.on_message` routes guild messages through `NlpMessageHandler` while keeping prefix commands working via `process_commands()`
- Forge Workflow initialized with Forge Terminal Workflow Architect
- **Database layer** (`src/db/`): SQLAlchemy models for `ChannelRepoLink` (channel→repo mapping with PAT) and `NlpChannel`; full CRUD repository with upsert support
- **GitHub API client** (`src/github/client.py`): `GitHubClient` wrapping PyGithub — list, view, create, comment, and close issues; returns plain dicts for decoupled testability
- **Discord bot core** (`src/bot/client.py`): `GitDiscordBot` with slash-command extension loading, DB session context manager, and NLP message routing
- **Link/setup slash commands** (`src/bot/commands/link_commands.py`): `/link`, `/unlink`, `/status`, `/nlp-enable`, `/nlp-disable` — PAT never echoed
- **Issue slash commands** (`src/bot/commands/issue_commands.py`): `/issue list|view|create|comment|close` command group with ephemeral error handling
- **Discord embed formatters** (`src/formatters/discord_embeds.py`): rich embeds for push events, PR opened/merged/review-requested/closed, and issue views
- **FastAPI webhook server** (`src/webhooks/server.py`): HMAC-SHA256 GitHub signature validation, `GET /health` liveness probe, `POST /webhook/github` event receiver
- **Push event handler** (`src/webhooks/handlers/push_handler.py`): skips tag pushes and empty commit lists; formats branch pushes as Discord embeds
- **PR event handler** (`src/webhooks/handlers/pr_handler.py`): routes opened / review_requested / closed(merged) / closed(unmerged) to correct embed formatter
- **NLP command parser** (`src/nlp/command_parser.py`): regex-based parser recognising list/view/create/comment/close patterns; `NlpMessageHandler` for designated NLP channels
- **Config** (`src/config.py`): pydantic-settings `Settings` with `lru_cache` loader; validates required vars at startup
- **Entry point** (`src/main.py`): starts Discord bot and uvicorn webhook server concurrently via `asyncio.gather()`; handles Railway `PORT` injection
- **Deployment**: `Dockerfile`, `docker-compose.yml`, `railway.toml` for Railway one-click deploy or self-hosted Docker
- `README.md`: quick-start, Railway deploy steps, slash command reference, NLP mode examples, Docker/ngrok local dev, and architecture diagram

### Changed

### Fixed
- **Bot startup no longer requires privileged Discord intents by default** — Message Content Intent now stays off unless `ENABLE_MESSAGE_CONTENT_INTENT=true`, so slash commands and webhook notifications can start locally or on Railway without enabling privileged gateway access.
- **Local startup no longer fails opening SQLite** — The default database path now points to `./gitdiscord.db`, and SQLite parent folders are created automatically when a nested `DATABASE_PATH` is configured.

### Removed
