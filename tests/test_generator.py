"""Tests for generator.ObjectivesGenerator and the private render helper."""

from types import SimpleNamespace

from dse_oss_reports.generator import ObjectivesGenerator, _render_data_module

# ---------------------------------------------------------------------------
# Render helper (pure, no network)
# ---------------------------------------------------------------------------


def test_render_round_trips_through_exec(sample_objectives):
    """Rendering then `exec`-ing the result should rebuild the original dict.

    This is the strongest test for the renderer: any quoting bug, missing comma,
    or shape regression will break the round-trip.
    """
    source = _render_data_module(sample_objectives)
    namespace: dict = {}
    exec(source, namespace)
    rebuilt = namespace["OBJECTIVES"]

    # The rendered repos are tuples literally; the source dict has tuples too.
    # Compare directly.
    assert rebuilt == sample_objectives


def test_render_escapes_quotes_in_titles_and_names():
    tricky = {
        "pi-26.1": [
            {
                "issue_number": 1,
                "title": 'Title with "quotes" and a backslash \\ in it',
                "state": "open",
                "contributors": [('Name with "quotes"', "user")],
                "repos": [],
            }
        ]
    }
    source = _render_data_module(tricky)
    namespace: dict = {}
    exec(source, namespace)
    assert namespace["OBJECTIVES"] == tricky


# ---------------------------------------------------------------------------
# ObjectivesGenerator.fetch (mocked PyGithub)
# ---------------------------------------------------------------------------


def make_fake_issue(*, number, title, state, label_names, assignees):
    """Build an object whose attribute shape matches a PyGithub issue search result."""
    return SimpleNamespace(
        number=number,
        title=title,
        state=state,
        labels=[SimpleNamespace(name=n) for n in label_names],
        assignees=[SimpleNamespace(name=name, login=login) for name, login in assignees],
    )


class FakeGithub:
    """Mock for `github.Github` in the generator module."""

    def __init__(self, issues):
        self._issues = list(issues)

    def search_issues(self, query):  # noqa: ARG002 — query is unused in the fake
        return list(self._issues)

    def close(self):
        pass


def patch_github(monkeypatch, fake):
    monkeypatch.setattr("dse_oss_reports.generator.Github", lambda **_kw: fake)
    monkeypatch.setattr("dse_oss_reports.generator.Auth", SimpleNamespace(Token=lambda t: t))


def test_fetch_groups_one_issue_under_its_pi(monkeypatch):
    fake = FakeGithub(
        [
            make_fake_issue(
                number=101,
                title="ODD PI 26.1 Objective: Test",
                state="open",
                label_names=["pi-26.1-objective", "repo:acme/widget"],
                assignees=[("Alice Example", "alice")],
            )
        ]
    )
    patch_github(monkeypatch, fake)

    gen = ObjectivesGenerator(token="fake", github_repo="NASA-IMPACT/test-team")
    result = gen.fetch()

    assert result == {
        "pi-26.1": [
            {
                "issue_number": 101,
                "title": "ODD PI 26.1 Objective: Test",
                "state": "open",
                "contributors": [("Alice Example", "alice")],
                "repos": [("acme", "widget")],
            }
        ]
    }


def test_fetch_expands_long_org_name_mapping(monkeypatch):
    # GitHub label length limit means org names sometimes need abbreviation.
    # The mapping expands "cng" → "cloudnativegeo" before storing the repo tuple.
    fake = FakeGithub(
        [
            make_fake_issue(
                number=1,
                title="t",
                state="open",
                label_names=["pi-26.2-objective", "repo:cng/zarr-python"],
                assignees=[],
            )
        ]
    )
    patch_github(monkeypatch, fake)

    gen = ObjectivesGenerator(
        token="fake",
        github_repo="NASA-IMPACT/test-team",
        long_org_name_mapping={"cng": "cloudnativegeo"},
    )
    result = gen.fetch()

    assert result["pi-26.2"][0]["repos"] == [("cloudnativegeo", "zarr-python")]


def test_fetch_skips_issues_without_a_pi_label(monkeypatch):
    fake = FakeGithub(
        [
            make_fake_issue(
                number=999,
                title="not an objective",
                state="open",
                label_names=["bug", "repo:acme/widget"],  # no pi-X.Y-objective label
                assignees=[],
            )
        ]
    )
    patch_github(monkeypatch, fake)

    gen = ObjectivesGenerator(token="fake", github_repo="NASA-IMPACT/test-team")
    assert gen.fetch() == {}


def test_fetch_falls_back_to_login_when_assignee_name_is_none(monkeypatch):
    # PyGithub returns name=None for users who haven't set a display name.
    fake = FakeGithub(
        [
            make_fake_issue(
                number=1,
                title="t",
                state="open",
                label_names=["pi-26.2-objective"],
                assignees=[(None, "ghost")],
            )
        ]
    )
    patch_github(monkeypatch, fake)

    gen = ObjectivesGenerator(token="fake", github_repo="NASA-IMPACT/test-team")
    result = gen.fetch()
    assert result["pi-26.2"][0]["contributors"] == [("ghost", "ghost")]


def test_fetch_groups_multiple_issues_under_their_respective_pis(monkeypatch):
    fake = FakeGithub(
        [
            make_fake_issue(
                number=1,
                title="A",
                state="closed",
                label_names=["pi-26.1-objective"],
                assignees=[],
            ),
            make_fake_issue(
                number=2,
                title="B",
                state="open",
                label_names=["pi-26.2-objective"],
                assignees=[],
            ),
            make_fake_issue(
                number=3,
                title="C",
                state="open",
                label_names=["pi-26.2-objective"],
                assignees=[],
            ),
        ]
    )
    patch_github(monkeypatch, fake)

    gen = ObjectivesGenerator(token="fake", github_repo="NASA-IMPACT/test-team")
    result = gen.fetch()
    assert set(result.keys()) == {"pi-26.1", "pi-26.2"}
    assert len(result["pi-26.1"]) == 1
    assert len(result["pi-26.2"]) == 2


# ---------------------------------------------------------------------------
# ObjectivesGenerator.write_data_module
# ---------------------------------------------------------------------------


def test_write_data_module_writes_round_trippable_source(monkeypatch, tmp_path):
    fake = FakeGithub(
        [
            make_fake_issue(
                number=42,
                title="Test objective",
                state="open",
                label_names=["pi-26.2-objective", "repo:acme/widget"],
                assignees=[("Alice Example", "alice")],
            )
        ]
    )
    patch_github(monkeypatch, fake)

    gen = ObjectivesGenerator(token="fake", github_repo="NASA-IMPACT/test-team")
    out_path = tmp_path / "_objectives_data.py"
    returned = gen.write_data_module(out_path)

    assert returned == out_path
    assert out_path.is_file()

    namespace: dict = {}
    exec(out_path.read_text(), namespace)
    assert namespace["OBJECTIVES"] == {
        "pi-26.2": [
            {
                "issue_number": 42,
                "title": "Test objective",
                "state": "open",
                "contributors": [("Alice Example", "alice")],
                "repos": [("acme", "widget")],
            }
        ]
    }
