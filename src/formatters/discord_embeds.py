"""
discord_embeds.py — Converts raw GitHub webhook payloads into discord.Embed objects.

Each function accepts a Python dict (the parsed webhook JSON) and returns an Embed
ready to post to a Discord channel. All embeds share a consistent footer so users
always know which bot sent the message.
"""

import discord

# ── Constants ──────────────────────────────────────────────────────────────────

# GitHub can send hundreds of commits in a single push; we cap the list so the
# embed stays readable and doesn't exceed Discord's 6000-character embed limit.
MAX_COMMITS_SHOWN = 5

# PR and issue bodies can be very long; we truncate to keep embeds scannable.
MAX_BODY_PREVIEW_CHARS = 300

# Shared footer text stamped on every embed for consistent bot attribution.
_FOOTER_TEXT = "GitDiscord"


# ── Push Events ────────────────────────────────────────────────────────────────

def format_push_event(payload: dict) -> discord.Embed:
    """
    Formats a GitHub 'push' webhook event as a Discord embed.

    Shows the repository name, the branch that was pushed to, the pusher's
    username, how many commits were included, and up to MAX_COMMITS_SHOWN
    commit messages with short SHA hyperlinks to the diff on GitHub.

    Color: discord.Color.blue()
    """
    repo_name = payload.get("repository", {}).get("full_name", "unknown/repo")
    pusher_name = payload.get("pusher", {}).get("name", "unknown")

    # The ref is a full Git ref like "refs/heads/main"; strip the prefix so we
    # show only the human-readable branch name in the embed.
    raw_ref = payload.get("ref", "refs/heads/unknown")
    branch_name = raw_ref.removeprefix("refs/heads/")

    commits: list[dict] = payload.get("commits", [])
    total_commit_count = len(commits)

    # Build the description line-by-line so it's easy to read at a glance.
    description_lines = [
        f"**Pusher:** {pusher_name}",
        f"**Branch:** `{branch_name}`",
        f"**Commits:** {total_commit_count}",
        "",
    ]

    # Show up to MAX_COMMITS_SHOWN commits; link each short SHA to GitHub so
    # reviewers can jump straight to the diff without leaving Discord.
    shown_commits = commits[:MAX_COMMITS_SHOWN]
    for commit in shown_commits:
        sha_full = commit.get("id", "")
        sha_short = sha_full[:7] if sha_full else "unknown"
        commit_url = commit.get("url", "")
        message_first_line = commit.get("message", "No message").splitlines()[0]

        if commit_url:
            description_lines.append(f"[`{sha_short}`]({commit_url}) {message_first_line}")
        else:
            description_lines.append(f"`{sha_short}` {message_first_line}")

    # Let the reader know there are more commits not listed here.
    if total_commit_count > MAX_COMMITS_SHOWN:
        remaining = total_commit_count - MAX_COMMITS_SHOWN
        description_lines.append(f"… and {remaining} more commit(s)")

    embed = discord.Embed(
        title=f"🔨 Push to {repo_name}",
        description="\n".join(description_lines),
        color=discord.Color.blue(),
    )
    embed.set_footer(text=_FOOTER_TEXT)
    return embed


# ── Pull Request Events ────────────────────────────────────────────────────────

def format_pr_opened(payload: dict) -> discord.Embed:
    """
    Formats a GitHub pull_request 'opened' event as a Discord embed.

    Shows the PR title (as the embed title), PR number, author login, the
    base ← head branch relationship, a truncated body preview, and a link
    to the PR on GitHub.

    Color: discord.Color.green()
    """
    pull_request = payload.get("pull_request", {})

    pr_title = pull_request.get("title", "Untitled PR")
    pr_number = pull_request.get("number", 0)
    pr_url = pull_request.get("html_url", "")
    author = pull_request.get("user", {}).get("login", "unknown")
    base_branch = pull_request.get("base", {}).get("ref", "unknown")
    head_branch = pull_request.get("head", {}).get("ref", "unknown")

    raw_body = pull_request.get("body") or ""
    body_preview = (
        raw_body[:MAX_BODY_PREVIEW_CHARS] + "…"
        if len(raw_body) > MAX_BODY_PREVIEW_CHARS
        else raw_body
    )

    description_lines = [
        f"**Author:** {author}",
        f"**Branch:** `{base_branch}` ← `{head_branch}`",
    ]
    if body_preview:
        description_lines += ["", body_preview]

    embed = discord.Embed(
        title=f"🔀 PR #{pr_number}: {pr_title}",
        description="\n".join(description_lines),
        color=discord.Color.green(),
        url=pr_url or None,
    )
    embed.set_footer(text=_FOOTER_TEXT)
    return embed


