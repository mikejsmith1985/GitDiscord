"""
Tests for GitHubClient in src/github/client.py.

All PyGithub HTTP calls are replaced with MagicMock objects so no real
network requests are made.  Each test verifies the dict shape returned
by the client and the PyGithub calls it delegates to.
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from github import UnknownObjectException

from src.github.client import GitHubClient, MAX_ISSUES_PER_PAGE


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_mock_issue(
    number: int = 1,
    title: str = "Test Issue",
    state: str = "open",
    body: str | None = "Issue body text",
    html_url: str = "https://github.com/owner/repo/issues/1",
    user_login: str = "testuser",
    label_names: list[str] | None = None,
    assignee_logins: list[str] | None = None,
) -> MagicMock:
    """Build a MagicMock that mimics a PyGithub Issue object."""
    mock_issue = MagicMock()
    mock_issue.number = number
    mock_issue.title = title
    mock_issue.state = state
    mock_issue.body = body
    mock_issue.html_url = html_url
    mock_issue.created_at = datetime(2024, 1, 15, 10, 0, 0)
    mock_issue.user.login = user_login

    resolved_label_names = label_names or []
    mock_labels = []
    for label_name in resolved_label_names:
        label_mock = MagicMock()
        label_mock.name = label_name
        mock_labels.append(label_mock)
    mock_issue.labels = mock_labels

    resolved_assignee_logins = assignee_logins or []
    mock_assignees = []
    for login in resolved_assignee_logins:
        assignee_mock = MagicMock()
        assignee_mock.login = login
        mock_assignees.append(assignee_mock)
    mock_issue.assignees = mock_assignees

    return mock_issue


def _make_mock_comment(
    comment_id: int = 101,
    body: str = "A comment",
    html_url: str = "https://github.com/owner/repo/issues/1#issuecomment-101",
    user_login: str = "commenter",
) -> MagicMock:
    """Build a MagicMock that mimics a PyGithub IssueComment object."""
    mock_comment = MagicMock()
    mock_comment.id = comment_id
    mock_comment.body = body
    mock_comment.html_url = html_url
    mock_comment.created_at = datetime(2024, 2, 10, 9, 30, 0)
    mock_comment.user.login = user_login
    return mock_comment


def _make_mock_pull_request(
    number: int = 1,
    title: str = "Test PR",
    state: str = "open",
    body: str | None = "PR body text",
    html_url: str = "https://github.com/owner/repo/pull/1",
    user_login: str = "testuser",
    base_ref: str = "main",
    head_ref: str = "feature/test",
    merged: bool = False,
    merged_by_login: str | None = None,
    label_names: list[str] | None = None,
    assignee_logins: list[str] | None = None,
    is_draft: bool = False,
) -> MagicMock:
    """Build a MagicMock that mimics a PyGithub PullRequest object."""
    mock_pull_request = MagicMock()
    mock_pull_request.number = number
    mock_pull_request.title = title
    mock_pull_request.state = state
    mock_pull_request.body = body
    mock_pull_request.html_url = html_url
    mock_pull_request.created_at = datetime(2024, 3, 1, 12, 0, 0)
    mock_pull_request.user.login = user_login
    mock_pull_request.base.ref = base_ref
    mock_pull_request.head.ref = head_ref
    mock_pull_request.merged = merged
    mock_pull_request.merged_by = (
        MagicMock(login=merged_by_login) if merged_by_login else None
    )
    mock_pull_request.draft = is_draft

    resolved_label_names = label_names or []
    mock_labels = []
    for label_name in resolved_label_names:
        label_mock = MagicMock()
        label_mock.name = label_name
        mock_labels.append(label_mock)
    mock_pull_request.labels = mock_labels

    resolved_assignee_logins = assignee_logins or []
    mock_pull_request.assignees = [
        MagicMock(login=assignee_login)
        for assignee_login in resolved_assignee_logins
    ]

    return mock_pull_request


@pytest.fixture
def client_and_repo():
    """
    Provide a GitHubClient instance whose internal Github object is fully mocked.

    Yields a tuple of (GitHubClient, mock_repo) so tests can both call the
    client methods and assert on the mock_repo interactions.
    """
    mock_repo = MagicMock()
    with patch("src.github.client.Auth.AppAuth") as mock_app_auth_class, patch("src.github.client.GithubIntegration") as mock_github_integration_class, patch("src.github.client.Github") as mock_github_class:
        mock_app_auth = MagicMock()
        mock_app_auth_class.return_value = mock_app_auth
        mock_github_instance = MagicMock()
        mock_github_class.return_value = mock_github_instance
        mock_github_instance.get_repo.return_value = mock_repo
        mock_github_integration_instance = MagicMock()
        mock_github_integration_class.return_value = mock_github_integration_instance
        mock_repo_installation = MagicMock()
        mock_repo_installation.id = 456
        mock_github_integration_instance.get_repo_installation.return_value = mock_repo_installation
        mock_access_token = MagicMock()
        mock_access_token.token = "installation-token"
        mock_github_integration_instance.get_access_token.return_value = mock_access_token

        github_client = GitHubClient(
            github_app_id="123",
            github_app_private_key="-----BEGIN PRIVATE KEY-----test-----END PRIVATE KEY-----",
            github_app_installation_id="456",
            repo_owner="owner",
            repo_name="repo",
        )
        yield github_client, mock_repo


@patch("src.github.client.GithubIntegration")
@patch("src.github.client.Auth.AppAuth")
@patch("src.github.client.Github")
def test_github_client_uses_installation_access_token(
    mock_github_class,
    mock_app_auth_class,
    mock_github_integration_class,
):
    """GitHubClient must use a GitHub App installation token, not a PAT."""
    mock_github_instance = MagicMock()
    mock_github_class.return_value = mock_github_instance
    mock_github_instance.get_repo.return_value = MagicMock()
    mock_app_auth = MagicMock()
    mock_app_auth_class.return_value = mock_app_auth
    mock_github_integration_instance = MagicMock()
    mock_github_integration_class.return_value = mock_github_integration_instance
    mock_repo_installation = MagicMock()
    mock_repo_installation.id = 456
    mock_github_integration_instance.get_repo_installation.return_value = mock_repo_installation
    mock_access_token = MagicMock()
    mock_access_token.token = "generated-installation-token"
    mock_github_integration_instance.get_access_token.return_value = mock_access_token

    GitHubClient(
        github_app_id="123",
        github_app_private_key="-----BEGIN PRIVATE KEY-----test-----END PRIVATE KEY-----",
        github_app_installation_id="456",
        repo_owner="owner",
        repo_name="repo",
    )

    mock_app_auth_class.assert_called_once_with(
        app_id=123,
        private_key="-----BEGIN PRIVATE KEY-----test-----END PRIVATE KEY-----",
    )
    mock_github_integration_class.assert_called_once_with(auth=mock_app_auth)
    mock_github_integration_instance.get_repo_installation.assert_called_once_with("owner", "repo")
    mock_github_integration_instance.get_access_token.assert_called_once_with(456)
    mock_github_class.assert_called_once_with("generated-installation-token")


@patch("src.github.client.GithubIntegration")
@patch("src.github.client.Auth.AppAuth")
def test_github_client_reports_repo_installation_id_mismatch(
    mock_app_auth_class,
    mock_github_integration_class,
):
    """GitHubClient should report when configured installation id doesn't match repo installation."""
    mock_app_auth = MagicMock()
    mock_app_auth_class.return_value = mock_app_auth
    mock_github_integration_instance = MagicMock()
    mock_github_integration_class.return_value = mock_github_integration_instance
    mock_repo_installation = MagicMock()
    mock_repo_installation.id = 999
    mock_github_integration_instance.get_repo_installation.return_value = mock_repo_installation

    with pytest.raises(ValueError, match="installation mismatch"):
        GitHubClient(
            github_app_id="123",
            github_app_private_key="-----BEGIN PRIVATE KEY-----test-----END PRIVATE KEY-----",
            github_app_installation_id="456",
            repo_owner="owner",
            repo_name="repo",
        )


