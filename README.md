# GitDiscord

> Bidirectional Discord ↔ GitHub integration. Get PR and commit notifications in Discord, and manage GitHub issues directly from chat.

## Features

- **GitHub → Discord**: Push commits, PR lifecycle events, issue lifecycle updates, issue comments, and commit comments posted as rich embeds
- **Discord → GitHub**: Full issue management via slash commands and thread-based issue drafts
- **Split channel routing**: Keep issue commands in one channel and send webhook notifications to another
- **Natural language**: Type `create issue: Fix login bug` or `show issue #5` in designated channels
- **Multi-repo**: Each Discord channel can link to a different GitHub repo
- **Railway-ready**: One-click deploy from GitHub, public webhook URL included

## Quick Start (Local)

1. **Create a Discord bot** at [discord.com/developers](https://discord.com/developers/applications)
   - Enable **Message Content Intent** under Privileged Gateway Intents
   - Invite with scopes: `bot`, `applications.commands` and permissions: Send Messages, Embed Links, Read Message History
   - Copy the Bot Token

2. **Clone and configure**
   ```bash
   git clone https://github.com/mikejsmith1985/GitDiscord.git
   cd GitDiscord
   cp .env.example .env
   # Edit .env with your Discord token, webhook secret, and GitHub App credentials
   ```

3. **Install and run**
   ```bash
   pip install -r requirements.txt
   python src/main.py
   ```

   Keep `ENABLE_MESSAGE_CONTENT_INTENT=false` unless you explicitly enable
   Discord's Message Content Intent in the Developer Portal. Slash commands and
   GitHub webhook notifications do not need that privileged gateway intent.

## Deploy to Railway

1. Push this repo to GitHub (already done)
2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo** → select `GitDiscord`
3. Set environment variables in Railway dashboard (copy from `.env.example`)
4. Railway provides a public URL, e.g. `https://gitdiscord-production.up.railway.app`
5. In your GitHub repo → **Settings → Webhooks → Add webhook**:
   - Payload URL: `https://<railway-url>/webhook/github`
   - Content type: `application/json`
   - Secret: your `WEBHOOK_SECRET` value
   - Events: select **Pushes**, **Pull requests**, **Issues**, **Issue comments**, and **Commit comments**

## Slash Commands

| Command | Description |
|---------|-------------|
| `/link <repo>` | Link this channel to a GitHub repo (`owner/repo`) using configured GitHub App auth |
| `/help` | Show a full in-Discord guide for setup, issue commands, notifications, and NLP examples |
| `/help-public` | Post a pin-ready help message in the channel (non-ephemeral) |
| `/unlink` | Remove this channel's repo link |
| `/status` | Show issue-command and notification routing for this channel |
| `/notifications link <repo>` | Send GitHub webhook notifications for a repo to this channel |
| `/notifications unlink <repo>` | Stop sending a repo's GitHub notifications to this channel |
| `/notifications status` | Show which repos currently notify this channel |
| `/nlp-enable` | Enable natural language commands in this channel |
| `/nlp-disable` | Disable natural language commands |
| `/issue list [open\|closed]` | List issues |
| `/issue view <number>` | View a specific issue |
| `/issue create <title> [body]` | Create a new issue |
| `/issue create-thread` | Create an issue from the current thread discussion |
| `/issue comment <number> <text>` | Add a comment |
| `/issue close <number>` | Close an issue |

## Natural Language (NLP Mode)

After running `/nlp-enable` in a channel, you can type plain English:

NLP mode requires `ENABLE_MESSAGE_CONTENT_INTENT=true` and the matching
privileged intent enabled for the bot in the Discord Developer Portal.

| You type | Action |
|----------|--------|
| `list issues` | List open issues |
| `show issue #5` | View issue #5 |
| `please reference gh issue #123` | Auto-resolve and post issue #123 as a clickable embed |
| `create issue: Fix login bug` | Create a new issue |
| `comment on issue #5: looks good` | Add a comment |
| `close issue #5` | Close issue #5 |

## Local Development with Docker

```bash
docker compose up --build
```

For GitHub webhooks during local dev, use [ngrok](https://ngrok.com):
```bash
ngrok http 8080
# Set GitHub webhook URL to: https://<ngrok-url>/webhook/github
```

## Architecture

```
GitHub ──webhook POST──► FastAPI (port 8080) ──► Discord channel
Discord slash command ──► discord.py bot     ──► GitHub API ──► Discord reply
Discord NLP message  ──► NLP parser          ──► GitHub API ──► Discord reply
```

Both processes run on the same asyncio event loop via `asyncio.gather()`.
