"""
Tests for Discord embed formatters in src/formatters/discord_embeds.py.

discord.py can be imported without a running bot, so real discord.Embed
objects are used rather than mocks — this lets us assert on the actual
embed fields, color values, and footer text.
"""

import pytest
import discord

from src.formatters.discord_embeds import (
    format_push_event,
    format_pr_opened,
    format_pr_review_requested,
    format_pr_merged,
    format_pr_closed_without_merge,
    format_pr_dict,
    format_issue_dict,
    format_issue_comment_event,
    format_commit_comment_event,
    MAX_COMMITS_SHOWN,
    MAX_BODY_PREVIEW_CHARS,
)

# ── Shared constants ──────────────────────────────────────────────────────────

# The footer text all embeds must carry for bot attribution.
EXPECTED_FOOTER_TEXT = "GitDiscord"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _build_push_payload(
    full_name: str = "myorg/myrepo",
    ref: str = "refs/heads/main",
    pusher_name: str = "alice",
    commits: list[dict] | None = None,
) -> dict:
    """Construct a minimal GitHub push webhook payload dict for testing."""
    return {
        "repository": {"full_name": full_name},
        "pusher": {"name": pusher_name},
        "ref": ref,
        "commits": commits if commits is not None else [],
    }


def _build_pr_payload(
    pr_title: str = "Add dark mode",
    pr_number: int = 99,
    html_url: str = "https://github.com/org/repo/pull/99",
    author_login: str = "bob",
    base_ref: str = "main",
    head_ref: str = "feature/dark-mode",
    body: str | None = "PR description text",
    merged: bool = False,
    merged_by_login: str | None = None,
    sender_login: str = "bob",
    requested_reviewer_login: str | None = None,
) -> dict:
    """Construct a minimal GitHub pull_request webhook payload dict for testing."""
    pull_request: dict = {
        "title": pr_title,
        "number": pr_number,
        "html_url": html_url,
        "user": {"login": author_login},
        "base": {"ref": base_ref},
        "head": {"ref": head_ref},
        "body": body,
        "merged": merged,
    }
    if merged_by_login:
        pull_request["merged_by"] = {"login": merged_by_login}
    else:
        pull_request["merged_by"] = None

    payload: dict = {
        "pull_request": pull_request,
        "sender": {"login": sender_login},
    }
    if requested_reviewer_login:
        payload["requested_reviewer"] = {"login": requested_reviewer_login}

    return payload


def _build_issue_dict(
    number: int = 3,
    title: str = "Something is broken",
    state: str = "open",
    body: str | None = "Steps to reproduce…",
    html_url: str = "https://github.com/org/repo/issues/3",
    labels: list[dict] | None = None,
) -> dict:
    """
    Construct an issue dict in the webhook/formatter format.

    Note: labels are dicts with a 'name' key, matching GitHub webhook format.
    """
    return {
        "number": number,
        "title": title,
        "state": state,
        "body": body,
        "html_url": html_url,
        "labels": labels if labels is not None else [],
    }


def _build_pr_dict(
    number: int = 99,
    title: str = "Add dark mode",
    state: str = "open",
    merged: bool = False,
    html_url: str = "https://github.com/org/repo/pull/99",
    author_login: str = "bob",
    base_ref: str = "main",
    head_ref: str = "feature/dark-mode",
    body: str | None = "PR description text",
    labels: list | None = None,
    merged_by_login: str | None = None,
) -> dict:
    """Construct a plain PR dict in the shape returned by GitHubClient."""
    return {
        "number": number,
        "title": title,
        "state": state,
        "merged": merged,
        "url": html_url,
        "user_login": author_login,
        "base_ref": base_ref,
        "head_ref": head_ref,
        "body": body,
        "labels": labels if labels is not None else [],
        "merged_by_login": merged_by_login,
    }


# ── format_push_event ─────────────────────────────────────────────────────────


