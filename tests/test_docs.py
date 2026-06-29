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


def test_engagement_chart_embedded_for_current_pi(sample_objectives):
    md = render_objectives_md(sample_objectives, make_settings(), current_pi="pi-26.2")
    assert "images/pi-26.2-engagement.png" in md
    assert "foundational engagement" in md


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


def test_past_pi_section_includes_both_image_links_by_default(sample_objectives):
    """Past PIs get both commits + resolved-items image links, mirroring current PI."""
    md = render_objectives_md(sample_objectives, make_settings(), current_pi="pi-26.2")
    assert "images/pi-26.1-authored-commits.png" in md
    assert "images/pi-26.1-resolved-issues-prs.png" in md


def test_image_links_gated_by_images_dir_when_provided(sample_objectives, tmp_path):
    """When images_dir is given, only image links for PNGs that exist on disk are emitted."""
    (tmp_path / "pi-26.2-authored-commits.png").write_bytes(b"")
    (tmp_path / "pi-26.1-resolved-issues-prs.png").write_bytes(b"")
    # pi-26.2-resolved-issues-prs.png and pi-26.1-authored-commits.png intentionally missing.

    md = render_objectives_md(
        sample_objectives,
        make_settings(),
        current_pi="pi-26.2",
        images_dir=tmp_path,
    )

    assert "pi-26.2-authored-commits.png" in md
    assert "pi-26.1-resolved-issues-prs.png" in md
    assert "pi-26.2-resolved-issues-prs.png" not in md
    assert "pi-26.1-authored-commits.png" not in md


def test_images_dir_none_keeps_unconditional_rendering(sample_objectives, tmp_path):
    """Passing images_dir=None (default) renders all four links regardless of filesystem."""
    md = render_objectives_md(
        sample_objectives,
        make_settings(),
        current_pi="pi-26.2",
        images_dir=None,
    )
    assert "pi-26.2-authored-commits.png" in md
    assert "pi-26.2-resolved-issues-prs.png" in md
    assert "pi-26.1-authored-commits.png" in md
    assert "pi-26.1-resolved-issues-prs.png" in md


def test_configuration_footer_links_to_objectives_data_module(sample_objectives):
    md = render_objectives_md(sample_objectives, make_settings())
    # Footer should reference where objectives data lives so readers can edit it.
    assert "_objectives_data.json" in md
    assert "https://github.com/NASA-IMPACT/veda-odd" in md


def test_empty_objectives_renders_just_the_header_without_crashing():
    md = render_objectives_md({}, make_settings())
    assert md.startswith("# Quarterly Objectives")
    # No Current PI section, no past PIs section, but the configuration footer is fine.
    assert "## Current PI:" not in md


def _past_pi_objectives(*specs: tuple[str, str | None]) -> list[dict]:
    """Build a minimal pi-26.1 objectives list from (state, state_reason) tuples."""
    return [
        {
            "issue_number": i,
            "title": f"o{i}",
            "state": state,
            "state_reason": reason,
            "contributors": [],
            "repos": [],
        }
        for i, (state, reason) in enumerate(specs, start=1)
    ]


def _render_with_past_pi(past_pi_objs: list[dict]) -> str:
    """Render `objectives.md` with a past pi-26.1 and a trivial current pi-26.2."""
    objectives = {
        "pi-26.1": past_pi_objs,
        "pi-26.2": [
            {
                "issue_number": 99,
                "title": "Current",
                "state": "open",
                "state_reason": None,
                "contributors": [],
                "repos": [],
            },
        ],
    }
    return render_objectives_md(objectives, make_settings(), current_pi="pi-26.2")


def test_past_pi_summary_renders_total_completed_and_not_planned_counts():
    """Past-PI <summary> always shows original / completed / not-planned counts."""
    md = _render_with_past_pi(
        _past_pi_objectives(
            ("closed", "completed"),
            ("closed", "completed"),
            ("closed", "completed"),
            ("closed", "completed"),
            ("closed", "not_planned"),
            ("closed", "not_planned"),
            ("closed", "not_planned"),
        )
    )
    assert "PI 26.1 (7 original objectives; 4 closed as completed; 3 closed as not planned)" in md


def test_past_pi_summary_appends_still_open_segment_when_some_objectives_are_open():
    md = _render_with_past_pi(
        _past_pi_objectives(
            ("closed", "completed"),
            ("closed", "not_planned"),
            ("open", None),
            ("open", None),
        )
    )
    assert (
        "PI 26.1 (4 original objectives; 1 closed as completed; "
        "1 closed as not planned; 2 still open)"
    ) in md


def test_past_pi_summary_treats_legacy_closed_without_state_reason_as_completed():
    """Pre-``state_reason`` GitHub closed every issue with no reason; count those as completed."""
    legacy_objectives = [
        {
            "issue_number": 1,
            "title": "old",
            "state": "closed",
            "contributors": [],
            "repos": [],
        },  # no state_reason key
        {
            "issue_number": 2,
            "title": "newer",
            "state": "closed",
            "state_reason": "not_planned",
            "contributors": [],
            "repos": [],
        },
    ]
    md = _render_with_past_pi(legacy_objectives)
    assert "PI 26.1 (2 original objectives; 1 closed as completed; 1 closed as not planned)" in md


def test_past_pi_state_column_shows_completion_reason():
    """State column renders 'closed (completed)' / 'closed (not planned)' / 'open' / 'closed'."""
    objectives = {
        "pi-26.1": [
            {
                "issue_number": 1,
                "title": "Done",
                "state": "closed",
                "state_reason": "completed",
                "contributors": [],
                "repos": [],
            },
            {
                "issue_number": 2,
                "title": "Dropped",
                "state": "closed",
                "state_reason": "not_planned",
                "contributors": [],
                "repos": [],
            },
            {
                "issue_number": 3,
                "title": "Still open",
                "state": "open",
                "state_reason": None,
                "contributors": [],
                "repos": [],
            },
            {
                "issue_number": 4,
                "title": "Old issue, no reason",
                "state": "closed",
                # no state_reason key at all — simulates legacy data module
                "contributors": [],
                "repos": [],
            },
        ],
        "pi-26.2": [
            {
                "issue_number": 10,
                "title": "Current",
                "state": "open",
                "state_reason": None,
                "contributors": [],
                "repos": [],
            },
        ],
    }
    md = render_objectives_md(objectives, make_settings(), current_pi="pi-26.2")

    assert "| closed (completed) |" in md
    assert "| closed (not planned) |" in md
    assert "| open |" in md
    # Legacy row with no state_reason key falls back to plain "closed".
    assert "| closed |" in md
