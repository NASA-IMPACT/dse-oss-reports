from dataclasses import FrozenInstanceError

import pytest

from dse_oss_reports import TeamSettings


def make_settings(**overrides) -> TeamSettings:
    defaults = dict(
        team_name="ODD",
        team_display_name="VEDA/EODC ODD",
        github_org="NASA-IMPACT",
        github_repo="veda-odd",
        site_url="nasa-impact.github.io/veda-odd",
        objectives_page_url="https://nasa-impact.github.io/veda-odd/objectives",
        token_env_var="GH_PAT",
    )
    return TeamSettings(**(defaults | overrides))


def test_repo_full_name_combines_org_and_repo():
    s = make_settings(github_org="NASA-IMPACT", github_repo="science-support")
    assert s.repo_full_name == "NASA-IMPACT/science-support"


def test_settings_are_frozen():
    s = make_settings()
    with pytest.raises(FrozenInstanceError):
        s.team_name = "changed"