def test_github_client_reports_non_integer_installation_id():
    """GitHubClient should fail fast when installation ID is not numeric."""
    with pytest.raises(ValueError, match="GITHUB_APP_INSTALLATION_ID must be a valid integer"):
        GitHubClient(
            github_app_id="123",
            github_app_private_key="-----BEGIN PRIVATE KEY-----test-----END PRIVATE KEY-----",
            github_app_installation_id="not-a-number",
            repo_owner="owner",
            repo_name="repo",
        )


# ── list_issues ───────────────────────────────────────────────────────────────


class TestListIssues:
    """Tests for GitHubClient.list_issues()."""

    def test_list_issues_returns_list_of_dicts_with_correct_fields(self, client_and_repo):
        """list_issues() converts PyGithub Issue objects into plain dicts with all expected keys."""
        github_client, mock_repo = client_and_repo
        mock_issue = _make_mock_issue(
            number=7,
            title="Fix the login bug",
            state="open",
            body="Detailed description",
            html_url="https://github.com/owner/repo/issues/7",
            user_login="alice",
            label_names=["bug", "high-priority"],
            assignee_logins=["bob"],
        )
        mock_repo.get_issues.return_value = [mock_issue]

        result = github_client.list_issues()

        assert isinstance(result, list)
        assert len(result) == 1

        issue_dict = result[0]
        assert issue_dict["number"] == 7
        assert issue_dict["title"] == "Fix the login bug"
        assert issue_dict["state"] == "open"
        assert issue_dict["body"] == "Detailed description"
        assert issue_dict["url"] == "https://github.com/owner/repo/issues/7"
        assert issue_dict["created_at"] == "2024-01-15T10:00:00"
        assert issue_dict["user_login"] == "alice"
        assert issue_dict["labels"] == ["bug", "high-priority"]
        assert issue_dict["assignees"] == ["bob"]

    def test_list_issues_passes_open_state_by_default(self, client_and_repo):
        """list_issues() calls get_issues with state='open' when no state argument is given."""
        github_client, mock_repo = client_and_repo
        mock_repo.get_issues.return_value = []

        github_client.list_issues()

        mock_repo.get_issues.assert_called_once_with(state="open")

    def test_list_issues_passes_closed_state_when_requested(self, client_and_repo):
        """list_issues(state='closed') forwards the 'closed' filter to PyGithub."""
        github_client, mock_repo = client_and_repo
        mock_repo.get_issues.return_value = []

        github_client.list_issues(state="closed")

        mock_repo.get_issues.assert_called_once_with(state="closed")

    def test_list_issues_caps_results_at_max_issues_per_page(self, client_and_repo):
        """list_issues() never returns more than MAX_ISSUES_PER_PAGE issues."""
        github_client, mock_repo = client_and_repo
        # Create one more issue than the cap to verify truncation.
        oversized_issue_list = [
            _make_mock_issue(number=issue_index)
            for issue_index in range(MAX_ISSUES_PER_PAGE + 5)
        ]
        mock_repo.get_issues.return_value = oversized_issue_list

        result = github_client.list_issues()

        assert len(result) == MAX_ISSUES_PER_PAGE

    def test_list_issues_handles_null_body_gracefully(self, client_and_repo):
        """list_issues() converts a None issue body to an empty string rather than raising."""
        github_client, mock_repo = client_and_repo
        mock_issue = _make_mock_issue(body=None)
        mock_repo.get_issues.return_value = [mock_issue]

        result = github_client.list_issues()

        assert result[0]["body"] == ""

    def test_list_issues_returns_empty_list_when_no_issues_exist(self, client_and_repo):
        """list_issues() returns an empty list rather than None when the repo has no issues."""
        github_client, mock_repo = client_and_repo
        mock_repo.get_issues.return_value = []

        result = github_client.list_issues()

        assert result == []


