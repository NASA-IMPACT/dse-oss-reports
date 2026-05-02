"""Tests for docs.render_objectives_md."""

from dse_oss_reports import TeamSettings
from dse_oss_reports.docs import render_objectives_md


def make_settings(**overrides) -> TeamSettings:
    defaults = dict(
        team_name="ODD",
        team_display_name="VEDA/EODC ODD",
        github_org="NASA-IMPACT",
        github_repo="veda-odd",
        site_url="example.github.io/team",
        objectives_page_url="https://example.com/team/objectives",
        token_env_var="GH_PAT",
    )
    return TeamSettings(**(defaults | overrides))


def test_renders_top_level_title_and_intro(sample_objectives):
    md = render_objectives_md(sample_objectives, make_settings())
    assert md.startswith("# Quarterly Objectives")
    # Intro mentions Program Increments so readers know the framing.
    assert "Program Increment" in md


def test_current_pi_defaults_to_chronologically_latest(sample_objectives):
    md = render_objectives_md(sample_objectives, make_settings())
    # sample_objectives has pi-26.1 and pi-26.2 → 26.2 is latest
    assert "## Current PI: 26.2" in md
    assert "## Current PI: 26.1" not in md


def test_current_pi_can_be_overridden(sample_objectives):
    md = render_objectives_md(sample_objectives, make_settings(), current_pi="pi-26.1")
    assert "## Current PI: 26.1" in md
    assert "## Current PI: 26.2" not in md


def test_current_pi_section_includes_both_image_links(sample_objectives):
    md = render_objectives_md(sample_objectives, make_settings(), current_pi="pi-26.2")
    # Harmonized filenames: -authored-commits.png + -resolved-issues-prs.png
    assert "images/pi-26.2-authored-commits.png" in md
    assert "images/pi-26.2-resolved-issues-prs.png" in md


def test_image_dir_can_be_overridden(sample_objectives):
    md = render_objectives_md(
        sample_objectives, make_settings(), current_pi="pi-26.2", images_dir_relative="figures"
    )
    assert "figures/pi-26.2-authored-commits.png" in md
    assert "images/pi-26.2-authored-commits.png" not in md


def test_current_pi_section_renders_objective_table_rows(sample_objectives):
    md = render_objectives_md(sample_objectives, make_settings(), current_pi="pi-26.2")
    # Table header
    assert "| # | Objective | Contributors | Repos |" in md
    # Issue link should point at the team's repo
    assert "[#103](https://github.com/NASA-IMPACT/veda-odd/issues/103)" in md
    # Repos column: bare repo names joined
    assert "gizmo, doohickey" in md or "gizmo" in md  # accept either ordering


def test_past_pis_are_collapsed_into_details_blocks(sample_objectives):
    md = render_objectives_md(sample_objectives, make_settings(), current_pi="pi-26.2")
    # pi-26.1 is past → wrapped in <details>
    assert "<details" in md
    assert "PI 26.1" in md or "pi-26.1" in md.lower()
    assert "</details>" in md


def test_configuration_footer_links_to_objectives_data_module(sample_objectives):
    md = render_objectives_md(sample_objectives, make_settings())
    # Footer should reference where objectives data lives so readers can edit it.
    assert "_objectives_data.py" in md
    assert "https://github.com/NASA-IMPACT/veda-odd" in md


def test_empty_objectives_renders_just_the_header_without_crashing():
    md = render_objectives_md({}, make_settings())
    assert md.startswith("# Quarterly Objectives")
    # No Current PI section, no past PIs section, but the configuration footer is fine.
    assert "## Current PI:" not in md
