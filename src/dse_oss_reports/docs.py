"""Render `docs/objectives.md` from an OBJECTIVES dict."""

from dse_oss_reports.objectives import ObjectivesDict
from dse_oss_reports.settings import TeamSettings

_TITLE_MAX = 60


def _short_objective_title(title: str, max_len: int = _TITLE_MAX) -> str:
    """Strip a leading ``"... Objective N: "`` prefix and truncate."""
    if "Objective" in title and ":" in title:
        title = title.split(":", 1)[1].strip()
    if len(title) > max_len:
        title = title[: max_len - 3] + "..."
    return title


def _sorted_pis(objectives: ObjectivesDict, *, reverse: bool = True) -> list[str]:
    """PI keys ordered by their numeric component (e.g. 26.2 > 26.1)."""
    return sorted(objectives.keys(), key=lambda x: float(x.split("-")[1]), reverse=reverse)


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
    repo_url = f"https://github.com/{settings.repo_full_name}"
    lines = [
        "# Quarterly Objectives",
        "",
        f"This page tracks quarterly objectives for the {settings.team_display_name} team "
        "and the open-source repositories they touch across Program Increments (PIs).",
        "",
    ]

    if not objectives:
        lines.extend(_render_footer(repo_url))
        return "\n".join(lines)

    if current_pi is None:
        current_pi = _sorted_pis(objectives, reverse=True)[0]

    # Current PI section
    pi_short = current_pi.split("-")[1]
    lines.append(f"## Current PI: {pi_short}")
    lines.append("")
    lines.append(
        f"![{current_pi.upper()} authored commits]"
        f"({images_dir_relative}/{current_pi}-authored-commits.png)"
    )
    lines.append("")
    lines.append(
        f"![{current_pi.upper()} resolved issues and PRs]"
        f"({images_dir_relative}/{current_pi}-resolved-issues-prs.png)"
    )
    lines.append("")
    lines.append("| # | Objective | Contributors | Repos |")
    lines.append("|---|-----------|--------------|-------|")
    for obj in sorted(objectives[current_pi], key=lambda x: x["issue_number"]):
        num = obj["issue_number"]
        title = _short_objective_title(obj["title"])
        contributors = ", ".join(u for _, u in obj["contributors"]) or "-"
        repos = ", ".join(r for _, r in obj["repos"]) or "-"
        lines.append(f"| [#{num}]({repo_url}/issues/{num}) | {title} | {contributors} | {repos} |")
    lines.append("")

    # Past PIs (reverse chronological, in collapsible blocks)
    past_pis = [pi for pi in _sorted_pis(objectives, reverse=True) if pi != current_pi]
    if past_pis:
        lines.append("---")
        lines.append("")
        lines.append("## Past PIs")
        lines.append("")
        for pi in past_pis:
            pi_objs = objectives[pi]
            closed = sum(1 for o in pi_objs if o["state"] == "closed")
            pi_label = f"PI {pi.split('-')[1]}"
            lines.append("<details markdown>")
            lines.append(
                f"<summary>{pi_label} ({len(pi_objs)} objectives, {closed} closed)</summary>"
            )
            lines.append("")
            lines.append("| # | Objective | State | Contributors |")
            lines.append("|---|-----------|-------|--------------|")
            for obj in sorted(pi_objs, key=lambda x: x["issue_number"]):
                num = obj["issue_number"]
                title = _short_objective_title(obj["title"], max_len=50)
                contributors = ", ".join(u for _, u in obj["contributors"]) or "-"
                lines.append(
                    f"| [#{num}]({repo_url}/issues/{num}) "
                    f"| {title} | {obj['state']} | {contributors} |"
                )
            lines.append("")
            lines.append(
                f"![{pi.upper()} authored commits]({images_dir_relative}/{pi}-authored-commits.png)"
            )
            lines.append("")
            lines.append("</details>")
            lines.append("")

    lines.extend(_render_footer(repo_url))
    return "\n".join(lines)


def _render_footer(repo_url: str) -> list[str]:
    return [
        "---",
        "",
        "## Configuration",
        "",
        f"Objectives data lives in [`reports/_objectives_data.py`]"
        f"({repo_url}/blob/main/reports/_objectives_data.py) — auto-generated from "
        "GitHub issues by `dse_oss_reports.generator.ObjectivesGenerator`.",
        "",
        "To regenerate this page:",
        "",
        "```bash",
        "cd reports",
        "uv run generate_docs.py",
        "```",
        "",
    ]