# ── get_issue ─────────────────────────────────────────────────────────────────


class TestGetIssue:
    """Tests for GitHubClient.get_issue()."""

    def test_get_issue_returns_correct_dict_for_existing_issue(self, client_and_repo):
        """get_issue() returns a populated dict when the issue number exists."""
        github_client, mock_repo = client_and_repo
        mock_issue = _make_mock_issue(
            number=42,
            title="Upgrade dependencies",
            state="open",
            user_login="carol",
        )
        mock_repo.get_issue.return_value = mock_issue

        result = github_client.get_issue(42)

        assert result is not None
        assert result["number"] == 42
        assert result["title"] == "Upgrade dependencies"
        assert result["user_login"] == "carol"
        mock_repo.get_issue.assert_called_once_with(42)

    def test_get_issue_returns_none_for_missing_issue(self, client_and_repo):
        """get_issue() returns None when PyGithub raises UnknownObjectException."""
        github_client, mock_repo = client_and_repo
        mock_repo.get_issue.side_effect = UnknownObjectException(404, "Not Found", {})

        result = github_client.get_issue(9999)

        assert result is None


# ── get_pull_request ───────────────────────────────────────────────────────────


class TestGetPullRequest:
    """Tests for GitHubClient.get_pull_request()."""

    def test_get_pull_request_returns_correct_dict_for_existing_pr(self, client_and_repo):
        """get_pull_request() returns a populated dict when the PR number exists."""
        github_client, mock_repo = client_and_repo
        mock_pull_request = _make_mock_pull_request(
            number=42,
            title="Upgrade dependencies",
            state="open",
            user_login="carol",
            base_ref="main",
            head_ref="feature/deps",
        )
        mock_repo.get_pull.return_value = mock_pull_request

        result = github_client.get_pull_request(42)

        assert result is not None
        assert result["number"] == 42
        assert result["title"] == "Upgrade dependencies"
        assert result["user_login"] == "carol"
        assert result["base_ref"] == "main"
        assert result["head_ref"] == "feature/deps"
        assert result["created_at"] == "2024-03-01T12:00:00"
        mock_repo.get_pull.assert_called_once_with(42)

    def test_get_pull_request_returns_none_for_missing_pr(self, client_and_repo):
        """get_pull_request() returns None when PyGithub raises UnknownObjectException."""
        github_client, mock_repo = client_and_repo
        mock_repo.get_pull.side_effect = UnknownObjectException(404, "Not Found", {})

        result = github_client.get_pull_request(9999)

        assert result is None

    def test_get_pull_request_handles_null_body(self, client_and_repo):
        """get_pull_request() converts a None body to an empty string."""
        github_client, mock_repo = client_and_repo
        mock_repo.get_pull.return_value = _make_mock_pull_request(body=None)

        result = github_client.get_pull_request(1)

        assert result["body"] == ""

    def test_get_pull_request_handles_no_merged_by(self, client_and_repo):
        """get_pull_request() returns None for merged_by_login when GitHub omits it."""
        github_client, mock_repo = client_and_repo
        mock_repo.get_pull.return_value = _make_mock_pull_request(
            merged=True,
            merged_by_login=None,
        )

        result = github_client.get_pull_request(1)

        assert result["merged"] is True
        assert result["merged_by_login"] is None

    def test_get_pull_request_maps_labels_and_assignees(self, client_and_repo):
        """get_pull_request() serializes labels and assignees as plain strings."""
        github_client, mock_repo = client_and_repo
        mock_repo.get_pull.return_value = _make_mock_pull_request(
            label_names=["bug", "P1"],
            assignee_logins=["alice", "bob"],
        )

        result = github_client.get_pull_request(1)

        assert result["labels"] == ["bug", "P1"]
        assert result["assignees"] == ["alice", "bob"]


