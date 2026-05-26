"""Tests for migration script: migrate_notification_links.py"""

import sqlite3
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_db():
    """Create a temporary SQLite database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    
    yield db_path
    
    # Cleanup
    Path(db_path).unlink(missing_ok=True)


def test_migrate_empty_database(temp_db):
    """Test migration on a database with no legacy links."""
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    
    # Create empty channel_repo_links table
    cursor.execute("""
        CREATE TABLE channel_repo_links (
            id INTEGER PRIMARY KEY,
            guild_id TEXT,
            channel_id TEXT,
            repo_owner TEXT,
            repo_name TEXT,
            github_pat TEXT,
            created_at DATETIME
        )
    """)
    conn.commit()
    conn.close()
    
    # Run migration
    from scripts.migrate_notification_links import migrate_channel_links
    migrate_channel_links(temp_db)
    
    # Verify notification_channel_links was created
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM notification_channel_links")
    count = cursor.fetchone()[0]
    assert count == 0, "Should have 0 notification links from empty legacy table"
    conn.close()


def test_migrate_with_legacy_links(temp_db):
    """Test migration copies legacy channel_repo_links."""
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    
    # Create and populate channel_repo_links
    cursor.execute("""
        CREATE TABLE channel_repo_links (
            id INTEGER PRIMARY KEY,
            guild_id TEXT,
            channel_id TEXT,
            repo_owner TEXT,
            repo_name TEXT,
            github_pat TEXT,
            created_at DATETIME
        )
    """)
    cursor.execute("""
        INSERT INTO channel_repo_links VALUES
        (1, '111', '222', 'owner1', 'repo1', 'pat1', '2026-05-01'),
        (2, '333', '444', 'owner2', 'repo2', 'pat2', '2026-05-02')
    """)
    conn.commit()
    conn.close()
    
    # Run migration
    from scripts.migrate_notification_links import migrate_channel_links
    migrate_channel_links(temp_db)
    
    # Verify notification_channel_links has the migrated data
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT repo_owner, repo_name, channel_id FROM notification_channel_links ORDER BY repo_owner")
    rows = cursor.fetchall()
    
    assert len(rows) == 2, "Should have 2 notification links"
    assert rows[0] == ('owner1', 'repo1', '222')
    assert rows[1] == ('owner2', 'repo2', '444')
    conn.close()


def test_migration_idempotent(temp_db):
    """Test that running migration twice doesn't create duplicates."""
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    
    # Create and populate channel_repo_links
    cursor.execute("""
        CREATE TABLE channel_repo_links (
            id INTEGER PRIMARY KEY,
            guild_id TEXT,
            channel_id TEXT,
            repo_owner TEXT,
            repo_name TEXT,
            github_pat TEXT,
            created_at DATETIME
        )
    """)
    cursor.execute("""
        INSERT INTO channel_repo_links VALUES
        (1, '111', '222', 'owner1', 'repo1', 'pat1', '2026-05-01')
    """)
    conn.commit()
    conn.close()
    
    # Run migration twice
    from scripts.migrate_notification_links import migrate_channel_links
    migrate_channel_links(temp_db)
    migrate_channel_links(temp_db)
    
    # Verify only one link (INSERT OR IGNORE prevents duplicates)
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM notification_channel_links")
    count = cursor.fetchone()[0]
    assert count == 1, "Should have exactly 1 notification link after running twice"
    conn.close()
