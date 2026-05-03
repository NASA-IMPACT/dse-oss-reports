"""Tests for queries.fetch_commits and fetch_resolved.

The real ``github.Github`` client is mocked at the module level via monkeypatch
so the tests don't hit the network. The fake classes mimic just the attribute
shape PyGithub exposes for the calls we make — anything not used here is omitted.
"""

from datetime import datetime
from types import SimpleNamespace

from dse_oss_reports.queries import fetch_commits, fetch_commits_and_resolved, fetch_resolved

# ---------------------------------------------------------------------------
# Fake PyGithub objects
# ---------------------------------------------------------------------------


class FakePulls(list):
    """List subclass exposing PyGithub's ``totalCount`` attribute."""

    @property
    def totalCount(self) -> int:
        return len(self)


def make_fake_commit(
    sha: str,
    message: str,
    author: str,
    committer: str = "GitHub",
    total: int = 1,
    pr_numbers: list[int] | None = None,
    html_url: str | None = None,
):
    """Build an object whose attribute shape matches a PyGithub Commit."""
    pulls = FakePulls(SimpleNamespace(number=n) for n in (pr_numbers or []))
    return SimpleNamespace(
        sha=sha,
        commit=SimpleNamespace(
            message=message,
            author=SimpleNamespace(name=author),
            committer=SimpleNamespace(name=committer),
        ),
        html_url=html_url or f"https://github.com/x/y/commit/{sha}",
        stats=SimpleNamespace(total=total),
        get_pulls=lambda: pulls,
    )


class FakeRepo:
    def __init__(self, commits: list):
        self._commits = commits

    def get_commits(self, **_kwargs):
        return list(self._commits)


class FakeGithub:
    """Replace ``dse_oss_reports.queries.Github`` for the duration of a test.

    Construct one ``FakeGithub`` per test, then patch the module-level constructor
    to a lambda that returns it; the lambda accepts ``auth=...`` and ignores it.
    """

    def __init__(
        self,
        repos: dict[str, FakeRepo] | None = None,
        *,
        issue_results: list | None = None,
        pr_results: list | None = None,
    ):
        self.repos = repos or {}
        self.issue_results = issue_results or []
        self.pr_results = pr_results or []
        self.closed = False

    def get_repo(self, full_name: str) -> FakeRepo:
        return self.repos[full_name]

    def search_issues(self, query: str) -> list:
        if "is:issue" in query:
            return list(self.issue_results)
        if "is:pr" in query:
            return list(self.pr_results)
        return []

    def close(self) -> None:
        self.closed = True


def make_fake_resolved(
    *,
    number: int,
    title: str,
    org: str,
    repo: str,
    is_pr: bool,
    author_login: str = "alice",
    state: str = "closed",
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
):
    """Build an object whose attribute shape matches a PyGithub Issue/PR search result."""
    return SimpleNamespace(
        number=number,
        title=title,
        state=state,
        pull_request=SimpleNamespace() if is_pr else None,
        user=SimpleNamespace(login=author_login),
        html_url=f"https://github.com/{org}/{repo}/issues/{number}",
        created_at=created_at or datetime(2026, 2, 1),
        updated_at=updated_at or datetime(2026, 3, 1),
        repository=SimpleNamespace(
            owner=SimpleNamespace(login=org),
            name=repo,
        ),
    )


# ---------------------------------------------------------------------------
# fetch_commits
# ---------------------------------------------------------------------------


def test_fetch_commits_single_task_returns_dataframe(monkeypatch):
    fake_repo = FakeRepo(
        [
            make_fake_commit(
                sha="abc123",
                message="feat: thing",
                author="Alice Example",
                total=42,
                pr_numbers=[],
            )
        ]
    )
    fake = FakeGithub({"acme/widget": fake_repo})
    monkeypatch.setattr("dse_oss_reports.queries.Github", lambda **kw: fake)
    monkeypatch.setattr("dse_oss_reports.queries.Auth", SimpleNamespace(Token=lambda t: t))

    df = fetch_commits(
        token="fake-token",
        tasks=[("acme", "widget", "alice")],
        time_start=datetime(2026, 1, 1),
        time_end=datetime(2026, 4, 1),
    )

    assert list(df.columns) == [
        "sha",
        "message",
        "author",
        "committer",
        "url",
        "total_changes",
        "organization",
        "repository",
    ]
    assert len(df) == 1
    row = df.iloc[0]
    assert row["sha"] == "abc123"
    assert row["message"] == "feat: thing"
    assert row["author"] == "Alice Example"
    assert row["total_changes"] == 42
    assert row["organization"] == "acme"
    assert row["repository"] == "widget"


