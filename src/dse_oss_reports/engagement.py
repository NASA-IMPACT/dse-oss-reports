"""Foundational "engagement" contributions: reviews, comments, discussions, opened issues.

A complement to ``queries.py`` (directed work). For each tracked contributor in
each curated repo, over the PI window, counts the *distinct items* (issues, PRs,
discussions) they engaged with by reviewing, commenting, opening (issues), or
participating in a discussion. Each item is counted once per contributor (kinds
collapsed); a contributor's own authored PRs are excluded as directed work.
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)

Task = tuple[str, str, str]  # (org, repo, username)
Contributor = tuple[str, str]  # (name, username)

_ENGAGEMENT_COLUMNS = [
    "number",
    "title",
    "type",
    "url",
    "engagement_kinds",
    "created_at",
    "updated_at",
    "organization",
    "repository",
    "contributor",
]

# Raw-record keys produced by the source fetchers before dedupe.
_RAW_KEYS = [
    "number",
    "title",
    "type",
    "url",
    "kind",
    "author",
    "created_at",
    "updated_at",
    "organization",
    "repository",
    "contributor",
]


def _dedupe_engagement(rows: list[dict]) -> pd.DataFrame:
    """Collapse raw activity records into one row per distinct (contributor, item).

    - Drops records for PRs the contributor authored (directed work).
    - Groups by (organization, repository, number, contributor); the per-item
      ``engagement_kinds`` column is the sorted, comma-joined set of ``kind``s.
    - Sorts by (organization, repository, number, contributor) for stable output.
    """
    kept = [r for r in rows if not (r["type"] == "PullRequest" and r["author"] == r["contributor"])]
    if not kept:
        return pd.DataFrame(columns=_ENGAGEMENT_COLUMNS)

    raw = pd.DataFrame(kept, columns=_RAW_KEYS)
    raw["number"] = raw["number"].astype("Int64")
    group_keys = ["organization", "repository", "number", "contributor"]

    # Aggregate kinds separately, then join with the first-occurrence metadata.
    kinds_agg = (
        raw.groupby(group_keys, sort=False)["kind"]
        .agg(lambda s: ",".join(sorted(set(s))))
        .rename("engagement_kinds")
        .reset_index()
    )
    first_meta = raw.drop_duplicates(subset=group_keys)[
        group_keys + ["title", "type", "url", "created_at", "updated_at"]
    ]
    collapsed = kinds_agg.merge(first_meta, on=group_keys, how="left")
    return collapsed[_ENGAGEMENT_COLUMNS].sort_values(by=group_keys).reset_index(drop=True)