class TestFormatPushEvent:
    """Tests for the format_push_event() formatter function."""

    def test_push_event_includes_repo_name_in_title(self):
        """format_push_event() puts the repository full name in the embed title."""
        payload = _build_push_payload(full_name="acme/backend")

        embed = format_push_event(payload)

        assert "acme/backend" in embed.title

    def test_push_event_strips_refs_heads_prefix_from_branch(self):
        """format_push_event() shows only the branch name, stripping 'refs/heads/' prefix."""
        payload = _build_push_payload(ref="refs/heads/feature/my-branch")

        embed = format_push_event(payload)

        assert "feature/my-branch" in embed.description
        assert "refs/heads/" not in embed.description

    def test_push_event_includes_commit_count(self):
        """format_push_event() shows the total number of commits in the description."""
        three_commits = [
            {"id": "abc1234", "message": "First", "url": "https://github.com/c/1"},
            {"id": "def5678", "message": "Second", "url": "https://github.com/c/2"},
            {"id": "ghi9012", "message": "Third", "url": "https://github.com/c/3"},
        ]
        payload = _build_push_payload(commits=three_commits)

        embed = format_push_event(payload)

        assert "3" in embed.description

    def test_push_event_includes_pusher_name(self):
        """format_push_event() includes the pusher's username in the description."""
        payload = _build_push_payload(pusher_name="carol")

        embed = format_push_event(payload)

        assert "carol" in embed.description

    def test_push_event_caps_commits_shown_at_max(self):
        """format_push_event() shows at most MAX_COMMITS_SHOWN commit lines."""
        many_commits = [
            {
                "id": f"{'a' * 6}{commit_index:02d}",
                "message": f"Commit {commit_index}",
                "url": f"https://github.com/org/repo/commit/{commit_index}",
            }
            for commit_index in range(MAX_COMMITS_SHOWN + 3)
        ]
        payload = _build_push_payload(commits=many_commits)

        embed = format_push_event(payload)

        # Count how many short SHA hyperlinks appear in the description.
        commit_line_count = embed.description.count("`aa")
        assert commit_line_count <= MAX_COMMITS_SHOWN
        # The "and N more" overflow notice must be present.
        assert "more commit" in embed.description

    def test_push_event_handles_empty_commits_list_gracefully(self):
        """format_push_event() does not raise when the commits list is empty."""
        payload = _build_push_payload(commits=[])

        embed = format_push_event(payload)

        assert embed is not None
        assert "0" in embed.description

    def test_push_event_handles_missing_pusher_gracefully(self):
        """format_push_event() falls back to 'unknown' when the pusher field is absent."""
        payload = _build_push_payload()
        del payload["pusher"]

        embed = format_push_event(payload)

        assert "unknown" in embed.description

    def test_push_event_has_blue_color(self):
        """format_push_event() uses discord.Color.blue() for the embed color."""
        payload = _build_push_payload()

        embed = format_push_event(payload)

        assert embed.color == discord.Color.blue()

    def test_push_event_has_gitdiscord_footer(self):
        """format_push_event() stamps the embed footer with 'GitDiscord'."""
        embed = format_push_event(_build_push_payload())

        assert embed.footer.text == EXPECTED_FOOTER_TEXT


# ── format_pr_opened ──────────────────────────────────────────────────────────


class TestFormatPrOpened:
    """Tests for the format_pr_opened() formatter function."""

    def test_pr_opened_includes_pr_title(self):
        """format_pr_opened() puts the PR title in the embed title."""
        payload = _build_pr_payload(pr_title="Refactor auth middleware")

        embed = format_pr_opened(payload)

        assert "Refactor auth middleware" in embed.title

    def test_pr_opened_includes_pr_number(self):
        """format_pr_opened() includes the PR number in the embed title."""
        payload = _build_pr_payload(pr_number=123)

        embed = format_pr_opened(payload)

        assert "123" in embed.title

    def test_pr_opened_includes_author_login(self):
        """format_pr_opened() shows the PR author's GitHub username in the description."""
        payload = _build_pr_payload(author_login="dave")

        embed = format_pr_opened(payload)

        assert "dave" in embed.description

    def test_pr_opened_has_green_color(self):
        """format_pr_opened() uses discord.Color.green() for the embed color."""
        embed = format_pr_opened(_build_pr_payload())

        assert embed.color == discord.Color.green()

    def test_pr_opened_has_gitdiscord_footer(self):
        """format_pr_opened() stamps the embed footer with 'GitDiscord'."""
        embed = format_pr_opened(_build_pr_payload())

        assert embed.footer.text == EXPECTED_FOOTER_TEXT

    def test_pr_opened_body_preview_is_truncated_to_max_chars(self):
        """format_pr_opened() truncates long PR bodies to MAX_BODY_PREVIEW_CHARS characters."""
        long_body = "x" * (MAX_BODY_PREVIEW_CHARS + 50)
        payload = _build_pr_payload(body=long_body)

        embed = format_pr_opened(payload)

        # The body content in the description must not exceed MAX_BODY_PREVIEW_CHARS + the ellipsis.
        assert len(long_body[:MAX_BODY_PREVIEW_CHARS]) <= MAX_BODY_PREVIEW_CHARS
        assert "…" in embed.description


