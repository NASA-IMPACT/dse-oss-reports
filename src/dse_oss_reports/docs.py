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


def _past_pi_summary(pi_objs: list[dict]) -> str:
    """Render the parenthesized summary suffix for a past-PI ``<details>`` block.

    Always includes original-objective count and both closed buckets (even when
    zero). Appends a ``still open`` segment only when at least one objective is
    still open — common case for past PIs has none. Closed objectives missing a
    ``state_reason`` (legacy data modules) count as completed, matching the
    pre-``state_reason`` GitHub semantics where every closure was implicitly
    "completed".
    """
    total = len(pi_objs)
    not_planned = sum(
        1 for o in pi_objs if o["state"] == "closed" and o.get("state_reason") == "not_planned"
    )
    completed = sum(1 for o in pi_objs if o["state"] == "closed") - not_planned
    still_open = total - completed - not_planned

    segments = [
        f"{total} original objectives",
        f"{completed} closed as completed",
        f"{not_planned} closed as not planned",
    ]
    if still_open:
        segments.append(f"{still_open} still open")
    return "(" + "; ".join(segments) + ")"


def _state_label(obj: dict) -> str:
    """Render an objective's state for the past-PI table.

    Mirrors GitHub's "Closed as completed" / "Closed as not planned" taxonomy:
    closed objectives gain the reason in parentheses when known. Falls back to
    plain ``"closed"`` for legacy data modules that pre-date ``state_reason``.
    """
    state = obj["state"]
    if state != "closed":
        return state
    reason = obj.get("state_reason")
    if reason == "completed":
        return "closed (completed)"
    if reason == "not_planned":
        return "closed (not planned)"
    return "closed"


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
            pi_label = f"PI {pi.split('-')[1]}"
            lines.append("<details markdown>")
            lines.append(f"<summary>{pi_label} {_past_pi_summary(pi_objs)}</summary>")
            lines.append("")
            lines.append("| # | Objective | State | Contributors |")
            lines.append("|---|-----------|-------|--------------|")
            for obj in sorted(pi_objs, key=lambda x: x["issue_number"]):
                num = obj["issue_number"]
                title = _short_objective_title(obj["title"], max_len=50)
                contributors = ", ".join(u for _, u in obj["contributors"]) or "-"
                state_label = _state_label(obj)
                lines.append(
                    f"| [#{num}]({repo_url}/issues/{num}) "
                    f"| {title} | {state_label} | {contributors} |"
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
