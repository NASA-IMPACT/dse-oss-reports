"""Render `docs/objectives.md` from an OBJECTIVES dict."""

from dse_oss_reports.objectives import ObjectivesDict
from dse_oss_reports.settings import TeamSettings


def render_objectives_md(
    objectives: ObjectivesDict,
    settings: TeamSettings,
    *,
    current_pi: str | None = None,
    images_dir_relative: str = "images",
) -> str:
    """Build the markdown body of ``docs/objectives.md`` for a team.

    Layout (mirroring the existing per-team scripts):

    - Top-level heading and intro paragraph
    - "Current PI" section with full objective table + commits + resolved-items charts
    - Collapsible ``<details>`` blocks for each historical PI in reverse-chronological order
    - Caveats / configuration footer with a link to the team's ``_objectives_data.py``

    ``current_pi`` defaults to the chronologically latest key in ``objectives``.
    Image links use ``{images_dir_relative}/{pi}-authored-commits.png`` and
    ``{images_dir_relative}/{pi}-resolved-issues-prs.png``.
    """
    raise NotImplementedError
