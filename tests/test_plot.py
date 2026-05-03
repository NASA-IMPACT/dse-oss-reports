"""Tests for plot.plot_counts and its private helpers."""

import pandas as pd

from dse_oss_reports import TeamSettings
from dse_oss_reports.plot import (
    _objective_colors,
    _objective_short_title,
    _repo_labels,
    _repo_to_objectives,
    plot_combined_counts,
    plot_counts,
)


def make_settings(**overrides) -> TeamSettings:
    defaults = dict(
        team_name="ODD",
        team_display_name="VEDA/EODC ODD",
        github_org="NASA-IMPACT",
        github_repo="veda-odd",
        site_url="example.github.io/team",
        objectives_page_url="https://example.com/team/objectives",
        token_env_var="GH_PAT",
    )
    return TeamSettings(**(defaults | overrides))


# ---------------------------------------------------------------------------
# _repo_labels
# ---------------------------------------------------------------------------


def test_repo_labels_uses_bare_name_when_unique_across_orgs():
    df = pd.DataFrame(
        [
            {"organization": "acme", "repository": "widget"},
            {"organization": "globex", "repository": "doohickey"},
        ]
    )
    labels = _repo_labels(df)
    # series indexed by source row
    assert list(labels) == ["widget", "doohickey"]


def test_repo_labels_falls_back_to_org_repo_for_colliding_names():
    df = pd.DataFrame(
        [
            {"organization": "acme", "repository": "widget"},
            {"organization": "globex", "repository": "widget"},  # same repo name, different org
            {"organization": "acme", "repository": "gizmo"},
        ]
    )
    labels = _repo_labels(df)
    assert list(labels) == ["acme/widget", "globex/widget", "gizmo"]


# ---------------------------------------------------------------------------
# _repo_to_objectives
# ---------------------------------------------------------------------------


def test_repo_to_objectives_groups_objectives_by_full_repo(sample_objectives):
    mapping = _repo_to_objectives(sample_objectives, "pi-26.1")
    # widget appears in both objectives 101 and 102
    assert mapping["acme/widget"] == [
        (101, "Sample PI 26.1 Objective A"),
        (102, "Sample PI 26.1 Objective B"),
    ]
    # gizmo only in 102
    assert mapping["acme/gizmo"] == [(102, "Sample PI 26.1 Objective B")]


def test_repo_to_objectives_returns_empty_for_unknown_pi(sample_objectives):
    assert _repo_to_objectives(sample_objectives, "pi-99.9") == {}


# ---------------------------------------------------------------------------
# _objective_colors
# ---------------------------------------------------------------------------


def test_objective_colors_assigns_a_distinct_color_per_objective(sample_objectives):
    colors = _objective_colors(sample_objectives, "pi-26.1")
    # pi-26.1 has 2 objectives (#101, #102) → 2 keys, 2 distinct hex values
    assert set(colors.keys()) == {101, 102}
    assert len(set(colors.values())) == 2
    for color in colors.values():
        assert color.startswith("#") and len(color) == 7


def test_objective_colors_cycles_palette_when_more_than_palette_size():
    # 32 objectives > 30-color palette → every objective still gets a color
    # (colors at the cycle boundary repeat; that's acceptable).
    big = {
        "pi-99.9": [
            {
                "issue_number": n,
                "title": f"Obj {n}",
                "state": "open",
                "contributors": [],
                "repos": [],
            }
            for n in range(1, 33)
        ]
    }
    colors = _objective_colors(big, "pi-99.9")
    assert set(colors.keys()) == set(range(1, 33))
    # First 30 colors are distinct (no cycling yet); after that some repeat.
    first_30 = [colors[n] for n in range(1, 31)]
    assert len(set(first_30)) == 30


# ---------------------------------------------------------------------------
# _objective_short_title
# ---------------------------------------------------------------------------


def test_objective_short_title_strips_team_pi_prefix():
    assert (
        _objective_short_title("ODD PI 25.2 Objective 7: Increase data format support")
        == "Increase data format support"
    )


def test_objective_short_title_strips_emoji_then_prefix():
    # Emojis sometimes appear at the start of objective titles for visual flavor;
    # the rendered legend should drop them.
    assert (
        _objective_short_title("🎉 Science Support PI 26.1 Objective 3: Test thing") == "Test thing"
    )


def test_objective_short_title_truncates_very_long_titles():
    long = "X" * 200
    out = _objective_short_title(long)
    assert len(out) <= 100
    assert out.endswith("...")


