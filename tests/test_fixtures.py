"""Sanity checks on the test fixtures themselves.

If a future change to the fixture pack breaks downstream tests, these spot-checks
make the cause obvious.
"""

import pandas as pd

from tests.fixtures.sample_objectives import SAMPLE_OBJECTIVES, SAMPLE_PI_DATES


def test_sample_objectives_shape():
    assert set(SAMPLE_OBJECTIVES) == {"pi-26.1", "pi-26.2"}
    for objs in SAMPLE_OBJECTIVES.values():
        for obj in objs:
            assert {"issue_number", "title", "state", "contributors", "repos"} <= obj.keys()
            assert obj["state"] in {"open", "closed"}


def test_sample_pi_dates_shape():
    for pi, (start, end) in SAMPLE_PI_DATES.items():
        assert pi.startswith("pi-")
        assert len(start) == 8 and len(end) == 8


def test_sample_commits_csv_columns(sample_commits_csv):
    df = pd.read_csv(sample_commits_csv)
    expected = {
        "sha",
        "message",
        "author",
        "committer",
        "url",
        "total_changes",
        "organization",
        "repository",
    }
    assert expected <= set(df.columns)
    assert len(df) == 4
