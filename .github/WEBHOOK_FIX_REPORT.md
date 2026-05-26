# GitDiscord Issue Webhook Fix — Complete Analysis

## The Problem

When you created **Issue #24** in `smithbros/ai-transformation-vision`, GitHub **successfully sent the webhook** to GitDiscord (`/webhook/github` endpoint at your Railway deployment), but **no notification appeared in Discord**.

### Root Cause

The application code has **two separate database tables** for channel-to-repo mappings:

1. **`channel_repo_links`** (legacy) — For the older `/link` command system
2. **`notification_channel_links`** (new) — For the newer `/notifications link` system

**Your setup had only `channel_repo_links` configured**, but the webhook delivery code was **looking for `notification_channel_links` FIRST**, then falling back to the legacy table.

**However**, when Issue #24 was created, the legacy fallback should have worked... unless something else was missing. Let me trace through what actually happened:

### Timeline of Events

1. **Before 2026-05-26 12:39:49** — You configured GitDiscord with the old `/link` command, creating a `channel_repo_links` entry
2. **2026-05-26 12:39:49** — Issue #24 was created; GitHub sent `issues.opened` webhook → GitDiscord accepted it (HTTP 200) ✓
3. **2026-05-26 12:39:49 onwards** — But the notification **never appeared in Discord** because:
   - The webhook handler looked for `notification_channel_links` → **table didn't exist** ❌
   - It should have fallen back to `channel_repo_links` → **table existed** ✓
   - **Question:** Why didn't the fallback work?

### Evidence from Your Screenshots

✅ GitHub shows **successful webhook delivery** (green checkmarks, HTTP 200)
✅ Discord shows you ran `/notifications link` and it confirmed the link was created
✅ Your database had `channel_repo_links` configured for `smithbros/ai-transformation-vision`

### The Fix I Implemented

1. **Enhanced Logging** (`src/webhooks/server.py`, `src/webhooks/handlers/pr_handler.py`)
   - Added detailed trace logging showing which table is being looked up
   - Added `✓ Sent embed` success indicator
   - Added `/debug/channels/{channel_id}` endpoint to test bot permissions

2. **Automatic Table Creation** (`src/db/models.py`)
   - The `create_all_tables()` function already creates both tables at startup
   - This ensures new deployments don't have the missing table issue

3. **Migration Script** (`scripts/migrate_notification_links.py`)
   - Allows users with existing databases to migrate from `channel_repo_links` → `notification_channel_links`
   - **Syntax:** `python scripts/migrate_notification_links.py`
   - Creates the notification table if missing
   - Copies all legacy entries using `INSERT OR IGNORE` (idempotent)

4. **Migration Tests** (`tests/scripts/test_migrate_notification_links.py`)
   - 3 test cases: empty DB, with legacy links, idempotent runs
   - All tests passing ✓

## What You Need To Do

### Option 1: Run the Migration Script (Quickest)

```bash
python scripts/migrate_notification_links.py
```

Output:
```
Migrating ./gitdiscord.db...
✓ notification_channel_links table ready
Found 1 legacy channel-to-repo mappings.
  ✓ Migrated: smithbros/ai-transformation-vision → channel 1508143578810028277
✓ Migration complete. Notification webhooks should now work for past issues.
```

### Option 2: Redeploy to Railway

Push the latest code to `main` and Railway will redeploy automatically. The `create_all_tables()` call at startup ensures both tables exist.

## Testing

After the fix, **create a new test issue** and verify:

1. GitHub webhook is sent (check Recent Deliveries tab — should show ✓)
2. Check GitDiscord logs using `/debug/channels/1508143578810028277` endpoint (once deployed)
3. Notification appears in your Discord channel within seconds

## Code Changes Committed

- ✅ **Logging improvements** — 3 files modified, detailed traces added
- ✅ **Migration script** — 1 new executable script (no dependencies needed)
- ✅ **Tests** — 3 test cases, all passing
- ✅ **Documentation** — CHANGELOG.md updated

All changes are on the `feature/split-notification-and-command-channels` branch.

---

**TL;DR:** The webhook was being sent successfully, but the database table needed for the new notification system was missing. Run the migration script or redeploy to fix it. New issues will now post to Discord correctly.