def format_pr_review_requested(payload: dict) -> discord.Embed:
    """
    Formats a GitHub pull_request 'review_requested' event as a Discord embed.

    Shows which reviewer was requested, the PR title, PR number, and a link.
    The embed title is always "👀 Review Requested" so it's easy to filter
    notifications visually.

    Color: discord.Color.yellow()
    """
    pull_request = payload.get("pull_request", {})

    pr_title = pull_request.get("title", "Untitled PR")
    pr_number = pull_request.get("number", 0)
    pr_url = pull_request.get("html_url", "")

    # GitHub sends either `requested_reviewer` (single user) or
    # `requested_team` depending on the review target; we prefer the user.
    reviewer = payload.get("requested_reviewer", {})
    reviewer_login = reviewer.get("login", "unknown") if reviewer else "unknown"

    description_lines = [
        f"**Reviewer:** {reviewer_login}",
        f"**PR #{pr_number}:** {pr_title}",
    ]

    embed = discord.Embed(
        title="👀 Review Requested",
        description="\n".join(description_lines),
        color=discord.Color.yellow(),
        url=pr_url or None,
    )
    embed.set_footer(text=_FOOTER_TEXT)
    return embed


def format_pr_merged(payload: dict) -> discord.Embed:
    """
    Formats a GitHub pull_request 'closed' event where merged == True.

    Shows who merged the PR, the PR title, number, target base branch, and
    a link. Callers are responsible for checking payload["pull_request"]["merged"]
    before calling this function; it does not re-validate that condition.

    Color: discord.Color.purple()
    """
    pull_request = payload.get("pull_request", {})

    pr_title = pull_request.get("title", "Untitled PR")
    pr_number = pull_request.get("number", 0)
    pr_url = pull_request.get("html_url", "")
    base_branch = pull_request.get("base", {}).get("ref", "unknown")

    # `merged_by` can be null if GitHub couldn't determine the merger (e.g.,
    # via the API without attribution), so we fall back gracefully.
    merged_by_obj = pull_request.get("merged_by") or {}
    merged_by = merged_by_obj.get("login", "unknown")

    description_lines = [
        f"**Merged by:** {merged_by}",
        f"**PR #{pr_number}:** {pr_title}",
        f"**Into:** `{base_branch}`",
    ]

    embed = discord.Embed(
        title="✅ Pull Request Merged",
        description="\n".join(description_lines),
        color=discord.Color.purple(),
        url=pr_url or None,
    )
    embed.set_footer(text=_FOOTER_TEXT)
    return embed


def format_pr_closed_without_merge(payload: dict) -> discord.Embed:
    """
    Formats a GitHub pull_request 'closed' event where merged == False.

    Shows who closed the PR (the sender of the webhook action), the PR title,
    number, and a link. Callers should verify merged == False before calling.

    Color: discord.Color.red()
    """
    pull_request = payload.get("pull_request", {})

    pr_title = pull_request.get("title", "Untitled PR")
    pr_number = pull_request.get("number", 0)
    pr_url = pull_request.get("html_url", "")

    # The "sender" field is the GitHub user who triggered the action, which is
    # the closest proxy for "who closed this PR" in the webhook payload.
    closed_by = payload.get("sender", {}).get("login", "unknown")

    description_lines = [
        f"**Closed by:** {closed_by}",
        f"**PR #{pr_number}:** {pr_title}",
    ]

    embed = discord.Embed(
        title="❌ Pull Request Closed",
        description="\n".join(description_lines),
        color=discord.Color.red(),
        url=pr_url or None,
    )
    embed.set_footer(text=_FOOTER_TEXT)
    return embed


