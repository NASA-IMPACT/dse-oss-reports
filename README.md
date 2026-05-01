# dse-oss-reports

Shared reporting library for tracking open-source contributions by NASA-ODSI DSE teams (currently `veda-odd` and `science-support`; designed to onboard additional teams with ~50 lines of glue).

The library provides:

- GitHub queries for authored commits and resolved issues/PRs across configured `(org, repo, contributor)` triples
- An objective-issue scraper that turns `pi-X.Y-objective` labelled issues into a structured `OBJECTIVES` dict
- A horizontal bar-chart renderer for commits-per-repo, with objective-based coloring and split-bar support for multi-objective repos
- A markdown renderer for an `objectives.md` docs page
- argparse-based CLI factories so each team's `reports/main.py` is a thin entrypoint

## Status

Pre-release. API may change before `v0.1.0`.

## Installation (from a consuming team's `reports/pyproject.toml`)

```toml
[project]
dependencies = [
    "dse-oss-reports @ git+https://github.com/NASA-IMPACT/dse-oss-reports.git@v0.1.0",
]
```

`pandas`, `matplotlib`, and `pygithub` come in as transitive dependencies — consuming repos don't need to declare them separately. Pin to a specific tag (or SHA) so library upgrades are explicit.

## Development

```bash
uv sync --all-extras
uv run pytest
uv run ruff check
```

## License

Apache 2.0 — see [LICENSE](./LICENSE).
