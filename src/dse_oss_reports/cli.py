"""High-level entrypoints that consuming teams' thin scripts call.

These functions add I/O (env-var lookup, CSV/PNG/MD writes) on top of the pure
fetchers, plotters, and renderers. Each team's ``reports/main.py`` etc. is a
~15-line argparse wrapper around one of these.
"""

import logging
from datetime import datetime
from pathlib import Path

from dse_oss_reports.docs import render_objectives_md
from dse_oss_reports.generator import ObjectivesGenerator
from dse_oss_reports.objectives import (
    ObjectivesDict,
    get_contributors_for_pi,
    get_repos_x_contributors_for_pi,
)
from dse_oss_reports.pi_dates import PIDates, get_current_pi, get_time_range
from dse_oss_reports.plot import plot_counts
from dse_oss_reports.queries import fetch_commits, fetch_resolved
from dse_oss_reports.settings import TeamSettings

logger = logging.getLogger(__name__)


def _resolve_pi(pi_dates: PIDates, pi: str | None) -> str:
    """Pick the PI to operate on: explicit ``pi`` if given, else current, else most recent."""
    if pi is not None:
        return pi
    current = get_current_pi(pi_dates)
    if current is not None:
        return current
    # Fallback: most recently defined PI window (matches get_time_range's behavior)
    return next(reversed(pi_dates))


def run_commits_report(
    token: str | None,
    settings: TeamSettings,
    pi_dates: PIDates,
    objectives: ObjectivesDict,
    *,
    pi: str | None = None,
    max_workers: int = 3,
    output_dir: Path = Path("output"),
) -> dict[str, Path]:
    """Fetch authored commits + resolved issues/PRs for one PI, write both CSVs.

    Resolves ``pi`` and the time window from ``pi_dates``, derives tasks from
    ``objectives`` via ``get_repos_x_contributors_for_pi``, runs both query types
    in parallel, and writes ``{output_dir}/{pi}-authored-commits.csv`` and
    ``{output_dir}/{pi}-resolved-issues-prs.csv``. Returns a dict mapping
    ``"commits"`` and ``"resolved"`` to the paths written.
    """
    pi = _resolve_pi(pi_dates, pi)
    start_str, end_str = get_time_range(pi_dates, pi)
    time_start = datetime.strptime(start_str, "%Y%m%d")
    time_end = datetime.strptime(end_str, "%Y%m%d")

    tasks = get_repos_x_contributors_for_pi(objectives, pi)
    contributors = get_contributors_for_pi(objectives, pi)

    logger.info(
        "Running commits report for %s (%s to %s): %d tasks, %d contributors",
        pi,
        start_str,
        end_str,
        len(tasks),
        len(contributors),
    )

    commits_df = fetch_commits(token, tasks, time_start, time_end, max_workers=max_workers)
    resolved_df = fetch_resolved(
        token, tasks, contributors, time_start, time_end, max_workers=max_workers
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    commits_path = output_dir / f"{pi}-authored-commits.csv"
    resolved_path = output_dir / f"{pi}-resolved-issues-prs.csv"
    commits_df.to_csv(commits_path, index=False)
    resolved_df.to_csv(resolved_path, index=False)

    return {"commits": commits_path, "resolved": resolved_path}


def run_plot_report(
    settings: TeamSettings,
    objectives: ObjectivesDict,
    *,
    pi: str | None = None,
    pi_dates: PIDates | None = None,
    csv_dir: Path = Path("output"),
    images_dir: Path = Path("../docs/images"),
    show_labels: bool = False,
) -> list[Path]:
    """Render both per-PI charts (commits + resolved items) to ``images_dir``.

    Reads ``{csv_dir}/{pi}-authored-commits.csv`` and
    ``{csv_dir}/{pi}-resolved-issues-prs.csv``; writes the two PNGs whose names
    swap ``.csv`` for ``.png``. Returns the list of PNG paths actually produced
    (may be shorter than 2 if a CSV was empty/missing).
    """
    if pi is None:
        if pi_dates is None:
            raise ValueError("Either `pi` or `pi_dates` must be provided.")
        pi = _resolve_pi(pi_dates, None)

    chart_specs = [
        (
            csv_dir / f"{pi}-authored-commits.csv",
            images_dir / f"{pi}-authored-commits.png",
            "commits to open source repositories",
            "Number of Commits",
        ),
        (
            csv_dir / f"{pi}-resolved-issues-prs.csv",
            images_dir / f"{pi}-resolved-issues-prs.png",
            "resolved issues and PRs",
            "Count",
        ),
    ]

    produced: list[Path] = []
    for csv_path, out_path, title, x_label in chart_specs:
        result = plot_counts(
            csv_path,
            pi,
            objectives,
            settings,
            title=title,
            x_label=x_label,
            output_path=out_path,
            show_labels=show_labels,
        )
        if result is not None:
            produced.append(result)
    return produced


def run_generate_config(
    token: str,
    settings: TeamSettings,
    *,
    long_org_name_mapping: dict[str, str] | None = None,
    output_path: Path = Path("_objectives_data.py"),
) -> Path:
    """Scrape the team's planning repo and write ``_objectives_data.py``.

    Writes to ``output_path`` (defaults to the consuming repo's ``reports/_objectives_data.py``
    when invoked with cwd at ``reports/``). Returns the path written.
    """
    generator = ObjectivesGenerator(
        token=token,
        github_repo=settings.repo_full_name,
        long_org_name_mapping=long_org_name_mapping,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return generator.write_data_module(output_path)


def run_generate_docs(
    settings: TeamSettings,
    objectives: ObjectivesDict,
    *,
    current_pi: str | None = None,
    images_dir_relative: str = "images",
    output_path: Path = Path("../docs/objectives.md"),
) -> Path:
    """Render the team's ``docs/objectives.md`` from the OBJECTIVES dict.

    ``output_path`` defaults to the consuming repo's ``docs/objectives.md`` when
    invoked with cwd at ``reports/``. Returns the path written.
    """
    markdown = render_objectives_md(
        objectives,
        settings,
        current_pi=current_pi,
        images_dir_relative=images_dir_relative,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown)
    return output_path
