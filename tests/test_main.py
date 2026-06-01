"""Tests for the dse-oss-reports CLI (in-process via main())."""

import subprocess
from pathlib import Path

import pytest

from dse_oss_reports.main import _load_objectives, main

FIXTURE = Path(__file__).parent / "fixtures" / "sample_team.toml"


def test_current_pi_prints_resolved_pi(capsys):
    """current-pi prints a PI — from the merged [pi_dates] table (library defaults + overrides)."""
    from dse_oss_reports.pi_dates import PI_DATES

    out_code = main(["--config", str(FIXTURE), "current-pi"])

    captured = capsys.readouterr()
    assert out_code == 0
    # The exact PI depends on today's date vs the shared library calendar; any defined PI is OK.
    assert captured.out.strip() in PI_DATES


def test_main_returns_nonzero_on_unknown_subcommand():
    code = main(["--config", str(FIXTURE), "nonsense-cmd"])
    assert code != 0


def test_generate_config_invokes_run_generate_config_with_resolved_token(monkeypatch, tmp_path):
    """generate-config resolves a token from env and writes to paths.objectives_data_path."""
    captured: dict = {}

    def fake_run(token, settings, *, long_org_name_mapping, output_path):
        captured["token"] = token
        captured["settings"] = settings
        captured["mapping"] = long_org_name_mapping
        captured["output_path"] = output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("{}\n")
        return output_path

    monkeypatch.setattr("dse_oss_reports.main.run_generate_config", fake_run)
    monkeypatch.setenv("DSE_OSS_REPORTS_TOKEN", "ci-token-value")
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "team.toml"
    config_path.write_text(FIXTURE.read_text())

    code = main(["--config", str(config_path), "generate-config"])

    assert code == 0
    assert captured["token"] == "ci-token-value"
    assert captured["settings"].team_name == "ODD"
    assert captured["output_path"] == Path("reports/_objectives_data.json")


def test_token_resolution_falls_back_to_team_token_env_var(monkeypatch, tmp_path):
    """When DSE_OSS_REPORTS_TOKEN is unset, fall back to team.token_env_var."""
    captured: dict = {}

    def fake_run(token, settings, *, long_org_name_mapping, output_path):
        captured["token"] = token
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("{}\n")
        return output_path

    monkeypatch.setattr("dse_oss_reports.main.run_generate_config", fake_run)
    monkeypatch.delenv("DSE_OSS_REPORTS_TOKEN", raising=False)
    monkeypatch.setenv("GH_ODD_PAT", "team-specific-token")
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "team.toml"
    config_path.write_text(FIXTURE.read_text())

    code = main(["--config", str(config_path), "generate-config"])
    assert code == 0
    assert captured["token"] == "team-specific-token"


def test_fetch_invokes_run_commits_report_with_loaded_objectives(monkeypatch, tmp_path):
    """fetch loads OBJECTIVES from paths.objectives_data_path and calls run_commits_report."""
    captured: dict = {}

    def fake_run(token, settings, pi_dates, objectives, *, pi, max_workers, output_dir):
        captured.update(
            token=token,
            pi=pi,
            pi_dates_keys=list(pi_dates.keys()),
            objectives=objectives,
            output_dir=output_dir,
            max_workers=max_workers,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        return {
            "commits": output_dir / f"{pi}-authored-commits.csv",
            "resolved": output_dir / f"{pi}-resolved-issues-prs.csv",
        }

    monkeypatch.setattr("dse_oss_reports.main.run_commits_report", fake_run)
    monkeypatch.setattr(
        "dse_oss_reports.main.run_engagement_report",
        lambda *a, **kw: {"engagement": Path("x")},
    )
    monkeypatch.setenv("DSE_OSS_REPORTS_TOKEN", "ci-token")
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "team.toml"
    config_path.write_text(FIXTURE.read_text())
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "_objectives_data.json").write_text(
        '{"pi-26.2": [{"issue_number": 1, "title": "x", "state": "open", '
        '"state_reason": null, "contributors": [], "repos": []}]}\n'
    )

    code = main(["--config", str(config_path), "fetch", "--pi", "pi-26.2"])

    assert code == 0
    assert captured["pi"] == "pi-26.2"
    assert "pi-26.2" in captured["pi_dates_keys"]
    assert "pi-26.2" in captured["objectives"]
    assert captured["output_dir"] == Path("reports/output")


def test_fetch_also_invokes_run_engagement_report(monkeypatch, tmp_path):
    """fetch calls run_engagement_report alongside run_commits_report."""
    captured: dict = {}

    def fake_commits(token, settings, pi_dates, objectives, *, pi, max_workers, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        return {"commits": output_dir / f"{pi}-authored-commits.csv"}

    def fake_engagement(token, settings, pi_dates, objectives, *, pi, max_workers, output_dir):
        captured["pi"] = pi
        captured["output_dir"] = output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        return {"engagement": output_dir / f"{pi}-engagement.csv"}

    monkeypatch.setattr("dse_oss_reports.main.run_commits_report", fake_commits)
    monkeypatch.setattr("dse_oss_reports.main.run_engagement_report", fake_engagement)
    monkeypatch.setenv("DSE_OSS_REPORTS_TOKEN", "ci-token")
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "team.toml"
    config_path.write_text(FIXTURE.read_text())
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "_objectives_data.json").write_text(
        '{"pi-26.2": [{"issue_number": 1, "title": "x", "state": "open", '
        '"state_reason": null, "contributors": [], "repos": []}]}\n'
    )

    code = main(["--config", str(config_path), "fetch", "--pi", "pi-26.2"])

    assert code == 0
    assert captured["pi"] == "pi-26.2"
    assert captured["output_dir"] == Path("reports/output")


