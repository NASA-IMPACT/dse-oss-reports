# dse-oss-reports

Shared reporting library + reusable GitHub workflow for tracking open-source contributions by NASA-ODSI DSE teams (currently `veda-odd` and `science-support`; designed to onboard additional teams with ~3 files of glue).

A consuming team's repo needs:

1. A `team.toml` describing the team, its tracked PIs, and any path overrides.
2. A ~15-line `.github/workflows/update-reports.yml` that calls the reusable workflow on a weekly cron.
3. An MkDocs `mkdocs.yml` for the published docs site.

The reusable workflow runs `dse-oss-reports run-all` against the consumer's `team.toml`, regenerates the objectives data + per-PI CSVs + charts + `docs/objectives.md`, and opens a PR.

## Status

Pre-release. API may change before `v0.1.0`. The reusable workflow's contract (inputs, secret name) will track a moving `v1` major tag once published.

## Adoption guide

### Step 1: Create `team.toml` at your repo root

```toml
[team]
name = "ODD"                                                  # short, for chart titles
display_name = "VEDA/EODC ODD"                                # full, for chart caveats
github_org = "NASA-IMPACT"                                    # org that owns the planning repo
github_repo = "veda-odd"                                      # repo where pi-X.Y-objective issues live
site_url = "nasa-impact.github.io/veda-odd"                   # GitHub Pages URL (no scheme)
objectives_page_url = "https://nasa-impact.github.io/veda-odd/objectives"
token_env_var = "GH_ODD_PAT"                                  # legacy fallback for local scripts

[long_org_name_mapping]   # optional — aliases for `repo:` labels whose org exceeds GH's label length
cng = "cloudnativegeo"

[paths]                   # all optional; defaults shown
output_dir = "reports/output"
images_dir = "docs/images"
images_dir_relative = "images"
docs_output_path = "docs/objectives.md"
objectives_data_path = "reports/_objectives_data.json"
```

The PI calendar (`PI_DATES`) and recognized label set (`_PI_LABELS`) are library-managed — every team inherits them by ref. If a team genuinely needs a non-standard window, add an optional `[pi_dates]` table that overrides individual entries:

```toml
[pi_dates]
"pi-26.1" = ["20251015", "20260120"]   # team-specific window; other PIs inherit from the library
```

### Step 2: Add the reusable workflow caller

`.github/workflows/update-reports.yml`:

```yaml
name: Update Reports
on:
  schedule:
    - cron: '0 14 * * 1'   # Mondays 9am ET (14:00 UTC)
  workflow_dispatch:

jobs:
  reports:
    uses: NASA-IMPACT/dse-oss-reports/.github/workflows/reports.yml@v0.2.0
    permissions:
      contents: write
      pull-requests: write
    with:
      dse-oss-reports-ref: v0.2.0   # pin to a tag/SHA — never to a moving branch
    secrets:
      pat: ${{ secrets.GH_ODD_PAT }}   # secret name is up to you; the workflow sees it as `pat`
```

Then add the PAT in **Settings → Secrets and variables → Actions** under whatever name you referenced.

### Step 3: Add an MkDocs site

`.github/workflows/deploy.yml`:

```yaml
name: Deploy docs
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v7
        with:
          version: "0.9.*"
          enable-cache: true
      - run: uv run mkdocs gh-deploy --force --strict
```

Root `pyproject.toml`:

```toml
[dependency-groups]
dev = [
    "mkdocs>=1.6.1",
    "mkdocs-material[imaging]>=9.6.3",
    "mike>=2.1.3",
]
```

`mkdocs.yml`:

```yaml
site_name: Your Team Reports
nav:
  - "index.md"
  - PI Objectives: "objectives.md"

theme:
  name: material

plugins:
  - search
```

Preview locally with `uv run mkdocs serve`.

### Step 4: Set up objective-driven labeling

Objectives are GitHub Issues with two labels:

- `pi-{YY}.{Q}-objective` (e.g. `pi-26.2-objective`) — marks the issue as a quarterly objective.
- `repo:{org}/{repo-name}` — maps the issue to a repository the work touches. One label per repo.

Contributors come from issue assignees. The set of recognized PI labels (`dse_oss_reports.generator._PI_LABELS`) and the shared PI calendar (`dse_oss_reports.pi_dates.PI_DATES`) are library-managed; opening a PR there is how you onboard a new PI for every team at once.