def format_pr_dict(pull_request: dict) -> discord.Embed:
    """
    Formats a plain GitHub pull request dict as a Discord embed.

    Accepts the REST/API shape returned by GitHubClient so inline PR references
    can reuse the same visual style as webhook notifications without pretending
    the data came from a webhook envelope.
    """
    pull_request_title = pull_request.get("title", "Untitled PR")
    pull_request_number = pull_request.get("number", 0)
    pull_request_url = pull_request.get("html_url") or pull_request.get("url", "")
    pull_request_state = pull_request.get("state", "open")
    was_merged = bool(pull_request.get("merged", False))
    author_login = (
        pull_request.get("user", {}).get("login")
        if isinstance(pull_request.get("user"), dict)
        else None
    ) or pull_request.get("user_login", "unknown")
    base_branch = (
        pull_request.get("base", {}).get("ref")
        if isinstance(pull_request.get("base"), dict)
        else None
    ) or pull_request.get("base_ref", "unknown")
    head_branch = (
        pull_request.get("head", {}).get("ref")
        if isinstance(pull_request.get("head"), dict)
        else None
    ) or pull_request.get("head_ref", "unknown")

    raw_body = pull_request.get("body") or ""
    body_preview = (
        raw_body[:MAX_BODY_PREVIEW_CHARS] + "…"
        if len(raw_body) > MAX_BODY_PREVIEW_CHARS
        else raw_body
    )

    label_names = _extract_label_names(pull_request.get("labels", []) or [])
    description_lines = [
        f"**Author:** {author_login}",
        f"**State:** {pull_request_state}",
        f"**Branch:** `{base_branch}` ← `{head_branch}`",
    ]
    if label_names:
        description_lines.append(f"**Labels:** {', '.join(label_names)}")
    if body_preview:
        description_lines += ["", body_preview]

    if pull_request_state == "closed" and was_merged:
        embed_color = discord.Color.purple()
    elif pull_request_state == "closed":
        embed_color = discord.Color.red()
    else:
        embed_color = discord.Color.green()

    embed = discord.Embed(
        title=f"🔀 PR #{pull_request_number}: {pull_request_title}",
        description="\n".join(description_lines),
        color=embed_color,
        url=pull_request_url or None,
    )
    embed.set_footer(text=_FOOTER_TEXT)
    return embed


# ── Issues ─────────────────────────────────────────────────────────────────────

def _extract_label_names(labels: list) -> list[str]:
    """Return label names from GitHub webhook dicts or GitHubClient strings."""
    label_names = []
    for label in labels:
        if isinstance(label, dict):
            label_name = label.get("name", "")
        else:
            label_name = str(label) if label else ""
        if label_name:
            label_names.append(label_name)
    return label_names

