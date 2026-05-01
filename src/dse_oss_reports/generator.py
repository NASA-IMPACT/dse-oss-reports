"""Scrape `pi-X.Y-objective` labelled issues from a planning repo into an OBJECTIVES dict."""

from pathlib import Path

from dse_oss_reports.objectives import ObjectivesDict


class ObjectivesGenerator:
    """Fetch and serialize the OBJECTIVES dataset for a single team's planning repo."""

    def __init__(
        self,
        token: str,
        github_repo: str,
        long_org_name_mapping: dict[str, str] | None = None,
    ) -> None:
        """Configure the generator.

        Args:
            token: A GitHub PAT with ``repo`` and ``read:org`` scope on ``github_repo``.
            github_repo: ``"{org}/{repo}"`` of the team's planning repo.
            long_org_name_mapping: Optional aliases for `repo:` labels whose org name
                exceeds GitHub's label length limit. ``{"cng": "cloudnativegeo"}`` would
                expand a ``repo:cng/zarr-python`` label to ``("cloudnativegeo", "zarr-python")``.
        """
        raise NotImplementedError

    def fetch(self) -> ObjectivesDict:
        """Hit the GitHub search API and build an OBJECTIVES dict keyed by ``"pi-X.Y"``."""
        raise NotImplementedError

    def write_data_module(self, path: Path) -> Path:
        """Render the fetched OBJECTIVES dict as a Python source file at ``path``.

        The file is intended to be committed to the consuming repo as
        ``reports/_objectives_data.py``. Returns ``path`` for chaining.
        """
        raise NotImplementedError