# ── format_pr_review_requested ────────────────────────────────────────────────


class TestFormatPrReviewRequested:
    """Tests for the format_pr_review_requested() formatter function."""

    def test_pr_review_requested_includes_reviewer_login(self):
        """format_pr_review_requested() shows the requested reviewer's GitHub login."""
        payload = _build_pr_payload(requested_reviewer_login="eve")

        embed = format_pr_review_requested(payload)

        assert "eve" in embed.description

    def test_pr_review_requested_has_review_requested_title(self):
        """format_pr_review_requested() uses a fixed 'Review Requested' embed title."""
        embed = format_pr_review_requested(_build_pr_payload(requested_reviewer_login="frank"))

        assert "Review Requested" in embed.title

    def test_pr_review_requested_has_yellow_color(self):
        """format_pr_review_requested() uses discord.Color.yellow() for the embed color."""
        embed = format_pr_review_requested(_build_pr_payload(requested_reviewer_login="grace"))

        assert embed.color == discord.Color.yellow()

    def test_pr_review_requested_has_gitdiscord_footer(self):
        """format_pr_review_requested() stamps the embed footer with 'GitDiscord'."""
        embed = format_pr_review_requested(_build_pr_payload(requested_reviewer_login="henry"))

        assert embed.footer.text == EXPECTED_FOOTER_TEXT


# ── format_pr_merged ──────────────────────────────────────────────────────────


class TestFormatPrMerged:
    """Tests for the format_pr_merged() formatter function."""

    def test_pr_merged_has_correct_title(self):
        """format_pr_merged() uses 'Pull Request Merged' in the embed title."""
        embed = format_pr_merged(_build_pr_payload(merged=True, merged_by_login="alice"))

        assert "Merged" in embed.title

    def test_pr_merged_has_purple_color(self):
        """format_pr_merged() uses discord.Color.purple() for the embed color."""
        embed = format_pr_merged(_build_pr_payload(merged=True, merged_by_login="alice"))

        assert embed.color == discord.Color.purple()

    def test_pr_merged_includes_merged_by_login(self):
        """format_pr_merged() shows who merged the PR in the description."""
        embed = format_pr_merged(_build_pr_payload(merged=True, merged_by_login="ivan"))

        assert "ivan" in embed.description

    def test_pr_merged_has_gitdiscord_footer(self):
        """format_pr_merged() stamps the embed footer with 'GitDiscord'."""
        embed = format_pr_merged(_build_pr_payload(merged=True, merged_by_login="alice"))

        assert embed.footer.text == EXPECTED_FOOTER_TEXT


# ── format_pr_closed_without_merge ────────────────────────────────────────────


class TestFormatPrClosedWithoutMerge:
    """Tests for the format_pr_closed_without_merge() formatter function."""

    def test_pr_closed_has_correct_title(self):
        """format_pr_closed_without_merge() uses 'Pull Request Closed' in the embed title."""
        embed = format_pr_closed_without_merge(_build_pr_payload(sender_login="judy"))

        assert "Closed" in embed.title

    def test_pr_closed_has_red_color(self):
        """format_pr_closed_without_merge() uses discord.Color.red() for the embed color."""
        embed = format_pr_closed_without_merge(_build_pr_payload(sender_login="judy"))

        assert embed.color == discord.Color.red()

    def test_pr_closed_includes_closed_by_login(self):
        """format_pr_closed_without_merge() shows who closed the PR via the sender field."""
        embed = format_pr_closed_without_merge(_build_pr_payload(sender_login="kate"))

        assert "kate" in embed.description

    def test_pr_closed_has_gitdiscord_footer(self):
        """format_pr_closed_without_merge() stamps the embed footer with 'GitDiscord'."""
        embed = format_pr_closed_without_merge(_build_pr_payload(sender_login="kate"))

        assert embed.footer.text == EXPECTED_FOOTER_TEXT


# ── format_pr_dict ─────────────────────────────────────────────────────────────