# ---------------------------------------------------------------------------
# plot_counts
# ---------------------------------------------------------------------------


def test_plot_counts_writes_non_empty_png(sample_commits_csv, sample_objectives, tmp_path):
    out_path = tmp_path / "out.png"
    settings = make_settings()

    returned = plot_counts(
        csv_path=sample_commits_csv,
        pi="pi-26.1",
        objectives=sample_objectives,
        settings=settings,
        title="commits to default branches",
        x_label="Number of Commits",
        output_path=out_path,
    )

    assert returned == out_path
    assert out_path.is_file()
    # PNG header is "\x89PNG"; any non-empty file starts with that for matplotlib output.
    contents = out_path.read_bytes()
    assert contents[:4] == b"\x89PNG"
    assert len(contents) > 1000  # arbitrary lower bound — a real chart, not an error stub


def test_plot_counts_returns_none_when_csv_missing(sample_objectives, tmp_path):
    settings = make_settings()
    returned = plot_counts(
        csv_path=tmp_path / "nope.csv",
        pi="pi-26.1",
        objectives=sample_objectives,
        settings=settings,
        title="commits",
        x_label="Number of Commits",
        output_path=tmp_path / "out.png",
    )
    assert returned is None
    assert not (tmp_path / "out.png").exists()


def test_plot_counts_returns_none_when_csv_has_no_rows(sample_objectives, tmp_path):
    empty_csv = tmp_path / "empty.csv"
    empty_csv.write_text("sha,message,author,committer,url,total_changes,organization,repository\n")
    out_path = tmp_path / "out.png"
    settings = make_settings()

    returned = plot_counts(
        csv_path=empty_csv,
        pi="pi-26.1",
        objectives=sample_objectives,
        settings=settings,
        title="commits",
        x_label="Number of Commits",
        output_path=out_path,
    )
    assert returned is None
    assert not out_path.exists()


# ---------------------------------------------------------------------------
# plot_combined_counts
# ---------------------------------------------------------------------------


def test_plot_combined_counts_handles_colliding_issue_numbers_across_teams(
    sample_commits_csv, tmp_path
):
    """Two teams whose planning repos both number objective #101 must not collide."""
    team_a = {
        "pi-26.1": [
            {
                "issue_number": 101,
                "title": "Team A Objective Alpha",
                "state": "open",
                "contributors": [],
                "repos": [("acme", "widget")],
            }
        ]
    }
    team_b = {
        "pi-26.1": [
            {
                "issue_number": 101,  # same number as team_a — must be namespaced
                "title": "Team B Objective Beta",
                "state": "open",
                "contributors": [],
                "repos": [("acme", "gizmo")],
            }
        ]
    }

    out_path = tmp_path / "combined.png"
    returned = plot_combined_counts(
        csv_path=sample_commits_csv,
        pi="pi-26.1",
        team_objectives={"team-a": team_a, "team-b": team_b},
        team_settings={
            "team-a": make_settings(team_name="A", team_display_name="Team A"),
            "team-b": make_settings(team_name="B", team_display_name="Team B"),
        },
        title="PI-26.1 VEDA combined commits",
        x_label="Number of Commits",
        output_path=out_path,
    )

    assert returned == out_path
    assert out_path.is_file()
    contents = out_path.read_bytes()
    assert contents[:4] == b"\x89PNG"
    assert len(contents) > 1000


def test_plot_combined_counts_returns_none_for_missing_csv(sample_objectives, tmp_path):
    returned = plot_combined_counts(
        csv_path=tmp_path / "nope.csv",
        pi="pi-26.1",
        team_objectives={"team-a": sample_objectives},
        team_settings={"team-a": make_settings()},
        title="combined",
        x_label="Number of Commits",
        output_path=tmp_path / "out.png",
    )
    assert returned is None
    assert not (tmp_path / "out.png").exists()


def test_plot_combined_counts_rejects_mismatched_team_keys(sample_objectives, tmp_path):
    import pytest

    with pytest.raises(ValueError, match="identical keys"):
        plot_combined_counts(
            csv_path=tmp_path / "irrelevant.csv",
            pi="pi-26.1",
            team_objectives={"team-a": sample_objectives},
            team_settings={"team-b": make_settings()},  # mismatched
            title="combined",
            x_label="Number of Commits",
            output_path=tmp_path / "out.png",
        )
