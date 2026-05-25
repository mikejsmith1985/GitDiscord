"""
test_command_parser.py — Unit tests for the NLP command parser.

Tests cover the pure parse_command() function across all supported actions
and their edge cases (case insensitivity, optional punctuation, multi-line
bodies, and fallback to ACTION_UNKNOWN for unrecognised input).
"""

import pytest

from src.nlp.command_parser import (
    parse_command,
    ParsedCommand,
    ACTION_LIST,
    ACTION_VIEW,
    ACTION_CREATE,
    ACTION_COMMENT,
    ACTION_CLOSE,
    ACTION_UNKNOWN,
    STATE_OPEN,
    STATE_CLOSED,
)


# ── LIST action ────────────────────────────────────────────────────────────────

class TestListAction:
    """Tests for 'list issues' natural-language variants."""

    def test_list_issues_returns_list_action(self):
        """'list issues' is the canonical form and must resolve to ACTION_LIST."""
        result = parse_command("list issues")
        assert result.action == ACTION_LIST

    def test_show_issues_resolves_to_list(self):
        """'show issues' is an accepted synonym for listing."""
        result = parse_command("show issues")
        assert result.action == ACTION_LIST

    def test_list_defaults_to_open_state(self):
        """Without an explicit state modifier, the list should default to open issues."""
        result = parse_command("list issues")
        assert result.state_filter == STATE_OPEN

    def test_show_open_issues_returns_open_state(self):
        """An explicit 'open' modifier must set state_filter to STATE_OPEN."""
        result = parse_command("show open issues")
        assert result.action == ACTION_LIST
        assert result.state_filter == STATE_OPEN

    def test_list_closed_issues_returns_closed_state(self):
        """An explicit 'closed' modifier must set state_filter to STATE_CLOSED."""
        result = parse_command("list closed issues")
        assert result.action == ACTION_LIST
        assert result.state_filter == STATE_CLOSED

    def test_open_issues_standalone_shorthand(self):
        """'open issues' (adjective-as-verb) must resolve to list with open state."""
        result = parse_command("open issues")
        assert result.action == ACTION_LIST
        assert result.state_filter == STATE_OPEN

    def test_closed_issues_standalone_shorthand(self):
        """'closed issues' (adjective-as-verb) must resolve to list with closed state."""
        result = parse_command("closed issues")
        assert result.action == ACTION_LIST
        assert result.state_filter == STATE_CLOSED

    def test_list_issues_case_insensitive(self):
        """Regex matching must be case-insensitive for all list variants."""
        result = parse_command("LIST ISSUES")
        assert result.action == ACTION_LIST

    def test_list_issue_singular_accepted(self):
        """'list issue' (no trailing s) should still be recognised as list."""
        result = parse_command("list issue")
        assert result.action == ACTION_LIST

    def test_leading_trailing_whitespace_stripped(self):
        """Extra whitespace around the message must not prevent matching."""
        result = parse_command("  list issues  ")
        assert result.action == ACTION_LIST


# ── VIEW action ────────────────────────────────────────────────────────────────

class TestViewAction:
    """Tests for 'view issue' natural-language variants."""

    def test_show_issue_with_hash_and_number(self):
        """'show issue #5' is the canonical view form."""
        result = parse_command("show issue #5")
        assert result.action == ACTION_VIEW
        assert result.issue_number == 5

    def test_issue_hash_and_number_bare(self):
        """'issue #5' (no verb) must resolve to ACTION_VIEW."""
        result = parse_command("issue #5")
        assert result.action == ACTION_VIEW
        assert result.issue_number == 5

    def test_view_issue_number_without_hash(self):
        """'view issue 5' (no # symbol) must still extract the number correctly."""
        result = parse_command("view issue 5")
        assert result.action == ACTION_VIEW
        assert result.issue_number == 5

    def test_issue_number_without_hash_bare(self):
        """'issue 5' (no verb, no hash) must resolve to ACTION_VIEW."""
        result = parse_command("issue 5")
        assert result.action == ACTION_VIEW
        assert result.issue_number == 5

    def test_hash_number_shorthand(self):
        """'#5' alone is the shortest supported view shorthand."""
        result = parse_command("#5")
        assert result.action == ACTION_VIEW
        assert result.issue_number == 5

    def test_view_issue_extracts_large_number(self):
        """Issue numbers with many digits must be extracted correctly."""
        result = parse_command("issue #12345")
        assert result.action == ACTION_VIEW
        assert result.issue_number == 12_345

    def test_view_issue_case_insensitive(self):
        """'SHOW ISSUE #5' must still match (case-insensitive regex)."""
        result = parse_command("SHOW ISSUE #5")
        assert result.action == ACTION_VIEW
        assert result.issue_number == 5