Add `.github/ISSUE_TEMPLATE/objective.md` so team members propose objectives consistently:

```markdown
---
name: Propose objective
about: Objective for the team
title: 'PI 26.2 Objective X: ...'
labels: pi-26.2-objective
assignees: ''
---

### Motivation

### Description

### Acceptance Criteria

- [ ] ...
```

### Step 5: Run it

Trigger the workflow manually (`workflow_dispatch`) or wait for the cron. It opens a PR with:

- `reports/_objectives_data.json` — auto-generated from your `pi-*-objective` issues
- `reports/output/{pi}-authored-commits.csv` and `reports/output/{pi}-resolved-issues-prs.csv`
- `docs/images/{pi}-*.png`
- `docs/objectives.md`

Merge the PR. The deploy workflow publishes to GitHub Pages.

### Quarterly maintenance

1. Update the issue template's `labels:` and `title:` to the new PI.
2. Create objective issues for the quarter; the next cron run picks them up.

The library handles the rest org-wide: when a new PI starts being tracked, open a PR against `dse-oss-reports` adding the entry to `PI_DATES` (in `dse_oss_reports/pi_dates.py`) and `_PI_LABELS` (in `dse_oss_reports/generator.py`), tag a release, and have each team bump their `dse-oss-reports-ref`.

## CLI reference

The reusable workflow runs `uvx --from "dse-oss-reports @ git+...@<ref>" dse-oss-reports --config team.toml run-all`. You can run the same locally:

```bash
uvx --from "dse-oss-reports @ git+https://github.com/NASA-IMPACT/dse-oss-reports.git@v0.2.0" \
  dse-oss-reports --config team.toml run-all
```

Subcommands:

| Subcommand | What it does |
|---|---|
| `current-pi` | Print the resolved PI and exit (useful for shell scripts) |
| `generate-config` | Scrape GitHub issues into `reports/_objectives_data.json` |
| `fetch` | Fetch authored commits + resolved items into `reports/output/*.csv` |
| `plot` | Render per-PI PNGs from the fetched CSVs |
| `generate-docs` | Render `docs/objectives.md` from the objectives data |
| `run-all` | Run all four stages in order (what the cron uses) |

Global flags: `--config PATH` (defaults to `./team.toml`), `-v/--verbose`. Stage subcommands also accept `--pi pi-26.2` to override PI resolution.

### Token resolution

The CLI looks up the GitHub PAT in this order:

1. `DSE_OSS_REPORTS_TOKEN` (the reusable workflow sets this from the `pat` secret)
2. The env var named by `[team].token_env_var` in `team.toml` (legacy)
3. `GITHUB_TOKEN`

## Reusable workflow inputs

| Input | Default | Notes |
|---|---|---|
| `config-path` | `team.toml` | Path to your config in the calling repo |
| `dse-oss-reports-ref` | `v0.2.0` | Always pin to a tag or full SHA |
| `uv-version` | `0.9.*` | Pinned uv version |
| `pr-branch` | `update-reports` | Branch name for the generated PR |

Secrets: `pat` (required) — a fine-grained PAT with public-repo read access.

## Python API (advanced / legacy)

The `dse_oss_reports.cli.run_*` functions (`run_commits_report`, `run_plot_report`, `run_generate_config`, `run_generate_docs`) remain available for teams that need to wire custom orchestration around the pipeline. New teams should prefer the CLI + reusable workflow.

Install from a consuming repo's `pyproject.toml`:

```toml
[project]
dependencies = [
    "dse-oss-reports @ git+https://github.com/NASA-IMPACT/dse-oss-reports.git@v0.2.0",
]
```

## Troubleshooting

| Problem | Solution |
|---|---|
| `generate-config` finds no issues | Check `pi-*-objective` labels and that the PI label is in `dse_oss_reports.generator._PI_LABELS` |
| `FileNotFoundError: _objectives_data.json` | Run `generate-config` first, or use `run-all` |
| Chart is empty | Check the per-PI CSV in `reports/output/`; verify the PI's window in the library's `PI_DATES` (or your `[pi_dates]` override, if any) |
| PR not created by Actions | Confirm the calling workflow's job has `contents: write` and `pull-requests: write` |
| MkDocs build fails | Run `uv run mkdocs build --strict` locally to see errors |

## Development

```bash
uv sync --all-extras
uv run pytest
uv run ruff check
```

## License

Apache 2.0 — see [LICENSE](./LICENSE).
