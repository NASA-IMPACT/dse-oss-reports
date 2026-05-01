"""Pure helpers for slicing an ``OBJECTIVES`` dict.

Each team's auto-generated ``_objectives_data.py`` defines an ``OBJECTIVES``
dict shaped like::

    {
        "pi-26.2": [
            {
                "issue_number": 123,
                "title": "...",
                "state": "open" | "closed",
                "contributors": [(name, username), ...],
                "repos": [(org, repo), ...],
            },
            ...
        ],
    }

These helpers take that dict as a parameter — the library does not import
``_objectives_data`` from any team's repo.
"""

ObjectivesDict = dict[str, list[dict]]


def get_all_repos(objectives: ObjectivesDict) -> list[tuple[str, str]]:
    """Distinct ``(org, repo)`` tuples across every PI's objectives, sorted."""
    raise NotImplementedError


def get_all_contributors(objectives: ObjectivesDict) -> list[tuple[str, str]]:
    """Distinct ``(name, username)`` tuples across every PI's objectives, sorted by name."""
    raise NotImplementedError


def get_repos_for_pi(objectives: ObjectivesDict, pi: str) -> list[tuple[str, str]]:
    """Distinct ``(org, repo)`` tuples for one PI, sorted."""
    raise NotImplementedError


def get_contributors_for_pi(objectives: ObjectivesDict, pi: str) -> list[tuple[str, str]]:
    """Distinct ``(name, username)`` tuples for one PI, sorted by name."""
    raise NotImplementedError


def get_repos_x_contributors_for_pi(
    objectives: ObjectivesDict, pi: str
) -> list[tuple[str, str, str]]:
    """``(org, repo, username)`` triples explicitly paired in one PI's objectives.

    Returns only the (repo, contributor) combinations that co-occur in a single
    objective — not the cartesian product of all repos × all contributors.
    """
    raise NotImplementedError