# ── CREATE action ──────────────────────────────────────────────────────────────

class TestCreateAction:
    """Tests for 'create issue' natural-language variants."""

    def test_create_issue_extracts_title(self):
        """'create issue: Fix login bug' must extract the title after the colon."""
        result = parse_command("create issue: Fix login bug")
        assert result.action == ACTION_CREATE
        assert result.title == "Fix login bug"

    def test_new_issue_variant(self):
        """'new issue: Add dark mode' is an accepted create synonym."""
        result = parse_command("new issue: Add dark mode")
        assert result.action == ACTION_CREATE
        assert result.title == "Add dark mode"

    def test_open_issue_variant(self):
        """'open issue: Something' mirrors GitHub's own UI language for create."""
        result = parse_command("open issue: Something")
        assert result.action == ACTION_CREATE
        assert result.title == "Something"

    def test_create_issue_trims_title_whitespace(self):
        """Extra spaces after the colon must be stripped from the extracted title."""
        result = parse_command("create issue:   Leading spaces in title")
        assert result.action == ACTION_CREATE
        assert result.title == "Leading spaces in title"

    def test_create_issue_no_body_returns_none_body(self):
        """A single-line create command must leave the body field as None."""
        result = parse_command("create issue: Title only")
        assert result.body is None

    def test_create_issue_multiline_separates_title_and_body(self):
        """A newline in the content must split title from the optional body."""
        message_text = "create issue: Fix login bug\nThis is the detailed description."
        result = parse_command(message_text)
        assert result.action == ACTION_CREATE
        assert result.title == "Fix login bug"
        assert result.body == "This is the detailed description."

    def test_create_issue_multiline_body_preserves_newlines(self):
        """Multi-paragraph bodies must preserve internal newlines after the first."""
        message_text = "create issue: New feature\nLine one.\nLine two."
        result = parse_command(message_text)
        assert result.title == "New feature"
        assert result.body == "Line one.\nLine two."

    def test_create_issue_case_insensitive(self):
        """'CREATE ISSUE: ...' must still match."""
        result = parse_command("CREATE ISSUE: All caps command")
        assert result.action == ACTION_CREATE
        assert result.title == "All caps command"


# ── COMMENT action ─────────────────────────────────────────────────────────────

class TestCommentAction:
    """Tests for 'comment on issue' natural-language variants."""

    def test_comment_on_issue_full_form(self):
        """'comment on issue #5: looks good' is the canonical comment form."""
        result = parse_command("comment on issue #5: looks good")
        assert result.action == ACTION_COMMENT
        assert result.issue_number == 5
        assert result.comment_text == "looks good"

    def test_comment_number_terse_form(self):
        """'comment #5: needs work' (no 'on issue') must also be accepted."""
        result = parse_command("comment #5: needs work")
        assert result.action == ACTION_COMMENT
        assert result.issue_number == 5
        assert result.comment_text == "needs work"

    def test_comment_trims_whitespace_from_text(self):
        """Whitespace after the colon must be stripped from the comment text."""
        result = parse_command("comment #5:   Text with leading spaces")
        assert result.comment_text == "Text with leading spaces"

    def test_comment_issue_without_hash(self):
        """'comment on issue 10: text' (no # symbol) must extract number correctly."""
        result = parse_command("comment on issue 10: LGTM")
        assert result.action == ACTION_COMMENT
        assert result.issue_number == 10
        assert result.comment_text == "LGTM"

    def test_comment_multiline_body_supported(self):
        """Multi-line comment bodies must be captured in their entirety."""
        message_text = "comment #5: First line\nSecond line"
        result = parse_command(message_text)
        assert result.action == ACTION_COMMENT
        assert result.comment_text == "First line\nSecond line"

    def test_comment_case_insensitive(self):
        """'COMMENT ON ISSUE #5: text' must match (case-insensitive)."""
        result = parse_command("COMMENT ON ISSUE #5: uppercase")
        assert result.action == ACTION_COMMENT
        assert result.issue_number == 5


