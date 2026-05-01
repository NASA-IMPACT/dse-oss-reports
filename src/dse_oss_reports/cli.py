"""High-level entrypoints that consuming teams' thin scripts call.

These functions add I/O (env-var lookup, CSV/PNG/MD writes) on top of the pure
fetchers, plotters, and renderers. Each team's ``reports/main.py`` etc. is a
~15-line argparse wrapper around one of these.
"""

from pathlib import Path

from dse_oss_reports.objectives import ObjectivesDict
from dse_oss_reports.pi_dates import PIDates
from dse_oss_reports.settings import TeamSettings


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
    raise NotImplementedError


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
    raise NotImplementedError


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
    raise NotImplementedError


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
    raise NotImplementedError