# ── create_issue ──────────────────────────────────────────────────────────────


class TestCreateIssue:
    """Tests for GitHubClient.create_issue()."""

    def test_create_issue_calls_pygithub_and_returns_issue_dict(self, client_and_repo):
        """create_issue() delegates to repo.create_issue and converts the result to a dict."""
        github_client, mock_repo = client_and_repo
        mock_created_issue = _make_mock_issue(
            number=55,
            title="New feature request",
            state="open",
        )
        mock_repo.create_issue.return_value = mock_created_issue

        result = github_client.create_issue(title="New feature request", body="Please add X")

        mock_repo.create_issue.assert_called_once_with(
            title="New feature request", body="Please add X"
        )
        assert result["number"] == 55
        assert result["title"] == "New feature request"

    def test_create_issue_defaults_body_to_empty_string(self, client_and_repo):
        """create_issue() passes an empty string body to PyGithub when no body is supplied."""
        github_client, mock_repo = client_and_repo
        mock_repo.create_issue.return_value = _make_mock_issue(title="Title only")

        github_client.create_issue(title="Title only")

        mock_repo.create_issue.assert_called_once_with(title="Title only", body="")


# ── add_issue_comment ─────────────────────────────────────────────────────────


class TestAddIssueComment:
    """Tests for GitHubClient.add_issue_comment()."""

    def test_add_issue_comment_returns_comment_dict_with_correct_fields(self, client_and_repo):
        """add_issue_comment() returns a dict with id, body, url, created_at, and user_login."""
        github_client, mock_repo = client_and_repo
        mock_issue = _make_mock_issue(number=10)
        mock_repo.get_issue.return_value = mock_issue
        mock_comment = _make_mock_comment(
            comment_id=999,
            body="This is a comment",
            html_url="https://github.com/owner/repo/issues/10#issuecomment-999",
            user_login="dave",
        )
        mock_issue.create_comment.return_value = mock_comment

        result = github_client.add_issue_comment(issue_number=10, comment_text="This is a comment")

        assert result["id"] == 999
        assert result["body"] == "This is a comment"
        assert result["url"] == "https://github.com/owner/repo/issues/10#issuecomment-999"
        assert result["created_at"] == "2024-02-10T09:30:00"
        assert result["user_login"] == "dave"
        mock_issue.create_comment.assert_called_once_with("This is a comment")

    def test_add_issue_comment_raises_value_error_for_missing_issue(self, client_and_repo):
        """add_issue_comment() raises ValueError with a descriptive message when the issue is gone."""
        github_client, mock_repo = client_and_repo
        mock_repo.get_issue.side_effect = UnknownObjectException(404, "Not Found", {})

        with pytest.raises(ValueError, match="Issue #404 not found"):
            github_client.add_issue_comment(issue_number=404, comment_text="Hello")


