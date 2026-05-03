"""Horizontal bar chart of items-per-repo with objective-based coloring."""

import logging
import re
from pathlib import Path

import matplotlib

# Use the non-interactive backend so charts render in headless environments (CI, cron).
matplotlib.use("Agg")

import matplotlib.colors as mcolors  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib import colormaps  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402

from dse_oss_reports.objectives import ObjectivesDict  # noqa: E402
from dse_oss_reports.settings import TeamSettings  # noqa: E402

logger = logging.getLogger(__name__)

_NO_OBJECTIVE_COLOR = "#95a5a6"  # gray, for repos that map to no objective


def _build_palette(size: int = 30) -> list[str]:
    """Combine matplotlib's tab20 + tab20b + tab20c (60 distinct hues) → first ``size``."""
    colors: list[str] = []
    for cmap_name in ("tab20", "tab20b", "tab20c"):
        cmap = colormaps[cmap_name]
        for i in range(cmap.N):
            colors.append(mcolors.to_hex(cmap(i)))
            if len(colors) == size:
                return colors
    return colors


# 30-color palette so a team's objective set rarely needs to cycle.
_PALETTE = _build_palette(30)
_EMOJI_RE = re.compile(r"[\U0001F300-\U0001F9FF]")
_OBJECTIVE_PREFIX_RE = re.compile(r"^.*?Objective\s*\d+\s*:\s*")
_TITLE_MAX_LEN = 100


def _repo_labels(df: pd.DataFrame) -> pd.Series:
    """Y-axis label per row: bare repo name; ``"{org}/{repo}"`` only when name collides."""
    orgs_per_name = df.groupby("repository")["organization"].nunique()
    colliding = set(orgs_per_name[orgs_per_name > 1].index)
    return df.apply(
        lambda row: (
            f"{row['organization']}/{row['repository']}"
            if row["repository"] in colliding
            else row["repository"]
        ),
        axis=1,
    )


def _repo_to_objectives(objectives: ObjectivesDict, pi: str) -> dict[str, list[tuple[int, str]]]:
    """Map ``"{org}/{repo}"`` → list of ``(issue_number, title)`` for the PI's objectives."""
    mapping: dict[str, list[tuple[int, str]]] = {}
    for obj in objectives.get(pi, []):
        for org, repo in obj["repos"]:
            mapping.setdefault(f"{org}/{repo}", []).append((obj["issue_number"], obj["title"]))
    return mapping


def _objective_colors(objectives: ObjectivesDict, pi: str) -> dict[int, str]:
    """Map objective issue_number → hex color, cycling through the 30-color palette."""
    return {
        obj["issue_number"]: _PALETTE[i % len(_PALETTE)]
        for i, obj in enumerate(objectives.get(pi, []))
    }


