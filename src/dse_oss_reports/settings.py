"""Team-specific configuration passed in to the library at the call site.

Each consuming team constructs one frozen `TeamSettings` instance (typically
in their `reports/settings.py`) and threads it through the library entrypoints
in `dse_oss_reports.cli`. The library never imports team config directly.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TeamSettings:
    """Identifiers used in chart titles, caveats, doc links, and env-var lookup."""

    team_name: str
    """Short name used in chart titles (e.g. ``"ODD"``, ``"Science Support"``)."""

    team_display_name: str
    """Full name used in caveats text (e.g. ``"VEDA/EODC ODD"``)."""

    github_org: str
    """GitHub organization that hosts the team's planning repo (e.g. ``"NASA-IMPACT"``)."""

    github_repo: str
    """Repo where this team's `pi-X.Y-objective` issues live (e.g. ``"veda-odd"``)."""

    site_url: str
    """GitHub Pages URL for the team's docs site, no scheme (e.g. ``example.github.io/team``)."""

    objectives_page_url: str
    """Full https URL of the rendered objectives page, used in chart caveats."""

    token_env_var: str
    """Environment variable name holding the team's GitHub PAT (e.g. ``"GH_PAT"``)."""

    @property
    def repo_full_name(self) -> str:
        """Convenience: ``"{github_org}/{github_repo}"``."""
        return f"{self.github_org}/{self.github_repo}"