# ── close_issue ───────────────────────────────────────────────────────────────


class TestCloseIssue:
    """Tests for GitHubClient.close_issue()."""

    def test_close_issue_calls_edit_with_closed_state_and_returns_updated_dict(
        self, client_and_repo
    ):
        """close_issue() calls issue.edit(state='closed') and returns the re-fetched issue dict."""
        github_client, mock_repo = client_and_repo

        mock_open_issue = _make_mock_issue(number=20, state="open")
        mock_closed_issue = _make_mock_issue(number=20, state="closed")

        # First call from close_issue() to get the issue; second call re-fetches after edit.
        mock_repo.get_issue.side_effect = [mock_open_issue, mock_closed_issue]

        result = github_client.close_issue(issue_number=20)

        mock_open_issue.edit.assert_called_once_with(state="closed")
        assert result["state"] == "closed"
        assert result["number"] == 20

    def test_close_issue_raises_value_error_for_missing_issue(self, client_and_repo):
        """close_issue() raises ValueError with a descriptive message for a non-existent issue."""
        github_client, mock_repo = client_and_repo
        mock_repo.get_issue.side_effect = UnknownObjectException(404, "Not Found", {})

        with pytest.raises(ValueError, match="Issue #99 not found"):
            github_client.close_issue(issue_number=99)