def test_fetch_commits_collapses_multiple_commits_from_same_pr(monkeypatch):
    # Three commits all merged via PR #42 → one representative row, not three.
    fake_repo = FakeRepo(
        [
            make_fake_commit("aaa", "feat: a", "Alice", pr_numbers=[42]),
            make_fake_commit("bbb", "fix: b", "Alice", pr_numbers=[42]),
            make_fake_commit("ccc", "chore: c", "Alice", pr_numbers=[42]),
        ]
    )
    monkeypatch.setattr(
        "dse_oss_reports.queries.Github",
        lambda **kw: FakeGithub({"acme/widget": fake_repo}),
    )
    monkeypatch.setattr("dse_oss_reports.queries.Auth", SimpleNamespace(Token=lambda t: t))

    df = fetch_commits(
        token=None,
        tasks=[("acme", "widget", "alice")],
        time_start=datetime(2026, 1, 1),
        time_end=datetime(2026, 4, 1),
    )

    assert len(df) == 1
    # The first commit is the representative (matches the existing veda-odd behavior)
    assert df.iloc[0]["sha"] == "aaa"


def test_fetch_commits_keeps_all_standalone_commits_with_no_pr(monkeypatch):
    fake_repo = FakeRepo(
        [
            make_fake_commit("aaa", "feat: a", "Alice", pr_numbers=[]),
            make_fake_commit("bbb", "fix: b", "Alice", pr_numbers=[]),
        ]
    )
    monkeypatch.setattr(
        "dse_oss_reports.queries.Github",
        lambda **kw: FakeGithub({"acme/widget": fake_repo}),
    )
    monkeypatch.setattr("dse_oss_reports.queries.Auth", SimpleNamespace(Token=lambda t: t))

    df = fetch_commits(
        token=None,
        tasks=[("acme", "widget", "alice")],
        time_start=datetime(2026, 1, 1),
        time_end=datetime(2026, 4, 1),
    )

    assert sorted(df["sha"].tolist()) == ["aaa", "bbb"]


def test_fetch_commits_aggregates_rows_across_tasks(monkeypatch):
    repos = {
        "acme/widget": FakeRepo([make_fake_commit("aaa", "x", "Alice", pr_numbers=[])]),
        "globex/doohickey": FakeRepo([make_fake_commit("bbb", "y", "Bob", pr_numbers=[])]),
    }
    monkeypatch.setattr("dse_oss_reports.queries.Github", lambda **kw: FakeGithub(repos))
    monkeypatch.setattr("dse_oss_reports.queries.Auth", SimpleNamespace(Token=lambda t: t))

    df = fetch_commits(
        token=None,
        tasks=[("acme", "widget", "alice"), ("globex", "doohickey", "bob")],
        time_start=datetime(2026, 1, 1),
        time_end=datetime(2026, 4, 1),
    )

    assert sorted(df["sha"].tolist()) == ["aaa", "bbb"]
    assert sorted(df["repository"].tolist()) == ["doohickey", "widget"]


def test_fetch_commits_returns_empty_dataframe_with_columns_when_no_tasks(monkeypatch):
    monkeypatch.setattr("dse_oss_reports.queries.Github", lambda **kw: FakeGithub())
    monkeypatch.setattr("dse_oss_reports.queries.Auth", SimpleNamespace(Token=lambda t: t))

    df = fetch_commits(
        token=None,
        tasks=[],
        time_start=datetime(2026, 1, 1),
        time_end=datetime(2026, 4, 1),
    )

    assert len(df) == 0
    # Columns must still be present so downstream concat / to_csv works
    assert "sha" in df.columns
    assert "organization" in df.columns


