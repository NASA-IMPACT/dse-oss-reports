"""Tests for generator.ObjectivesGenerator and the private render helpers."""

import json
from types import SimpleNamespace

import pytest

from dse_oss_reports.generator import (
    ObjectivesGenerator,
    _render_data_json,
    _render_data_module,
)

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
                "state_reason": None,
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


def make_fake_issue(*, number, title, state, label_names, assignees, state_reason=None):
    """Build an object whose attribute shape matches a PyGithub issue search result."""
    return SimpleNamespace(
        number=number,
        title=title,
        state=state,
        state_reason=state_reason,
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
                "state_reason": None,
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


def test_fetch_captures_state_reason_for_not_planned_issues(monkeypatch):
    """An issue closed as "not planned" must carry state_reason="not_planned"."""
    fake = FakeGithub(
        [
            make_fake_issue(
                number=12,
                title="Dropped objective",
                state="closed",
                state_reason="not_planned",
                label_names=["pi-26.2-objective", "repo:acme/widget"],
                assignees=[],
            )
        ]
    )
    patch_github(monkeypatch, fake)

    gen = ObjectivesGenerator(token="fake", github_repo="NASA-IMPACT/test-team")
    result = gen.fetch()

    assert result["pi-26.2"][0]["state_reason"] == "not_planned"
    assert result["pi-26.2"][0]["state"] == "closed"


def test_render_data_json_round_trips_through_json_load(sample_objectives):
    """JSON render → json.loads should reproduce the dict (with tuples → lists)."""
    source = _render_data_json(sample_objectives)
    rebuilt = json.loads(source)

    # Walk both structures, normalizing tuples to lists for comparison.
    def to_lists(obj):
        if isinstance(obj, dict):
            return {k: to_lists(v) for k, v in obj.items()}
        if isinstance(obj, list | tuple):
            return [to_lists(x) for x in obj]
        return obj

    assert rebuilt == to_lists(sample_objectives)


def test_write_data_module_writes_json_when_extension_is_json(monkeypatch, tmp_path):
    """Passing a .json path makes write_data_module emit JSON, not Python source."""
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
    out_path = tmp_path / "_objectives_data.json"
    returned = gen.write_data_module(out_path)

    assert returned == out_path
    data = json.loads(out_path.read_text())
    assert data == {
        "pi-26.2": [
            {
                "issue_number": 42,
                "title": "Test objective",
                "state": "open",
                "state_reason": None,
                "contributors": [["Alice Example", "alice"]],
                "repos": [["acme", "widget"]],
            }
        ]
    }


def test_write_data_module_rejects_unsupported_extension(monkeypatch, tmp_path):
    fake = FakeGithub([])
    patch_github(monkeypatch, fake)

    gen = ObjectivesGenerator(token="fake", github_repo="NASA-IMPACT/test-team")
    with pytest.raises(ValueError, match=r"\.json or \.py"):
        gen.write_data_module(tmp_path / "data.yaml")


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
                "state_reason": None,
                "contributors": [("Alice Example", "alice")],
                "repos": [("acme", "widget")],
            }
        ]
    }