def test_plot_invokes_run_plot_report_with_config_paths(monkeypatch, tmp_path):
    captured: dict = {}

    def fake_run(settings, objectives, *, pi, pi_dates, csv_dir, images_dir, show_labels=False):
        captured.update(
            pi=pi,
            csv_dir=csv_dir,
            images_dir=images_dir,
            show_labels=show_labels,
        )
        return []

    monkeypatch.setattr("dse_oss_reports.main.run_plot_report", fake_run)
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "team.toml"
    config_path.write_text(FIXTURE.read_text())
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "_objectives_data.json").write_text("{}\n")

    code = main(["--config", str(config_path), "plot", "--pi", "pi-26.2"])

    assert code == 0
    assert captured["pi"] == "pi-26.2"
    assert captured["csv_dir"] == Path("reports/output")
    assert captured["images_dir"] == Path("docs/images")


def test_generate_docs_invokes_run_generate_docs_with_config_paths(monkeypatch, tmp_path):
    captured: dict = {}

    def fake_run(settings, objectives, *, current_pi, images_dir_relative, output_path):
        captured.update(
            current_pi=current_pi,
            images_dir_relative=images_dir_relative,
            output_path=output_path,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("# stub\n")
        return output_path

    monkeypatch.setattr("dse_oss_reports.main.run_generate_docs", fake_run)
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "team.toml"
    config_path.write_text(FIXTURE.read_text())
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "_objectives_data.json").write_text("{}\n")

    code = main(["--config", str(config_path), "generate-docs"])

    assert code == 0
    assert captured["images_dir_relative"] == "images"
    assert captured["output_path"] == Path("docs/objectives.md")


def test_run_all_runs_four_subcommands_in_order(monkeypatch, tmp_path):
    """run-all dispatches generate-config → fetch → plot → generate-docs."""
    calls: list[str] = []

    def fake_gen_config(token, settings, *, long_org_name_mapping, output_path):
        calls.append("generate-config")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("{}\n")
        return output_path

    def make_fake(name):
        def fake(*args, **kwargs):
            calls.append(name)
            return None

        return fake

    monkeypatch.setattr("dse_oss_reports.main.run_generate_config", fake_gen_config)
    monkeypatch.setattr("dse_oss_reports.main.run_commits_report", make_fake("fetch"))
    monkeypatch.setattr("dse_oss_reports.main.run_engagement_report", lambda *a, **kw: None)
    monkeypatch.setattr("dse_oss_reports.main.run_plot_report", make_fake("plot"))
    monkeypatch.setattr("dse_oss_reports.main.run_generate_docs", make_fake("generate-docs"))
    monkeypatch.setenv("DSE_OSS_REPORTS_TOKEN", "ci-token")
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "team.toml"
    config_path.write_text(FIXTURE.read_text())

    code = main(["--config", str(config_path), "run-all"])

    assert code == 0
    assert calls == ["generate-config", "fetch", "plot", "generate-docs"]


def test_load_objectives_reads_json_file(tmp_path):
    """_load_objectives dispatches to json.load for .json paths — no code execution."""
    path = tmp_path / "data.json"
    path.write_text(
        '{"pi-26.2": [{"issue_number": 1, "title": "x", "state": "open", '
        '"state_reason": null, "contributors": [], "repos": []}]}'
    )
    result = _load_objectives(path)

    assert "pi-26.2" in result
    assert result["pi-26.2"][0]["issue_number"] == 1


def test_load_objectives_reads_py_file_for_back_compat(tmp_path):
    """_load_objectives still loads legacy .py modules so wrapper-script consumers work."""
    path = tmp_path / "data.py"
    path.write_text(
        'OBJECTIVES = {"pi-26.2": [{"issue_number": 7, "title": "y", "state": "open", '
        '"state_reason": None, "contributors": [], "repos": []}]}\n'
    )
    result = _load_objectives(path)

    assert result["pi-26.2"][0]["issue_number"] == 7


def test_load_objectives_rejects_unsupported_extension(tmp_path):
    path = tmp_path / "data.yaml"
    path.write_text("foo: bar\n")
    with pytest.raises(ValueError, match=r"\.json or \.py"):
        _load_objectives(path)


def test_console_script_is_installed_and_runs():
    """`dse-oss-reports --help` works as an installed console script."""
    result = subprocess.run(
        ["dse-oss-reports", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "current-pi" in result.stdout
    assert "run-all" in result.stdout
