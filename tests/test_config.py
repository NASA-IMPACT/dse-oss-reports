"""Tests for config.load_config."""

from pathlib import Path

import pytest

from dse_oss_reports.config import load_config
from dse_oss_reports.pi_dates import PI_DATES
from dse_oss_reports.settings import TeamSettings

FIXTURE = Path(__file__).parent / "fixtures" / "sample_team.toml"


def test_load_config_parses_team_table_into_team_settings():
    config = load_config(FIXTURE)

    assert isinstance(config.team, TeamSettings)
    assert config.team.team_name == "ODD"
    assert config.team.team_display_name == "VEDA/EODC ODD"
    assert config.team.github_org == "NASA-IMPACT"
    assert config.team.github_repo == "veda-odd"
    assert config.team.site_url == "nasa-impact.github.io/veda-odd"
    assert config.team.objectives_page_url == "https://nasa-impact.github.io/veda-odd/objectives"
    assert config.team.token_env_var == "GH_ODD_PAT"


def test_load_config_pi_dates_overrides_layer_on_library_defaults():
    """The [pi_dates] table merges over the library PI_DATES default, not replacing it."""
    config = load_config(FIXTURE)

    # Library default entries that aren't overridden in the fixture remain present
    assert "pi-25.4" in config.pi_dates
    assert config.pi_dates["pi-25.4"] == PI_DATES["pi-25.4"]
    # Fixture entries take effect (here they happen to match the library values)
    assert config.pi_dates["pi-26.1"] == ("20251019", "20260117")
    assert config.pi_dates["pi-26.2"] == ("20260118", "20260425")


def test_load_config_pi_dates_missing_table_falls_back_to_library_defaults(tmp_path):
    """If [pi_dates] is absent, config.pi_dates is the library's shared PI calendar."""
    minimal = tmp_path / "minimal.toml"
    minimal.write_text(
        """
[team]
name = "X"
display_name = "X team"
github_org = "X-org"
github_repo = "X-repo"
site_url = "x.github.io"
objectives_page_url = "https://x.github.io/o"
token_env_var = "X_PAT"
"""
    )

    config = load_config(minimal)
    assert config.pi_dates == dict(PI_DATES)


def test_load_config_pi_dates_team_override_wins_over_library_default(tmp_path):
    """When team.toml [pi_dates] sets a different window for a known PI, the team value wins."""
    custom = tmp_path / "custom.toml"
    custom.write_text(
        """
[team]
name = "X"
display_name = "X team"
github_org = "X-org"
github_repo = "X-repo"
site_url = "x.github.io"
objectives_page_url = "https://x.github.io/o"
token_env_var = "X_PAT"

[pi_dates]
"pi-26.1" = ["19990101", "19991231"]
"""
    )
    config = load_config(custom)
    assert config.pi_dates["pi-26.1"] == ("19990101", "19991231")
    # Other library defaults remain
    assert config.pi_dates["pi-26.3"] == PI_DATES["pi-26.3"]


def test_load_config_paths_use_documented_defaults_when_table_absent():
    config = load_config(FIXTURE)

    assert config.paths.output_dir == Path("reports/output")
    assert config.paths.images_dir == Path("docs/images")
    assert config.paths.images_dir_relative == "images"
    assert config.paths.docs_output_path == Path("docs/objectives.md")
    assert config.paths.objectives_data_path == Path("reports/_objectives_data.json")


def test_load_config_paths_override_via_table(tmp_path):
    custom = tmp_path / "custom.toml"
    custom.write_text(
        FIXTURE.read_text()
        + """
[paths]
output_dir = "out"
images_dir = "site/img"
images_dir_relative = "img"
docs_output_path = "site/objectives.md"
objectives_data_path = "data.py"
"""
    )
    config = load_config(custom)

    assert config.paths.output_dir == Path("out")
    assert config.paths.images_dir == Path("site/img")
    assert config.paths.images_dir_relative == "img"
    assert config.paths.docs_output_path == Path("site/objectives.md")
    assert config.paths.objectives_data_path == Path("data.py")


def test_load_config_long_org_name_mapping_is_optional():
    config = load_config(FIXTURE)
    assert config.long_org_name_mapping == {}


def test_load_config_long_org_name_mapping_parses_when_present(tmp_path):
    custom = tmp_path / "custom.toml"
    custom.write_text(
        FIXTURE.read_text()
        + """
[long_org_name_mapping]
cng = "cloudnativegeo"
"""
    )
    config = load_config(custom)
    assert config.long_org_name_mapping == {"cng": "cloudnativegeo"}


def test_load_config_missing_team_table_raises_clear_error(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text("[pi_dates]\n")

    with pytest.raises(ValueError, match=r"\[team\]"):
        load_config(bad)


def test_load_config_missing_team_key_names_the_key(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text(
        """
[team]
name = "X"
display_name = "X"
github_org = "X"
github_repo = "X"
site_url = "x"
"""
    )
    with pytest.raises(ValueError, match=r"objectives_page_url"):
        load_config(bad)