def _objective_short_title(title: str) -> str:
    """Strip ``"TEAM PI X.Y Objective N: "`` prefix and emoji from an objective title."""
    cleaned = _EMOJI_RE.sub("", title).strip()
    cleaned = _OBJECTIVE_PREFIX_RE.sub("", cleaned, count=1)
    if len(cleaned) > _TITLE_MAX_LEN:
        cleaned = cleaned[: _TITLE_MAX_LEN - 3] + "..."
    return cleaned


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
    if not csv_path.exists():
        logger.info("No data at %s; skipping plot.", csv_path)
        return None

    try:
        df = pd.read_csv(csv_path)
    except pd.errors.EmptyDataError:
        df = pd.DataFrame()

    required = {"organization", "repository"}
    if df.empty or not required.issubset(df.columns):
        logger.info("CSV %s has no plotable rows; skipping.", csv_path)
        return None

    df = df.copy()
    df["repo_label"] = _repo_labels(df)
    df["full_repo"] = df["organization"] + "/" + df["repository"]

    # repo_label → full_repo (for objective lookup), and counts per repo_label.
    full_repo_for_label = df.groupby("repo_label")["full_repo"].first().to_dict()
    counts = df["repo_label"].value_counts().sort_values(ascending=True)

    repo_to_objs = _repo_to_objectives(objectives, pi)
    obj_colors = _objective_colors(objectives, pi)

    fig, ax = plt.subplots(1, 1, figsize=(16, max(6, 0.4 * len(counts) + 2)))

    for i, (label, count) in enumerate(counts.items()):
        full = full_repo_for_label.get(label, label)
        objs = repo_to_objs.get(full, [])
        if not objs:
            ax.barh(i, count, color=_NO_OBJECTIVE_COLOR, edgecolor="black", linewidth=1.0)
        elif len(objs) == 1:
            color = obj_colors.get(objs[0][0], _NO_OBJECTIVE_COLOR)
            ax.barh(i, count, color=color, edgecolor="black", linewidth=1.0)
        else:
            width = count / len(objs)
            x = 0
            for issue_num, _t in objs:
                color = obj_colors.get(issue_num, _NO_OBJECTIVE_COLOR)
                ax.barh(i, width, left=x, color=color, edgecolor="black", linewidth=1.0)
                x += width

    ax.set_yticks(range(len(counts)))
    ax.set_yticklabels(counts.index)
    ax.set_xlabel(x_label, fontsize=14, loc="left")
    ax.tick_params(axis="y", labelsize=11)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.grid(axis="x", alpha=0.3)
    ax.set_title(f"{pi.upper()} {settings.team_name} {title}", fontsize=20, fontweight="bold")

    if show_labels:
        for i, v in enumerate(counts.values):
            ax.text(v + 0.5, i, str(v), ha="left", va="center", fontweight="bold")

    if obj_colors:
        legend = [
            Patch(
                facecolor=color,
                edgecolor="black",
                label=_objective_short_title(_title_of(objectives, pi, num)),
            )
            for num, color in obj_colors.items()
        ]
        ax.legend(
            handles=legend,
            loc="lower right",
            fontsize=9,
            title=f"{pi.upper()} Objectives",
            title_fontsize=10,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight", dpi=150)
    plt.close(fig)
    logger.info("Wrote chart to %s", output_path)
    return output_path


def _title_of(objectives: ObjectivesDict, pi: str, issue_number: int) -> str:
    """Look up the title of a specific objective by issue number for legend rendering."""
    for obj in objectives.get(pi, []):
        if obj["issue_number"] == issue_number:
            return obj["title"]
    return f"#{issue_number}"


def plot_combined_counts(
    csv_path: Path,
    pi: str,
    team_objectives: dict[str, ObjectivesDict],
    *,
    title: str,
    x_label: str,
    output_path: Path,
    show_labels: bool = False,
) -> Path | None:
    """Render a multi-team aggregate chart from ``csv_path``.

    Like :func:`plot_counts`, but accepts objectives from multiple teams. Bars are
    colored by objective using a shared palette; the per-team objective spaces are
    namespaced internally on ``(team_name, issue_number)`` so two teams' planning
    repos can both have an objective ``#100`` without collision. Legend entries are
    prefixed with ``[{team_name}]``. Unlike ``plot_counts``, the ``title`` is taken
    verbatim — the caller composes the full title (no ``team_name`` auto-prefix).

    Returns the output path on success, or ``None`` if the CSV is missing/empty.
    """
    if not csv_path.exists():
        logger.info("No data at %s; skipping combined plot.", csv_path)
        return None

    try:
        df = pd.read_csv(csv_path)
    except pd.errors.EmptyDataError:
        df = pd.DataFrame()

    required = {"organization", "repository"}
    if df.empty or not required.issubset(df.columns):
        logger.info("CSV %s has no plotable rows; skipping combined plot.", csv_path)
        return None

    df = df.copy()
    df["repo_label"] = _repo_labels(df)
    df["full_repo"] = df["organization"] + "/" + df["repository"]

    full_repo_for_label = df.groupby("repo_label")["full_repo"].first().to_dict()
    counts = df["repo_label"].value_counts().sort_values(ascending=True)

    # full_repo -> list of (team_name, issue_number) keys it belongs to.
    # (team_name, issue_number) -> color and title.
    repo_to_keys: dict[str, list[tuple[str, int]]] = {}
    obj_colors: dict[tuple[str, int], str] = {}
    obj_titles: dict[tuple[str, int], str] = {}

    color_idx = 0
    for team_name, objectives in team_objectives.items():
        for obj in objectives.get(pi, []):
            key = (team_name, obj["issue_number"])
            obj_colors[key] = _PALETTE[color_idx % len(_PALETTE)]
            obj_titles[key] = obj["title"]
            color_idx += 1
            for org, repo in obj["repos"]:
                repo_to_keys.setdefault(f"{org}/{repo}", []).append(key)

    fig, ax = plt.subplots(1, 1, figsize=(16, max(6, 0.4 * len(counts) + 2)))

    for i, (label, count) in enumerate(counts.items()):
        full = full_repo_for_label.get(label, label)
        keys = repo_to_keys.get(full, [])
        if not keys:
            ax.barh(i, count, color=_NO_OBJECTIVE_COLOR, edgecolor="black", linewidth=1.0)
        elif len(keys) == 1:
            ax.barh(
                i, count, color=obj_colors[keys[0]], edgecolor="black", linewidth=1.0
            )
        else:
            width = count / len(keys)
            x = 0
            for key in keys:
                ax.barh(
                    i, width, left=x, color=obj_colors[key], edgecolor="black", linewidth=1.0
                )
                x += width

    ax.set_yticks(range(len(counts)))
    ax.set_yticklabels(counts.index)
    ax.set_xlabel(x_label, fontsize=14, loc="left")
    ax.tick_params(axis="y", labelsize=11)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.grid(axis="x", alpha=0.3)
    ax.set_title(title, fontsize=20, fontweight="bold")

    if show_labels:
        for i, v in enumerate(counts.values):
            ax.text(v + 0.5, i, str(v), ha="left", va="center", fontweight="bold")

    if obj_colors:
        legend = [
            Patch(
                facecolor=color,
                edgecolor="black",
                label=f"[{team}] {_objective_short_title(obj_titles[(team, num)])}",
            )
            for (team, num), color in obj_colors.items()
        ]
        ax.legend(
            handles=legend,
            loc="lower right",
            fontsize=9,
            title=f"{pi.upper()} Objectives",
            title_fontsize=10,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight", dpi=150)
    plt.close(fig)
    logger.info("Wrote combined chart to %s", output_path)
    return output_path