def format_issue_dict(issue: dict, action: str = "opened") -> discord.Embed:
    """
    Formats a GitHub issue dict as a Discord embed.

    Accepts a plain issue dict — either from a webhook payload's 'issue' key or
    from the GitHubClient REST response — so it works for both live events and
    slash-command lookups.

    action:  one of "opened", "closed", "created", "updated"; used in the title.
    Shows:   issue title, number, state, a body preview, labels, and the URL.

    Color: discord.Color.gold() for open issues, discord.Color.greyple() for closed.
    """
    issue_title = issue.get("title", "Untitled Issue")
    issue_number = issue.get("number", 0)
    # Webhook payloads use "html_url"; GitHubClient dicts use "url".
    # Check both keys so this function works with either source.
    issue_url = issue.get("html_url") or issue.get("url", "")
    issue_state = issue.get("state", "open")

    raw_body = issue.get("body") or ""
    body_preview = (
        raw_body[:MAX_BODY_PREVIEW_CHARS] + "…"
        if len(raw_body) > MAX_BODY_PREVIEW_CHARS
        else raw_body
    )

    # Collect label names from either dict format (webhook: {"name": "bug"})
    # or plain string format (GitHubClient: "bug").  Supporting both keeps
    # this formatter usable regardless of which data source called it.
    labels: list = issue.get("labels", []) or []
    label_names = _extract_label_names(labels)

    description_lines = [
        f"**State:** {issue_state}",
    ]
    if label_names:
        # Show labels inline so reviewers can triage at a glance.
        description_lines.append(f"**Labels:** {', '.join(label_names)}")
    if body_preview:
        description_lines += ["", body_preview]

    # Use a warmer color for open issues (needs attention) and grey for closed
    # (resolved / no action needed) to give instant visual status cues.
    color = discord.Color.gold() if issue_state == "open" else discord.Color.greyple()

    embed = discord.Embed(
        title=f"🐛 Issue #{issue_number} {action}: {issue_title}",
        description="\n".join(description_lines),
        color=color,
        url=issue_url or None,
    )
    embed.set_footer(text=_FOOTER_TEXT)
    return embed


def format_issue_comment_event(payload: dict) -> discord.Embed:
    """
    Formats a GitHub 'issue_comment' webhook event as a Discord embed.

    Shows which issue received the comment, who wrote it, the webhook action,
    and a preview of the comment body with a direct link to the comment.

    Color: discord.Color.blurple()
    """
    issue_dict = payload.get("issue", {})
    comment_dict = payload.get("comment", {})
    action = payload.get("action", "created")

    issue_number = issue_dict.get("number", 0)
    issue_title = issue_dict.get("title", "Untitled Issue")
    commenter_login = comment_dict.get("user", {}).get("login", "unknown")
    comment_url = comment_dict.get("html_url", "")
    comment_body = comment_dict.get("body") or ""
    comment_preview = (
        comment_body[:MAX_BODY_PREVIEW_CHARS] + "…"
        if len(comment_body) > MAX_BODY_PREVIEW_CHARS
        else comment_body
    )

    description_lines = [
        f"**Action:** {action}",
        f"**Author:** {commenter_login}",
        f"**Issue #{issue_number}:** {issue_title}",
    ]
    if comment_preview:
        description_lines += ["", comment_preview]

    embed = discord.Embed(
        title="💬 Issue Comment",
        description="\n".join(description_lines),
        color=discord.Color.blurple(),
        url=comment_url or None,
    )
    embed.set_footer(text=_FOOTER_TEXT)
    return embed


def format_commit_comment_event(payload: dict) -> discord.Embed:
    """
    Formats a GitHub 'commit_comment' webhook event as a Discord embed.

    Shows the action, comment author, short commit SHA, and a preview of the
    comment body with a link to the comment on GitHub.

    Color: discord.Color.dark_teal()
    """
    comment_dict = payload.get("comment", {})
    action = payload.get("action", "created")
    commenter_login = comment_dict.get("user", {}).get("login", "unknown")
    commit_sha_full = comment_dict.get("commit_id", "")
    commit_sha_short = commit_sha_full[:7] if commit_sha_full else "unknown"
    comment_url = comment_dict.get("html_url", "")
    comment_body = comment_dict.get("body") or ""
    comment_preview = (
        comment_body[:MAX_BODY_PREVIEW_CHARS] + "…"
        if len(comment_body) > MAX_BODY_PREVIEW_CHARS
        else comment_body
    )

    description_lines = [
        f"**Action:** {action}",
        f"**Author:** {commenter_login}",
        f"**Commit:** `{commit_sha_short}`",
    ]
    if comment_preview:
        description_lines += ["", comment_preview]

    embed = discord.Embed(
        title="🧵 Commit Comment",
        description="\n".join(description_lines),
        color=discord.Color.dark_teal(),
        url=comment_url or None,
    )
    embed.set_footer(text=_FOOTER_TEXT)
    return embed