# ── CLOSE action ───────────────────────────────────────────────────────────────

class TestCloseAction:
    """Tests for 'close issue' natural-language variants."""

    def test_close_issue_with_hash(self):
        """'close issue #5' is the canonical close form."""
        result = parse_command("close issue #5")
        assert result.action == ACTION_CLOSE
        assert result.issue_number == 5

    def test_close_hash_terse_form(self):
        """'close #5' (no 'issue' filler) must still be recognised."""
        result = parse_command("close #5")
        assert result.action == ACTION_CLOSE
        assert result.issue_number == 5

    def test_resolve_synonym(self):
        """'resolve issue #5' must be treated identically to 'close issue #5'."""
        result = parse_command("resolve issue #5")
        assert result.action == ACTION_CLOSE
        assert result.issue_number == 5

    def test_close_issue_number_without_hash(self):
        """'close issue 5' (no # symbol) must extract the number."""
        result = parse_command("close issue 5")
        assert result.action == ACTION_CLOSE
        assert result.issue_number == 5

    def test_close_case_insensitive(self):
        """'CLOSE ISSUE #5' must match (case-insensitive)."""
        result = parse_command("CLOSE ISSUE #5")
        assert result.action == ACTION_CLOSE
        assert result.issue_number == 5


# ── UNKNOWN action ─────────────────────────────────────────────────────────────

class TestUnknownAction:
    """Tests for inputs that must return ACTION_UNKNOWN."""

    def test_empty_string_returns_unknown(self):
        """An empty message must not raise and must return ACTION_UNKNOWN."""
        result = parse_command("")
        assert result.action == ACTION_UNKNOWN

    def test_random_text_returns_unknown(self):
        """Arbitrary non-command text must return ACTION_UNKNOWN."""
        result = parse_command("Hello, how are you?")
        assert result.action == ACTION_UNKNOWN

    def test_partial_list_command_returns_unknown(self):
        """'list' alone (no 'issues') must not match the list pattern."""
        result = parse_command("list")
        assert result.action == ACTION_UNKNOWN

    def test_issue_without_number_returns_unknown(self):
        """'issue' with no number must not match the view pattern."""
        result = parse_command("issue")
        assert result.action == ACTION_UNKNOWN

    def test_create_without_colon_returns_unknown(self):
        """'create issue Fix bug' (missing colon) must not match create."""
        result = parse_command("create issue Fix bug")
        assert result.action == ACTION_UNKNOWN

    def test_whitespace_only_returns_unknown(self):
        """A message containing only whitespace must return ACTION_UNKNOWN."""
        result = parse_command("   ")
        assert result.action == ACTION_UNKNOWN


# ── ParsedCommand defaults ─────────────────────────────────────────────────────

class TestParsedCommandDefaults:
    """Tests that verify default field values on ParsedCommand instances."""

    def test_unknown_command_has_open_state_filter_default(self):
        """
        ParsedCommand defaults state_filter to STATE_OPEN so callers that
        only check action can safely ignore state_filter for non-list actions.
        """
        result = parse_command("random text")
        assert result.state_filter == STATE_OPEN

    def test_unknown_command_has_none_fields(self):
        """All optional fields on an unknown command must be None."""
        result = parse_command("random text")
        assert result.issue_number is None
        assert result.title is None
        assert result.body is None
        assert result.comment_text is None

    def test_list_command_has_none_issue_number(self):
        """A list command does not reference a specific issue number."""
        result = parse_command("list issues")
        assert result.issue_number is None

    def test_view_command_has_none_title_and_body(self):
        """A view command does not create content, so title and body must be None."""
        result = parse_command("issue #1")
        assert result.title is None
        assert result.body is None