class TestFormatPrDict:
    """Tests for the format_pr_dict() formatter function."""

    def test_open_pr_has_green_color(self):
        """Open PR references should use a green embed color."""
        embed = format_pr_dict(_build_pr_dict(state="open"))

        assert embed.color == discord.Color.green()

    def test_merged_pr_has_purple_color(self):
        """Merged PR references should use a purple embed color."""
        embed = format_pr_dict(_build_pr_dict(state="closed", merged=True))

        assert embed.color == discord.Color.purple()

    def test_closed_unmerged_pr_has_red_color(self):
        """Closed but unmerged PR references should use a red embed color."""
        embed = format_pr_dict(_build_pr_dict(state="closed", merged=False))

        assert embed.color == discord.Color.red()

    def test_pr_dict_includes_number_and_title_in_embed_title(self):
        """PR reference embeds should include the PR number and title."""
        embed = format_pr_dict(_build_pr_dict(number=17, title="Fix login flow"))

        assert "17" in embed.title
        assert "Fix login flow" in embed.title

    def test_pr_dict_includes_author_login_in_description(self):
        """PR reference embeds should include the author login."""
        embed = format_pr_dict(_build_pr_dict(author_login="alice"))

        assert "alice" in embed.description

    def test_pr_dict_includes_branch_relationship_in_description(self):
        """PR reference embeds should show the base and head branches."""
        embed = format_pr_dict(_build_pr_dict(base_ref="main", head_ref="feature/auth"))

        assert "`main` ← `feature/auth`" in embed.description

    def test_pr_dict_body_is_truncated_to_max_chars(self):
        """Long PR bodies should be truncated to keep embeds readable."""
        oversized_body = "p" * (MAX_BODY_PREVIEW_CHARS + 50)

        embed = format_pr_dict(_build_pr_dict(body=oversized_body))

        assert "…" in embed.description

    def test_pr_dict_handles_none_body_gracefully(self):
        """PR reference formatting should not fail when the PR body is empty."""
        embed = format_pr_dict(_build_pr_dict(body=None))

        assert embed is not None

    def test_pr_dict_displays_labels_when_present(self):
        """PR reference embeds should list labels when they are present."""
        embed = format_pr_dict(_build_pr_dict(labels=["bug", "P1"]))

        assert "bug" in embed.description
        assert "P1" in embed.description

    def test_pr_dict_sets_embed_url(self):
        """PR reference embeds should link directly to the GitHub PR."""
        embed = format_pr_dict(_build_pr_dict(html_url="https://github.com/org/repo/pull/17"))

        assert embed.url == "https://github.com/org/repo/pull/17"

    def test_pr_dict_accepts_html_url_key_fallback(self):
        """PR reference embeds should accept webhook-style html_url keys too."""
        pull_request = _build_pr_dict()
        pull_request["html_url"] = pull_request.pop("url")

        embed = format_pr_dict(pull_request)

        assert embed.url == "https://github.com/org/repo/pull/99"

    def test_pr_dict_has_gitdiscord_footer(self):
        """PR reference embeds should stamp the standard GitDiscord footer."""
        embed = format_pr_dict(_build_pr_dict())

        assert embed.footer.text == EXPECTED_FOOTER_TEXT


# ── format_issue_dict ─────────────────────────────────────────────────────────