def test_fetch_commits_swallows_per_task_errors_and_keeps_other_results(monkeypatch):
    # Only "acme/widget" is present; "acme/missing" raises KeyError on lookup.
    repos = {"acme/widget": FakeRepo([make_fake_commit("ok", "ok", "Alice", pr_numbers=[])])}
    monkeypatch.setattr("dse_oss_reports.queries.Github", lambda **kw: FakeGithub(repos))
    monkeypatch.setattr("dse_oss_reports.queries.Auth", SimpleNamespace(Token=lambda t: t))

    df = fetch_commits(
        token=None,
        tasks=[("acme", "widget", "alice"), ("acme", "missing", "alice")],
        time_start=datetime(2026, 1, 1),
        time_end=datetime(2026, 4, 1),
    )

    # The successful task's row survives; the failing one contributes nothing.
    assert df["sha"].tolist() == ["ok"]


# ---------------------------------------------------------------------------
# fetch_resolved
# ---------------------------------------------------------------------------


def test_fetch_resolved_returns_dataframe_with_expected_columns(monkeypatch):
    fake = FakeGithub(
        issue_results=[
            make_fake_resolved(number=1, title="bug", org="acme", repo="widget", is_pr=False),
        ],
        pr_results=[],
    )
    monkeypatch.setattr("dse_oss_reports.queries.Github", lambda **kw: fake)
    monkeypatch.setattr("dse_oss_reports.queries.Auth", SimpleNamespace(Token=lambda t: t))

    df = fetch_resolved(
        token=None,
        tasks=[("acme", "widget", "alice")],
        contributors=[("Alice Example", "alice")],
        time_start=datetime(2026, 1, 1),
        time_end=datetime(2026, 4, 1),
    )

    assert list(df.columns) == [
        "number",
        "title",
        "type",
        "state",
        "author",
        "url",
        "created_at",
        "updated_at",
        "organization",
        "repository",
        "contributor",
    ]
    assert len(df) == 1
    row = df.iloc[0]
    assert row["number"] == 1
    assert row["type"] == "Issue"
    assert row["organization"] == "acme"
    assert row["contributor"] == "alice"


def test_fetch_resolved_marks_pull_requests_with_type_pr(monkeypatch):
    fake = FakeGithub(
        issue_results=[],
        pr_results=[
            make_fake_resolved(number=7, title="merge", org="acme", repo="widget", is_pr=True),
        ],
    )
    monkeypatch.setattr("dse_oss_reports.queries.Github", lambda **kw: fake)
    monkeypatch.setattr("dse_oss_reports.queries.Auth", SimpleNamespace(Token=lambda t: t))

    df = fetch_resolved(
        token=None,
        tasks=[("acme", "widget", "alice")],
        contributors=[("Alice Example", "alice")],
        time_start=datetime(2026, 1, 1),
        time_end=datetime(2026, 4, 1),
    )

    assert df["type"].tolist() == ["PR"]


def test_fetch_resolved_drops_items_outside_the_configured_task_set(monkeypatch):
    # GitHub search may return items from repos that match the repo: filter but whose
    # (org, repo, contributor) triple isn't in tasks (e.g. the contributor was mentioned
    # in a repo that's only in tasks for a different contributor). Those must be dropped.
    fake = FakeGithub(
        issue_results=[
            make_fake_resolved(number=1, title="in-scope", org="acme", repo="widget", is_pr=False),
            make_fake_resolved(
                number=2, title="out-of-scope", org="acme", repo="other", is_pr=False
            ),
        ],
    )
    monkeypatch.setattr("dse_oss_reports.queries.Github", lambda **kw: fake)
    monkeypatch.setattr("dse_oss_reports.queries.Auth", SimpleNamespace(Token=lambda t: t))

    df = fetch_resolved(
        token=None,
        tasks=[("acme", "widget", "alice")],  # only widget is in tasks
        contributors=[("Alice Example", "alice")],
        time_start=datetime(2026, 1, 1),
        time_end=datetime(2026, 4, 1),
    )

    assert df["repository"].tolist() == ["widget"]
    assert df["number"].tolist() == [1]


