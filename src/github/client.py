"""
GitHub API client for the GitDiscord bot.

Wraps PyGithub to provide issue management operations as plain dicts,
keeping the Discord bot layer fully decoupled from the GitHub library.
"""

from github import Auth, Github, GithubException, GithubIntegration, UnknownObjectException

# Cap results to keep Discord message payloads readable and within embed limits.
MAX_ISSUES_PER_PAGE = 25


def _parse_required_integer(raw_value: str, setting_name: str) -> int:
    """Parse an integer setting and raise a clear ValueError when invalid."""
    try:
        return int(raw_value)
    except (TypeError, ValueError) as conversion_error:
        raise ValueError(
            f"{setting_name} must be a valid integer. Current value: {raw_value!r}"
        ) from conversion_error


def _issue_to_dict(issue) -> dict:
    """
    Convert a PyGithub Issue object into a plain dict.

    We return plain dicts instead of PyGithub objects so that callers
    (Discord command handlers) have no dependency on PyGithub types.
    This makes the bot layer independently testable via simple dict assertions.
    """
    return {
        "number": issue.number,
        "title": issue.title,
        "state": issue.state,
        "body": issue.body or "",
        "url": issue.html_url,
        "created_at": issue.created_at.isoformat(),
        "user_login": issue.user.login,
        "labels": [label.name for label in issue.labels],
        "assignees": [assignee.login for assignee in issue.assignees],
    }


def _comment_to_dict(comment) -> dict:
    """Convert a PyGithub IssueComment object into a plain dict."""
    return {
        "id": comment.id,
        "body": comment.body,
        "url": comment.html_url,
        "created_at": comment.created_at.isoformat(),
        "user_login": comment.user.login,
    }


class GitHubClient:
    """
    High-level GitHub API client used by the GitDiscord bot.

    All methods return plain dicts rather than PyGithub objects so that
    consumers are not coupled to the underlying library.
    """

    def __init__(
        self,
        github_app_id: str,
        github_app_private_key: str,
        github_app_installation_id: str,
        repo_owner: str,
        repo_name: str,
    ) -> None:
        """
        Initialise the client and resolve the target repository.

        Args:
            github_app_id: GitHub App ID from the app settings page.
            github_app_private_key: PEM private key generated for the app.
            github_app_installation_id: Installation ID authorizing repo access.
            repo_owner: The GitHub username or organisation that owns the repo.
            repo_name: The repository name (without the owner prefix).
        """
        parsed_github_app_id = _parse_required_integer(
            github_app_id,
            "GITHUB_APP_ID",
        )
        parsed_github_app_installation_id = _parse_required_integer(
            github_app_installation_id,
            "GITHUB_APP_INSTALLATION_ID",
        )

        try:
            github_app_auth = Auth.AppAuth(
                app_id=parsed_github_app_id,
                private_key=github_app_private_key,
            )
            github_integration_client = GithubIntegration(auth=github_app_auth)
            repo_installation = github_integration_client.get_repo_installation(
                repo_owner,
                repo_name,
            )
        except GithubException as github_exception:
            raise ValueError(
                "GitHub App setup failed during app/repo verification "
                f"(status={github_exception.status}): {github_exception.data}"
            ) from github_exception
        except Exception as github_setup_error:
            raise ValueError(
                "GitHub App setup failed while loading app credentials. "
                "Verify GITHUB_APP_PRIVATE_KEY uses the full PEM content."
            ) from github_setup_error

        if repo_installation.id != parsed_github_app_installation_id:
            raise ValueError(
                "GitHub App installation mismatch: configured "
                f"GITHUB_APP_INSTALLATION_ID={parsed_github_app_installation_id}, "
                f"but repo {repo_owner}/{repo_name} is installed as "
                f"{repo_installation.id}."
            )

        try:
            installation_access_token = github_integration_client.get_access_token(
                parsed_github_app_installation_id
            )
        except GithubException as github_exception:
            raise ValueError(
                "GitHub App token creation failed for configured installation "
                f"{parsed_github_app_installation_id} (status={github_exception.status}): "
                f"{github_exception.data}"
            ) from github_exception

        self._github = Github(installation_access_token.token)
        self._repo_owner = repo_owner
        self._repo_name = repo_name

        # Resolve the repo eagerly so misconfiguration surfaces at startup
        # rather than silently failing on the first command.
        self._repo = self._github.get_repo(f"{repo_owner}/{repo_name}")

    # ── Issue queries ──────────────────────────────────────────────────────

    def list_issues(self, state: str = "open") -> list[dict]:
        """
        Return up to MAX_ISSUES_PER_PAGE issues from the repository.

        Results are capped to keep Discord messages readable; the caller
        may present a "showing first 25" notice when the list is long.

        Args:
            state: Filter by issue state — "open", "closed", or "all".

        Returns:
            A list of issue dicts, each containing: number, title, state,
            body, url, created_at, user_login, labels, and assignees.
        """
        paginated_issues = self._repo.get_issues(state=state)

        # PyGithub PaginatedList is lazy; slicing triggers only the needed
        # API calls rather than fetching every page up front.
        return [_issue_to_dict(issue) for issue in paginated_issues[:MAX_ISSUES_PER_PAGE]]

    def get_issue(self, issue_number: int) -> dict | None:
        """
        Return a single issue by number, or None if it does not exist.

        Args:
            issue_number: The GitHub issue number (shown in the issue URL).

        Returns:
            An issue dict, or None when the issue number is not found.
        """
        try:
            issue = self._repo.get_issue(issue_number)
            return _issue_to_dict(issue)
        except UnknownObjectException:
            # The issue does not exist — return None rather than raising so
            # callers can decide how to handle the "not found" case gracefully.
            return None

    # ── Issue mutations ────────────────────────────────────────────────────

    def create_issue(self, title: str, body: str = "") -> dict:
        """
        Create a new issue and return it as a dict.

        Args:
            title: The issue title (required by the GitHub API).
            body:  Optional markdown body. Defaults to an empty string.

        Returns:
            The newly created issue as a dict.
        """
        new_issue = self._repo.create_issue(title=title, body=body)
        return _issue_to_dict(new_issue)

    def add_issue_comment(self, issue_number: int, comment_text: str) -> dict:
        """
        Add a comment to an existing issue.

        Args:
            issue_number: The issue to comment on.
            comment_text: The markdown body of the comment.

        Returns:
            The new comment as a dict containing: id, body, url,
            created_at, and user_login.

        Raises:
            ValueError: If the issue does not exist.
        """
        try:
            issue = self._repo.get_issue(issue_number)
        except UnknownObjectException:
            raise ValueError(
                f"Issue #{issue_number} not found in "
                f"{self._repo_owner}/{self._repo_name}"
            )

        new_comment = issue.create_comment(comment_text)
        return _comment_to_dict(new_comment)

    def close_issue(self, issue_number: int) -> dict:
        """
        Close an open issue and return the updated issue dict.

        Args:
            issue_number: The issue number to close.

        Returns:
            The updated issue dict with state set to "closed".

        Raises:
            ValueError: If the issue does not exist.
        """
        try:
            issue = self._repo.get_issue(issue_number)
        except UnknownObjectException:
            raise ValueError(
                f"Issue #{issue_number} not found in "
                f"{self._repo_owner}/{self._repo_name}"
            )

        # PyGithub requires edit() to change state; there is no dedicated
        # close() method — "closed" is just a state value like any other edit.
        issue.edit(state="closed")

        # Re-fetch after the edit so the returned dict reflects the server
        # state rather than our locally mutated object.
        return _issue_to_dict(self._repo.get_issue(issue_number))
