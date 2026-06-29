"""Scrub token-shaped strings before they reach disk, logs, or published artifacts.

Applied to every free-text field that gets serialized (manifest ``reason``s). Covers
GitHub token prefixes (classic ``ghp_``, OAuth ``gho_``, server ``ghs_``, refresh
``ghr_``, user-to-server ``ghu_``), fine-grained ``github_pat_`` tokens, and
``Authorization: Bearer …`` headers.
"""

import re

_TOKEN_RE = re.compile(
    r"github_pat_[A-Za-z0-9_]+|gh[a-z]_[A-Za-z0-9]+|Bearer\s+\S+",
)


def redact(text: str | None) -> str:
    """Replace any token-shaped substring with ``[REDACTED]``; ``None`` becomes ``''``."""
    return _TOKEN_RE.sub("[REDACTED]", text or "")
