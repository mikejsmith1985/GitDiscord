# Changelog — GitDiscord

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Inline pull request reference detection** (`src/nlp/command_parser.py`, `src/github/client.py`, `src/formatters/discord_embeds.py`): NLP-enabled channels now detect `pr #123`, `gh pr #123`, `github PR #123`, and `pull request #123` references in normal conversation and reply with a clickable pull request embed.
- **Signed webhook delivery diagnostics** (`src/webhooks/server.py`): Signed webhook tests can now include `X-GitDiscord-Debug: true` to return the exact delivery outcome (`sent`, `no_repo_link`, `channel_not_found`, etc.) in the response body, turning GitHub delivery logs into hard evidence instead of a generic HTTP 200.
- **Webhook diagnostic logging and endpoint** (`src/webhooks/server.py`, `src/webhooks/handlers/pr_handler.py`): Enhanced issue webhook handler with detailed tracing of issue numbers and actions; channel lookup now logs whether a notification or legacy command-channel link is used; added `/debug/channels/{channel_id}` diagnostic endpoint to verify bot visibility and send permissions in Discord channels
- **Legacy-to-notification channel migration script** (`scripts/migrate_notification_links.py`): Helper utility for existing GitDiscord users to migrate `channel_repo_links` entries to the new `notification_channel_links` table, ensuring webhooks are delivered to the correct channels for repos configured with the old `/link` command
- **Issue/comment webhook notifications** (`src/webhooks/server.py`, `src/webhooks/handlers/issue_handler.py`, `src/formatters/discord_embeds.py`): GitHub `issues`, `issue_comment`, and `commit_comment` events are now routed to Discord notification channels with dedicated embeds for issue lifecycle updates and discussion activity.
- **Inline issue reference detection** (`src/nlp/command_parser.py`): NLP channels now detect issue references embedded in normal conversation text (for example, `gh issue #123` or `issue #123`) and automatically reply with a clickable issue embed, reusing the existing issue-view response flow.
- **Separated command and notification channels** (`src/bot/commands/link_commands.py`, `src/webhooks/server.py`, `src/db/`): Added `/notifications link|unlink|status` so GitHub webhook events can be routed to a dedicated feed channel while `/issue` commands continue to run in a separate command channel. Webhooks now prefer the notification-channel mapping and fall back to the legacy command-channel mapping for backward compatibility.
- **Recoverable adaptive build jobs** (`.github/skills/adaptive-build-environments/SKILL.md`): Documents `detach: true` support in `forge-vault-environment_run`, which starts a background job and returns a `job_id` immediately. New tools `forge-vault-environment_jobs` (list all persistent jobs) and `forge-vault-environment_read_job` (recover output and status by ID) are now described with full usage examples. Jobs persist in `~/.forge/adaptive-build-jobs/` across Forge restarts so builds that exceed a session timeout can always be recovered.

- **Thread-based issue drafts** (`src/bot/commands/issue_commands.py`): `/issue create-thread` collects recent messages from the current thread, preserves authorship and order, and turns the discussion into a GitHub issue draft for review.

### Fixed
- **`/status` detached SQLAlchemy rows** (`src/main.py`): Session factory now uses `expire_on_commit=False`, preventing `DetachedInstanceError` when status embeds read linked repository fields after DB session commit.
- **NLP GitHub App authentication** (`src/nlp/command_parser.py`): Natural-language issue and PR lookups now use the configured GitHub App credentials instead of the removed personal-access-token constructor path.
- **Cold Discord channel cache drops** (`src/webhooks/server.py`): Webhook delivery now falls back from `discord_bot.get_channel()` to `discord_bot.fetch_channel()` so GitHub events are not silently dropped when Railway accepts webhooks before Discord's gateway cache is fully warm.
- **Public channel diagnostics safety** (`src/webhooks/server.py`): `/debug/channels/{channel_id}` now stays cache-only so unauthenticated diagnostic requests cannot consume Discord API rate limits, and permission reporting tolerates a cold guild-member cache.
- **Database path default** (`src/config.py`): Changed default `DATABASE_PATH` from `./gitdiscord.db` to `./data/gitdiscord.db` so the container's `appuser` can write the SQLite file — the container only has write access to `/app/data`, not `/app`

### Fixed
- **Railway start command** (`railway.toml`): Changed `python src/main.py` to `python -m src.main` to fix `ModuleNotFoundError: No module named 'src'` on startup — running the file directly set Python's module search path to `/app/src` instead of `/app`, breaking all internal imports

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
- **GitHub issue commands now use GitHub App installation auth** — `/link` no longer collects a PAT; API calls are authenticated with `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, and `GITHUB_APP_INSTALLATION_ID`.

### Fixed
- **GitHub App errors now pinpoint the failing configuration step** — `/issue` commands now report whether failure is app credential parsing, repo installation mismatch, or installation token creation.
- **`/issue` commands no longer fail on detached SQLAlchemy link rows** — repo owner/name are copied before session close, preventing “not bound to a Session” runtime errors.
- **`/issue` commands now return explicit auth/setup errors instead of timing out** — GitHub App client creation failures are surfaced as ephemeral messages so Discord no longer shows “The application did not respond.”
- **Slash-command sync diagnostics now show exactly what Discord accepted** — Startup logs include local command names and guild sync results so setup issues can be separated from Discord channel permissions.
- **Slash commands now sync immediately to connected Discord servers** — Startup copies the command tree to each guild and syncs once, so `/link`, `/status`, and issue commands appear without waiting for global command propagation.
- **Bot startup no longer requires privileged Discord intents by default** — Message Content Intent now stays off unless `ENABLE_MESSAGE_CONTENT_INTENT=true`, so slash commands and webhook notifications can start locally or on Railway without enabling privileged gateway access.
- **Local startup no longer fails opening SQLite** — The default database path now points to `./gitdiscord.db`, and SQLite parent folders are created automatically when a nested `DATABASE_PATH` is configured.

### Removed
