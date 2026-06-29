"""Tests for redact(): scrub token-shaped strings before serialization."""

from dse_oss_reports.redact import redact


def test_redacts_classic_pat():
    assert "ghp_" not in redact("token ghp_abcDEF1234567890abcDEF1234567890")


def test_redacts_fine_grained_pat():
    out = redact("github_pat_11ABCDE0123_aZ09aZ09aZ09")
    assert "github_pat_" not in out
    assert "[REDACTED]" in out


def test_redacts_oauth_and_server_and_refresh_and_user_tokens():
    for prefix in ("gho_", "ghs_", "ghr_", "ghu_"):
        secret = f"{prefix}abcDEF1234567890abcDEF1234567890"
        assert prefix not in redact(f"saw {secret}")


def test_redacts_bearer_header():
    assert "secretvalue" not in redact("Authorization: Bearer secretvalue")


def test_leaves_ordinary_text_untouched():
    assert redact("commits for acme/widget by alice") == "commits for acme/widget by alice"


def test_handles_none_safely():
    assert redact(None) == ""