def test_fetch_resolved_aggregates_across_contributors(monkeypatch):
    # Both contributors hit the same fake (each thread builds its own client, but our
    # lambda returns the same FakeGithub state — fine for verifying aggregation).
    fake = FakeGithub(
        issue_results=[
            make_fake_resolved(number=1, title="t", org="acme", repo="widget", is_pr=False),
        ],
    )
    monkeypatch.setattr("dse_oss_reports.queries.Github", lambda **kw: fake)
    monkeypatch.setattr("dse_oss_reports.queries.Auth", SimpleNamespace(Token=lambda t: t))

    df = fetch_resolved(
        token=None,
        tasks=[("acme", "widget", "alice"), ("acme", "widget", "bob")],
        contributors=[("Alice Example", "alice"), ("Bob Example", "bob")],
        time_start=datetime(2026, 1, 1),
        time_end=datetime(2026, 4, 1),
    )

    # Each contributor's search returned the same issue; both get a row tagged with
    # their respective contributor (the dedupe step happens at the cli layer).
    assert sorted(df["contributor"].tolist()) == ["alice", "bob"]


def test_fetch_resolved_swallows_per_contributor_errors(monkeypatch):
    # search_issues raises for any query — every contributor's result becomes [].
    class ExplodingGithub(FakeGithub):
        def search_issues(self, query):
            raise RuntimeError("API blew up")

    monkeypatch.setattr("dse_oss_reports.queries.Github", lambda **kw: ExplodingGithub())
    monkeypatch.setattr("dse_oss_reports.queries.Auth", SimpleNamespace(Token=lambda t: t))

    df = fetch_resolved(
        token=None,
        tasks=[("acme", "widget", "alice")],
        contributors=[("Alice Example", "alice")],
        time_start=datetime(2026, 1, 1),
        time_end=datetime(2026, 4, 1),
    )

    # No rows, but the DataFrame still has the right columns for downstream code.
    assert len(df) == 0
    assert "number" in df.columns
    assert "contributor" in df.columns


# ---------------------------------------------------------------------------
# fetch_commits_and_resolved
# ---------------------------------------------------------------------------


def test_fetch_commits_and_resolved_dedups_cross_contributor_resolved_rows(monkeypatch):
    """A single issue surfacing under multiple contributors collapses to one row."""
    fake = FakeGithub(
        repos={
            "acme/widget": FakeRepo(commits=[]),  # no commits — exercise resolved path
        },
        issue_results=[
            # Same issue #42 visible to both alice and bob's search queries
            make_fake_resolved(number=42, title="shared bug", org="acme", repo="widget", is_pr=False),
        ],
    )
    monkeypatch.setattr("dse_oss_reports.queries.Github", lambda **kw: fake)
    monkeypatch.setattr("dse_oss_reports.queries.Auth", SimpleNamespace(Token=lambda t: t))

    _, resolved_df = fetch_commits_and_resolved(
        token=None,
        tasks=[("acme", "widget", "alice"), ("acme", "widget", "bob")],
        contributors=[("Alice Example", "alice"), ("Bob Example", "bob")],
        time_start=datetime(2026, 1, 1),
        time_end=datetime(2026, 4, 1),
        max_workers=2,
    )

    # Issue #42 collapses to one row (vs. the two raw rows fetch_resolved would return).
    assert len(resolved_df) == 1
    assert resolved_df.iloc[0]["number"] == 42
    assert resolved_df.iloc[0]["contributor"] in {"alice", "bob"}


def test_fetch_commits_and_resolved_sorts_resolved_by_org_repo_number(monkeypatch):
    """Sorted output keeps PR-to-PR CSV diffs clean."""
    fake = FakeGithub(
        repos={"acme/widget": FakeRepo(commits=[])},
        issue_results=[
            make_fake_resolved(number=99, title="late", org="acme", repo="widget", is_pr=False),
            make_fake_resolved(number=1, title="early", org="acme", repo="widget", is_pr=False),
            make_fake_resolved(number=42, title="middle", org="acme", repo="widget", is_pr=False),
        ],
    )
    monkeypatch.setattr("dse_oss_reports.queries.Github", lambda **kw: fake)
    monkeypatch.setattr("dse_oss_reports.queries.Auth", SimpleNamespace(Token=lambda t: t))

    _, resolved_df = fetch_commits_and_resolved(
        token=None,
        tasks=[("acme", "widget", "alice")],
        contributors=[("Alice Example", "alice")],
        time_start=datetime(2026, 1, 1),
        time_end=datetime(2026, 4, 1),
        max_workers=1,
    )

    assert resolved_df["number"].tolist() == [1, 42, 99]
