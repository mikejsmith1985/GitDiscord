#!/usr/bin/env python
"""
Migration script: Copy legacy channel_repo_links to notification_channel_links.

This helps users who had the old system configured but didn't use the new
/notifications link command. Running this script ensures both tables have
the same repo-to-channel mappings.
"""

import sqlite3
import sys


def migrate_channel_links(database_path: str) -> None:
    """Copy all channel_repo_links entries to notification_channel_links."""
    conn = sqlite3.connect(database_path)
    cursor = conn.cursor()

    try:
        # Create notification_channel_links table if it doesn't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notification_channel_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                repo_owner TEXT NOT NULL,
                repo_name TEXT NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(repo_owner, repo_name)
            )
        """)
        print("✓ notification_channel_links table ready")

        # Get all channel_repo_links
        cursor.execute("""
            SELECT guild_id, channel_id, repo_owner, repo_name 
            FROM channel_repo_links
        """)
        legacy_links = cursor.fetchall()

        if not legacy_links:
            print("No legacy channel_repo_links found. Nothing to migrate.")
            conn.close()
            return

        print(f"Found {len(legacy_links)} legacy channel-to-repo mappings.")

        # Insert into notification_channel_links (with conflict handling)
        for guild_id, channel_id, repo_owner, repo_name in legacy_links:
            cursor.execute("""
                INSERT OR IGNORE INTO notification_channel_links
                (guild_id, channel_id, repo_owner, repo_name)
                VALUES (?, ?, ?, ?)
            """, (guild_id, channel_id, repo_owner, repo_name))
            print(f"  ✓ Migrated: {repo_owner}/{repo_name} → channel {channel_id}")

        conn.commit()
        print("\n✓ Migration complete. Notification webhooks should now work for past issues.")

    except Exception as error:
        print(f"❌ Migration failed: {error}", file=sys.stderr)
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    import os
    from pathlib import Path

    db_path = os.environ.get("DATABASE_PATH", "./gitdiscord.db")
    if not Path(db_path).exists():
        print(f"❌ Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Migrating {db_path}...")
    migrate_channel_links(db_path)
