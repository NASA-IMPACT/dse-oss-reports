"""Horizontal bar chart of items-per-repo with objective-based coloring."""

from pathlib import Path

from dse_oss_reports.objectives import ObjectivesDict
from dse_oss_reports.settings import TeamSettings


def plot_counts(
    csv_path: Path,
    pi: str,
    objectives: ObjectivesDict,
    settings: TeamSettings,
    *,
    title: str,
    x_label: str,
    output_path: Path,
    show_labels: bool = False,
) -> Path | None:
    """Render a horizontal bar chart from ``csv_path`` and save to ``output_path``.

    The chart:

    - Counts rows per ``repository`` value.
    - Orders bars ascending so the largest sits at the bottom.
    - Y-axis uses the bare repo name; falls back to ``"{org}/{repo}"`` for repos
      whose name appears under more than one org in the input data.
    - Colors bars by which PI-26.X objective the repo belongs to (split bars for
      repos in multiple objectives, gray for repos with no objective mapping).
    - Title is composed as ``f"{pi.upper()} {settings.team_name} {title}"``; the
      x-axis label is ``x_label`` (typically ``"Number of Commits"`` or ``"Count"``).

    Returns the path written, or ``None`` if the CSV was empty or missing required
    columns (mirrors veda-odd's graceful empty-data handling).
    """
    raise NotImplementedError