class TestFormatIssueDict:
    """Tests for the format_issue_dict() formatter function."""

    def test_open_issue_has_gold_color(self):
        """format_issue_dict() uses discord.Color.gold() for issues with state='open'."""
        open_issue = _build_issue_dict(state="open")

        embed = format_issue_dict(open_issue, action="opened")

        assert embed.color == discord.Color.gold()

    def test_closed_issue_has_greyple_color(self):
        """format_issue_dict() uses discord.Color.greyple() for issues with state='closed'."""
        closed_issue = _build_issue_dict(state="closed")

        embed = format_issue_dict(closed_issue, action="closed")

        assert embed.color == discord.Color.greyple()

    def test_issue_dict_includes_issue_number_and_title(self):
        """format_issue_dict() puts the issue number and title in the embed title."""
        issue = _build_issue_dict(number=17, title="Fix null pointer crash")

        embed = format_issue_dict(issue, action="opened")

        assert "17" in embed.title
        assert "Fix null pointer crash" in embed.title

    def test_issue_dict_includes_action_in_title(self):
        """format_issue_dict() includes the action string (e.g. 'opened') in the embed title."""
        issue = _build_issue_dict(state="open")

        embed = format_issue_dict(issue, action="reopened")

        assert "reopened" in embed.title

    def test_issue_dict_body_is_truncated_to_max_chars(self):
        """format_issue_dict() truncates long issue bodies to MAX_BODY_PREVIEW_CHARS characters."""
        oversized_body = "y" * (MAX_BODY_PREVIEW_CHARS + 100)
        issue = _build_issue_dict(body=oversized_body, state="open")

        embed = format_issue_dict(issue, action="opened")

        assert "…" in embed.description

    def test_issue_dict_displays_labels_when_present(self):
        """format_issue_dict() lists label names in the description when the issue has labels."""
        issue = _build_issue_dict(
            state="open",
            labels=[{"name": "bug"}, {"name": "P1"}],
        )

        embed = format_issue_dict(issue, action="opened")

        assert "bug" in embed.description
        assert "P1" in embed.description

    def test_issue_dict_handles_empty_body_gracefully(self):
        """format_issue_dict() does not raise when the issue body is None or empty."""
        issue = _build_issue_dict(body=None, state="open")

        embed = format_issue_dict(issue, action="opened")

        assert embed is not None

    def test_issue_dict_has_gitdiscord_footer(self):
        """format_issue_dict() stamps the embed footer with 'GitDiscord'."""
        embed = format_issue_dict(_build_issue_dict(), action="opened")

        assert embed.footer.text == EXPECTED_FOOTER_TEXT

    def test_issue_dict_accepts_string_labels_from_github_client(self):
        """format_issue_dict() handles labels as plain strings (as returned by GitHubClient)."""
        # GitHubClient._issue_to_dict returns labels as a list of strings, not dicts.
        issue = {
            "number": 5,
            "title": "Client-sourced issue",
            "state": "open",
            "body": "",
            "html_url": "https://github.com/org/repo/issues/5",
            "labels": ["enhancement", "help wanted"],
        }

        embed = format_issue_dict(issue, action="opened")

        assert "enhancement" in embed.description
        assert "help wanted" in embed.description


# ── Comment event formatters ───────────────────────────────────────────────────


class TestFormatIssueCommentEvent:
    """Tests for format_issue_comment_event() formatter function."""

    def test_issue_comment_embed_includes_action_and_author(self):
        """Issue comment embeds show action and commenter for quick triage."""
        payload = {
            "action": "created",
            "issue": {"number": 4, "title": "Flaky test"},
            "comment": {
                "html_url": "https://github.com/org/repo/issues/4#issuecomment-1",
                "body": "I can reproduce this reliably.",
                "user": {"login": "alice"},
            },
        }

        embed = format_issue_comment_event(payload)

        assert "created" in embed.description
        assert "alice" in embed.description
        assert "Flaky test" in embed.description
        assert embed.url == "https://github.com/org/repo/issues/4#issuecomment-1"

    def test_issue_comment_embed_has_blurple_color_and_footer(self):
        """Issue comment embeds use blurple and include GitDiscord attribution."""
        payload = {
            "action": "edited",
            "issue": {"number": 11, "title": "Docs typo"},
            "comment": {"body": "Updated wording", "user": {"login": "bob"}},
        }

        embed = format_issue_comment_event(payload)

        assert embed.color == discord.Color.blurple()
        assert embed.footer.text == EXPECTED_FOOTER_TEXT


class TestFormatCommitCommentEvent:
    """Tests for format_commit_comment_event() formatter function."""

    def test_commit_comment_embed_includes_short_sha_and_author(self):
        """Commit comment embeds show the short commit SHA and author login."""
        payload = {
            "action": "created",
            "comment": {
                "commit_id": "abc1234def5678",
                "html_url": "https://github.com/org/repo/commit/abc1234#commitcomment-1",
                "body": "Please split this function.",
                "user": {"login": "carol"},
            },
        }

        embed = format_commit_comment_event(payload)

        assert "abc1234" in embed.description
        assert "carol" in embed.description
        assert embed.url == "https://github.com/org/repo/commit/abc1234#commitcomment-1"

    def test_commit_comment_embed_has_teal_color_and_footer(self):
        """Commit comment embeds use dark teal and include GitDiscord footer."""
        payload = {
            "action": "edited",
            "comment": {
                "commit_id": "def5678abc9012",
                "body": "Rephrased for clarity",
                "user": {"login": "dave"},
            },
        }

        embed = format_commit_comment_event(payload)

        assert embed.color == discord.Color.dark_teal()
        assert embed.footer.text == EXPECTED_FOOTER_TEXT
