from pathlib import Path

import pytest

from tests.fixtures.sample_objectives import SAMPLE_OBJECTIVES, SAMPLE_PI_DATES


@pytest.fixture
def sample_objectives() -> dict:
    return SAMPLE_OBJECTIVES


@pytest.fixture
def sample_pi_dates() -> dict:
    return SAMPLE_PI_DATES


@pytest.fixture
def sample_commits_csv() -> Path:
    return Path(__file__).parent / "fixtures" / "sample_commits.csv"
