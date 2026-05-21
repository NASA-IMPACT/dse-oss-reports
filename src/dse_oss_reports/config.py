"""Load a team's reporting config from a TOML file."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from dse_oss_reports.pi_dates import PIDates
from dse_oss_reports.settings import TeamSettings


@dataclass(frozen=True)
class Paths:
    """Filesystem locations the CLI reads from and writes to."""

    output_dir: Path = Path("reports/output")
    images_dir: Path = Path("docs/images")
    images_dir_relative: str = "images"
    docs_output_path: Path = Path("docs/objectives.md")
    objectives_data_path: Path = Path("reports/_objectives_data.json")


@dataclass(frozen=True)
class Config:
    """Parsed contents of a team's ``team.toml``."""

    team: TeamSettings
    pi_dates: PIDates = field(default_factory=dict)
    paths: Paths = field(default_factory=Paths)
    long_org_name_mapping: dict[str, str] = field(default_factory=dict)


_REQUIRED_TEAM_KEYS = (
    "name",
    "display_name",
    "github_org",
    "github_repo",
    "site_url",
    "objectives_page_url",
    "token_env_var",
)


def _load_paths(data: dict) -> Paths:
    paths_table = data.get("paths", {})
    defaults = Paths()
    return Paths(
        output_dir=Path(paths_table.get("output_dir", defaults.output_dir)),
        images_dir=Path(paths_table.get("images_dir", defaults.images_dir)),
        images_dir_relative=paths_table.get("images_dir_relative", defaults.images_dir_relative),
        docs_output_path=Path(paths_table.get("docs_output_path", defaults.docs_output_path)),
        objectives_data_path=Path(
            paths_table.get("objectives_data_path", defaults.objectives_data_path)
        ),
    )


def load_config(path: Path) -> Config:
    """Parse ``path`` (a ``team.toml``) into a typed ``Config`` object.

    Raises ``ValueError`` if the ``[team]`` table is missing or incomplete; the
    error message names the missing key(s) so callers can fix the file.
    """
    path = Path(path)
    with path.open("rb") as f:
        data = tomllib.load(f)

    if "team" not in data:
        raise ValueError(f"{path}: missing required [team] table")

    team_table = data["team"]
    missing = [k for k in _REQUIRED_TEAM_KEYS if k not in team_table]
    if missing:
        raise ValueError(f"{path}: [team] missing required keys: {', '.join(missing)}")

    team = TeamSettings(
        team_name=team_table["name"],
        team_display_name=team_table["display_name"],
        github_org=team_table["github_org"],
        github_repo=team_table["github_repo"],
        site_url=team_table["site_url"],
        objectives_page_url=team_table["objectives_page_url"],
        token_env_var=team_table["token_env_var"],
    )
    pi_dates: PIDates = {pi: (start, end) for pi, (start, end) in data.get("pi_dates", {}).items()}
    return Config(
        team=team,
        pi_dates=pi_dates,
        paths=_load_paths(data),
        long_org_name_mapping=dict(data.get("long_org_name_mapping", {})),
    )
