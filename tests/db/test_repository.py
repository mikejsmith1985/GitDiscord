"""
Tests for the database repository layer in src/db/repository.py.

Uses an in-memory SQLite database (not mocks) so the real SQLAlchemy
SQL behaviour is exercised — including upserts, uniqueness constraints,
and row-count returns for delete operations.
"""

import pytest
from sqlalchemy.orm import sessionmaker

from src.db.models import ChannelRepoLink, NlpChannel, get_engine, create_all_tables
from src.db.repository import (
    create_channel_link,
    get_channel_link,
    delete_channel_link,
    list_guild_links,
    enable_nlp_channel,
    is_nlp_channel,
    disable_nlp_channel,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def db_session():
    """
    Provide a fresh in-memory SQLite session for each test.

    The database is created, populated with the schema, and torn down within
    the fixture so every test starts with a completely empty database.
    """
    in_memory_engine = get_engine(":memory:")
    create_all_tables(in_memory_engine)
    SessionFactory = sessionmaker(bind=in_memory_engine)
    session = SessionFactory()
    yield session
    session.close()


# ── Shared test data constants ────────────────────────────────────────────────

# Realistic-looking Discord snowflake IDs for test clarity.
GUILD_ALPHA_ID = "111111111111111111"
GUILD_BETA_ID = "222222222222222222"
CHANNEL_ONE_ID = "333333333333333333"
CHANNEL_TWO_ID = "444444444444444444"
CHANNEL_THREE_ID = "555555555555555555"


# ── Engine helpers ────────────────────────────────────────────────────────────


def test_get_engine_creates_missing_sqlite_parent_directory(tmp_path):
    """get_engine() creates the database folder so first-run startup succeeds."""
    database_path = tmp_path / "nested" / "gitdiscord.db"

    database_engine = get_engine(str(database_path))
    create_all_tables(database_engine)

    assert database_path.exists()


# ── create_channel_link ───────────────────────────────────────────────────────


class TestCreateChannelLink:
    """Tests for the create_channel_link() repository function."""

    def test_create_channel_link_inserts_new_record(self, db_session):
        """create_channel_link() persists a new ChannelRepoLink row to the database."""
        created_link = create_channel_link(
            session=db_session,
            guild_id=GUILD_ALPHA_ID,
            channel_id=CHANNEL_ONE_ID,
            repo_owner="myorg",
            repo_name="backend",
            github_pat="ghp_secret1",
        )

        assert created_link is not None
        assert created_link.channel_id == CHANNEL_ONE_ID
        assert created_link.guild_id == GUILD_ALPHA_ID
        assert created_link.repo_owner == "myorg"
        assert created_link.repo_name == "backend"
        assert created_link.github_pat == "ghp_secret1"

    def test_create_channel_link_upserts_without_duplicate_on_second_call(self, db_session):
        """Calling create_channel_link() twice for the same channel_id updates, not duplicates."""
        create_channel_link(
            session=db_session,
            guild_id=GUILD_ALPHA_ID,
            channel_id=CHANNEL_ONE_ID,
            repo_owner="myorg",
            repo_name="backend",
            github_pat="ghp_original_token",
        )

        # Re-link the same channel to a different repo with a rotated PAT.
        updated_link = create_channel_link(
            session=db_session,
            guild_id=GUILD_ALPHA_ID,
            channel_id=CHANNEL_ONE_ID,
            repo_owner="myorg",
            repo_name="frontend",
            github_pat="ghp_rotated_token",
        )

        assert updated_link.repo_name == "frontend"
        assert updated_link.github_pat == "ghp_rotated_token"

        # Confirm only one row exists — not two.
        all_links = list_guild_links(db_session, GUILD_ALPHA_ID)
        assert len(all_links) == 1


# ── get_channel_link ──────────────────────────────────────────────────────────


class TestGetChannelLink:
    """Tests for the get_channel_link() repository function."""

    def test_get_channel_link_returns_link_for_known_channel(self, db_session):
        """get_channel_link() returns the correct ChannelRepoLink for a registered channel."""
        create_channel_link(
            session=db_session,
            guild_id=GUILD_ALPHA_ID,
            channel_id=CHANNEL_ONE_ID,
            repo_owner="acme",
            repo_name="api",
            github_pat="ghp_test",
        )

        fetched_link = get_channel_link(db_session, CHANNEL_ONE_ID)

        assert fetched_link is not None
        assert fetched_link.channel_id == CHANNEL_ONE_ID
        assert fetched_link.repo_owner == "acme"

    def test_get_channel_link_returns_none_for_unknown_channel(self, db_session):
        """get_channel_link() returns None when no link exists for the given channel_id."""
        result = get_channel_link(db_session, "nonexistent-channel-id")

        assert result is None


# ── delete_channel_link ───────────────────────────────────────────────────────


class TestDeleteChannelLink:
    """Tests for the delete_channel_link() repository function."""

    def test_delete_channel_link_removes_record_and_returns_true(self, db_session):
        """delete_channel_link() deletes an existing link and returns True."""
        create_channel_link(
            session=db_session,
            guild_id=GUILD_ALPHA_ID,
            channel_id=CHANNEL_ONE_ID,
            repo_owner="org",
            repo_name="repo",
            github_pat="ghp_delete_test",
        )

        was_deleted = delete_channel_link(db_session, CHANNEL_ONE_ID)

        assert was_deleted is True
        # Verify the row is truly gone.
        assert get_channel_link(db_session, CHANNEL_ONE_ID) is None

    def test_delete_channel_link_returns_false_for_non_existent_channel(self, db_session):
        """delete_channel_link() returns False when no link exists for the given channel_id."""
        was_deleted = delete_channel_link(db_session, "channel-that-was-never-linked")

        assert was_deleted is False


# ── list_guild_links ──────────────────────────────────────────────────────────


class TestListGuildLinks:
    """Tests for the list_guild_links() repository function."""

    def test_list_guild_links_returns_all_links_for_the_requested_guild(self, db_session):
        """list_guild_links() returns every link registered under a given guild_id."""
        create_channel_link(
            session=db_session,
            guild_id=GUILD_ALPHA_ID,
            channel_id=CHANNEL_ONE_ID,
            repo_owner="org",
            repo_name="repo-one",
            github_pat="ghp_a",
        )
        create_channel_link(
            session=db_session,
            guild_id=GUILD_ALPHA_ID,
            channel_id=CHANNEL_TWO_ID,
            repo_owner="org",
            repo_name="repo-two",
            github_pat="ghp_b",
        )

        guild_alpha_links = list_guild_links(db_session, GUILD_ALPHA_ID)

        assert len(guild_alpha_links) == 2
        returned_channel_ids = {link.channel_id for link in guild_alpha_links}
        assert returned_channel_ids == {CHANNEL_ONE_ID, CHANNEL_TWO_ID}

    def test_list_guild_links_does_not_return_links_from_other_guilds(self, db_session):
        """list_guild_links() filters strictly by guild_id and omits other guilds' links."""
        create_channel_link(
            session=db_session,
            guild_id=GUILD_ALPHA_ID,
            channel_id=CHANNEL_ONE_ID,
            repo_owner="org",
            repo_name="repo-alpha",
            github_pat="ghp_alpha",
        )
        create_channel_link(
            session=db_session,
            guild_id=GUILD_BETA_ID,
            channel_id=CHANNEL_TWO_ID,
            repo_owner="org",
            repo_name="repo-beta",
            github_pat="ghp_beta",
        )

        guild_beta_links = list_guild_links(db_session, GUILD_BETA_ID)

        assert len(guild_beta_links) == 1
        assert guild_beta_links[0].guild_id == GUILD_BETA_ID

    def test_list_guild_links_returns_empty_list_for_guild_with_no_links(self, db_session):
        """list_guild_links() returns an empty list when the guild has no registered channels."""
        result = list_guild_links(db_session, "guild-with-no-links")

        assert result == []


# ── enable_nlp_channel ────────────────────────────────────────────────────────


class TestEnableNlpChannel:
    """Tests for the enable_nlp_channel() repository function."""

    def test_enable_nlp_channel_inserts_record(self, db_session):
        """enable_nlp_channel() creates a new NlpChannel row for the given channel."""
        nlp_channel = enable_nlp_channel(
            session=db_session,
            guild_id=GUILD_ALPHA_ID,
            channel_id=CHANNEL_ONE_ID,
        )

        assert nlp_channel is not None
        assert nlp_channel.channel_id == CHANNEL_ONE_ID
        assert nlp_channel.guild_id == GUILD_ALPHA_ID

    def test_enable_nlp_channel_is_idempotent_on_duplicate_call(self, db_session):
        """enable_nlp_channel() called twice for the same channel does not raise or duplicate."""
        enable_nlp_channel(
            session=db_session,
            guild_id=GUILD_ALPHA_ID,
            channel_id=CHANNEL_ONE_ID,
        )
        # Second call for the same channel must not raise.
        second_result = enable_nlp_channel(
            session=db_session,
            guild_id=GUILD_ALPHA_ID,
            channel_id=CHANNEL_ONE_ID,
        )

        assert second_result is not None
        assert second_result.channel_id == CHANNEL_ONE_ID


# ── is_nlp_channel ────────────────────────────────────────────────────────────


class TestIsNlpChannel:
    """Tests for the is_nlp_channel() repository function."""

    def test_is_nlp_channel_returns_true_when_enabled(self, db_session):
        """is_nlp_channel() returns True for a channel that has NLP enabled."""
        enable_nlp_channel(
            session=db_session,
            guild_id=GUILD_ALPHA_ID,
            channel_id=CHANNEL_ONE_ID,
        )

        result = is_nlp_channel(db_session, CHANNEL_ONE_ID)

        assert result is True

    def test_is_nlp_channel_returns_false_when_not_enabled(self, db_session):
        """is_nlp_channel() returns False for a channel that has never had NLP enabled."""
        result = is_nlp_channel(db_session, "never-enabled-channel-id")

        assert result is False


# ── disable_nlp_channel ───────────────────────────────────────────────────────


class TestDisableNlpChannel:
    """Tests for the disable_nlp_channel() repository function."""

    def test_disable_nlp_channel_removes_record_and_returns_true(self, db_session):
        """disable_nlp_channel() removes an NLP record and returns True when the channel was enabled."""
        enable_nlp_channel(
            session=db_session,
            guild_id=GUILD_ALPHA_ID,
            channel_id=CHANNEL_ONE_ID,
        )

        was_disabled = disable_nlp_channel(db_session, CHANNEL_ONE_ID)

        assert was_disabled is True
        # Confirm NLP is no longer active for this channel.
        assert is_nlp_channel(db_session, CHANNEL_ONE_ID) is False

    def test_disable_nlp_channel_returns_false_for_channel_never_enabled(self, db_session):
        """disable_nlp_channel() returns False when the channel was not in the NLP list."""
        was_disabled = disable_nlp_channel(db_session, "channel-nlp-was-never-enabled")

        assert was_disabled is False
