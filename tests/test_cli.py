"""Tests for cli orchestrators.

These tests stub the lower-level dependencies (fetch_commits, fetch_resolved,
plot_counts, ObjectivesGenerator) at the cli module boundary so the orchestration
logic is exercised in isolation from network and matplotlib.
"""

from datetime import datetime
from pathlib import Path

import pandas as pd

from dse_oss_reports import TeamSettings
from dse_oss_reports.cli import (
    run_commits_report,
    run_generate_config,
    run_generate_docs,
    run_plot_report,
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
# run_commits_report
# ---------------------------------------------------------------------------


def test_run_commits_report_writes_both_csvs_at_harmonized_paths(
    monkeypatch, sample_objectives, sample_pi_dates, tmp_path
):
    captured: dict = {}

    def fake_fetch_combined(
        token, tasks, contributors, time_start, time_end, *, max_workers
    ):
        captured["args"] = (token, tasks, contributors, time_start, time_end, max_workers)
        commits_df = pd.DataFrame(
            [{"sha": "abc", "organization": "acme", "repository": "widget"}]
        )
        resolved_df = pd.DataFrame(
            [{"number": 1, "organization": "acme", "repository": "widget", "contributor": "alice"}]
        )
        return commits_df, resolved_df

    monkeypatch.setattr(
        "dse_oss_reports.cli.fetch_commits_and_resolved", fake_fetch_combined
    )

    paths = run_commits_report(
        token="fake-token",
        settings=make_settings(),
        pi_dates=sample_pi_dates,
        objectives=sample_objectives,
        pi="pi-26.2",
        max_workers=5,
        output_dir=tmp_path,
    )

    # Returned dict points at the right files
    assert paths["commits"] == tmp_path / "pi-26.2-authored-commits.csv"
    assert paths["resolved"] == tmp_path / "pi-26.2-resolved-issues-prs.csv"
    assert paths["commits"].is_file()
    assert paths["resolved"].is_file()

    _, tasks, contributors, ts, te, mw = captured["args"]
    assert mw == 5
    assert ts == datetime(2026, 1, 18)
    assert te == datetime(2026, 4, 25)
    # pi-26.2 has one objective (#103) with [alice, carol] × [(acme, gizmo), (globex, doohickey)]
    assert set(tasks) == {
        ("acme", "gizmo", "alice"),
        ("acme", "gizmo", "carol"),
        ("globex", "doohickey", "alice"),
        ("globex", "doohickey", "carol"),
    }
    assert set(c[1] for c in contributors) == {"alice", "carol"}


def test_run_commits_report_defaults_pi_to_current(
    monkeypatch, sample_objectives, sample_pi_dates, tmp_path
):
    # Force "current PI" to be pi-26.2 by passing today inside its window via patching.
    # Simpler: the resolver picks the latest defined PI when today is outside all windows.
    monkeypatch.setattr(
        "dse_oss_reports.cli.fetch_commits_and_resolved",
        lambda *a, **kw: (pd.DataFrame(), pd.DataFrame()),
    )

    paths = run_commits_report(
        token=None,
        settings=make_settings(),
        pi_dates=sample_pi_dates,
        objectives=sample_objectives,
        # pi omitted → resolver picks current PI based on date or most recent fallback
        output_dir=tmp_path,
    )

    # File names should embed whichever PI was picked; for sample_pi_dates the resolver
    # falls back to pi-26.2 (most recent) when today is outside both windows.
    assert paths["commits"].name in (
        "pi-26.1-authored-commits.csv",
        "pi-26.2-authored-commits.csv",
    )


# ---------------------------------------------------------------------------
# run_plot_report
# ---------------------------------------------------------------------------


def test_run_plot_report_calls_plot_counts_for_both_csvs(
    monkeypatch, sample_objectives, sample_pi_dates, tmp_path
):
    calls: list = []

    def fake_plot_counts(
        csv_path, pi, objectives, settings, *, title, x_label, output_path, show_labels=False
    ):
        calls.append({"csv": csv_path, "out": output_path, "title": title, "x_label": x_label})
        # Simulate a successful plot by touching the output file
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\x89PNG fake")
        return output_path

    monkeypatch.setattr("dse_oss_reports.cli.plot_counts", fake_plot_counts)

    csv_dir = tmp_path / "csvs"
    images_dir = tmp_path / "images"
    csv_dir.mkdir()
    # Pre-create the CSVs so plot_counts has something to read in real use.
    # (Our fake doesn't actually read them; this is just for realism.)
    (csv_dir / "pi-26.2-authored-commits.csv").write_text("sha\n")
    (csv_dir / "pi-26.2-resolved-issues-prs.csv").write_text("number\n")

    paths = run_plot_report(
        settings=make_settings(),
        objectives=sample_objectives,
        pi_dates=sample_pi_dates,
        pi="pi-26.2",
        csv_dir=csv_dir,
        images_dir=images_dir,
    )

    # Two PNGs returned
    assert len(paths) == 2
    assert {p.name for p in paths} == {
        "pi-26.2-authored-commits.png",
        "pi-26.2-resolved-issues-prs.png",
    }

    # plot_counts called once for each CSV with distinct titles
    assert len(calls) == 2
    titles = {c["title"] for c in calls}
    x_labels = {c["x_label"] for c in calls}
    assert any("commits" in t.lower() for t in titles)
    assert any("resolved" in t.lower() for t in titles)
    # Commits chart uses "Number of Commits"; resolved uses "Count" (per the chart-style
    # feedback already established in the workspace).
    assert "Number of Commits" in x_labels
    assert "Count" in x_labels


def test_run_plot_report_drops_paths_for_empty_or_missing_csvs(
    monkeypatch, sample_objectives, sample_pi_dates, tmp_path
):
    # plot_counts returns None when its CSV is missing/empty — orchestrator should
    # exclude those from the returned list.
    def fake_plot_counts(csv_path, *args, output_path, **kwargs):
        if "resolved" in csv_path.name:
            return None  # simulate empty resolved CSV
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\x89PNG fake")
        return output_path

    monkeypatch.setattr("dse_oss_reports.cli.plot_counts", fake_plot_counts)

    paths = run_plot_report(
        settings=make_settings(),
        objectives=sample_objectives,
        pi_dates=sample_pi_dates,
        pi="pi-26.2",
        csv_dir=tmp_path,
        images_dir=tmp_path / "images",
    )
    assert len(paths) == 1
    assert paths[0].name == "pi-26.2-authored-commits.png"


# ---------------------------------------------------------------------------
# run_generate_config
# ---------------------------------------------------------------------------


def test_run_generate_config_constructs_generator_and_writes_to_path(monkeypatch, tmp_path):
    captured: dict = {}

    class FakeGenerator:
        def __init__(self, token, github_repo, long_org_name_mapping=None):
            captured["init"] = (token, github_repo, long_org_name_mapping)

        def write_data_module(self, path: Path) -> Path:
            captured["write"] = path
            path.write_text("OBJECTIVES = {}\n")
            return path

    monkeypatch.setattr("dse_oss_reports.cli.ObjectivesGenerator", FakeGenerator)

    out_path = tmp_path / "_objectives_data.py"
    returned = run_generate_config(
        token="t",
        settings=make_settings(),
        long_org_name_mapping={"cng": "cloudnativegeo"},
        output_path=out_path,
    )

    assert returned == out_path
    assert out_path.is_file()
    # Constructor got token + the team's repo full-name + mapping
    assert captured["init"] == ("t", "NASA-IMPACT/veda-odd", {"cng": "cloudnativegeo"})
    assert captured["write"] == out_path


# ---------------------------------------------------------------------------
# run_generate_docs (no mocking — render_objectives_md is pure)
# ---------------------------------------------------------------------------


def test_run_generate_docs_writes_file_with_rendered_markdown(sample_objectives, tmp_path):
    out_path = tmp_path / "objectives.md"
    returned = run_generate_docs(
        settings=make_settings(),
        objectives=sample_objectives,
        output_path=out_path,
    )

    assert returned == out_path
    contents = out_path.read_text()
    assert contents.startswith("# Quarterly Objectives")
    # Defaults to latest PI
    assert "## Current PI: 26.2" in contents


def test_run_generate_docs_creates_parent_directory_if_missing(sample_objectives, tmp_path):
    out_path = tmp_path / "deeply" / "nested" / "objectives.md"
    run_generate_docs(
        settings=make_settings(),
        objectives=sample_objectives,
        output_path=out_path,
    )
    assert out_path.is_file()
