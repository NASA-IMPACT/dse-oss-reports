"""Argparse CLI for `dse-oss-reports`. Drives the pipeline from a single team.toml."""

import argparse
import importlib.util
import json
import logging
import os
import sys
from pathlib import Path

from dse_oss_reports.cli import (
    run_commits_report,
    run_engagement_report,
    run_generate_config,
    run_generate_docs,
    run_plot_report,
)
from dse_oss_reports.config import Config, load_config
from dse_oss_reports.objectives import ObjectivesDict
from dse_oss_reports.pi_dates import get_current_pi

logger = logging.getLogger(__name__)


def _resolve_token(config: Config) -> str | None:
    """Layered token lookup: DSE_OSS_REPORTS_TOKEN → team.token_env_var → GITHUB_TOKEN."""
    return (
        os.environ.get("DSE_OSS_REPORTS_TOKEN")
        or os.environ.get(config.team.token_env_var)
        or os.environ.get("GITHUB_TOKEN")
    )


def _require_token(config: Config) -> str | None:
    token = _resolve_token(config)
    if not token:
        print(
            f"No token found (checked DSE_OSS_REPORTS_TOKEN, "
            f"{config.team.token_env_var}, GITHUB_TOKEN)",
            file=sys.stderr,
        )
    return token


def _load_objectives(path: Path) -> ObjectivesDict:
    """Load OBJECTIVES from ``path``, picking format by extension.

    ``.json`` (preferred) is loaded with ``json.load`` — no code execution. ``.py`` is
    loaded via importlib for back-compat with existing wrapper-script consumers, which is
    inherently RCE-prone: anyone with merge access to the consuming repo can put arbitrary
    Python in ``_objectives_data.py`` and have it run under the next CI invocation. New
    consumers should use ``.json`` (the CLI's default in ``Paths.objectives_data_path``).
    """
    if not path.exists():
        raise FileNotFoundError(f"{path} not found — run `dse-oss-reports generate-config` first")
    if path.suffix == ".json":
        with path.open() as f:
            return json.load(f)
    if path.suffix == ".py":
        spec = importlib.util.spec_from_file_location("_objectives_data", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load module from {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.OBJECTIVES
    raise ValueError(
        f"Unsupported objectives data extension {path.suffix!r}; expected .json or .py"
    )


def _cmd_current_pi(config: Config, args: argparse.Namespace) -> int:
    pi = get_current_pi(config.pi_dates)
    if pi is None and config.pi_dates:
        pi = list(config.pi_dates.keys())[-1]
    if pi is None:
        print("(no PI defined in [pi_dates])", file=sys.stderr)
        return 1
    print(pi)
    return 0


def _cmd_generate_config(config: Config, args: argparse.Namespace) -> int:
    token = _require_token(config)
    if not token:
        return 1
    run_generate_config(
        token,
        config.team,
        long_org_name_mapping=config.long_org_name_mapping,
        output_path=config.paths.objectives_data_path,
    )
    return 0


def _cmd_fetch(config: Config, args: argparse.Namespace) -> int:
    token = _require_token(config)
    if not token:
        return 1
    objectives = _load_objectives(config.paths.objectives_data_path)
    run_commits_report(
        token,
        config.team,
        config.pi_dates,
        objectives,
        pi=args.pi,
        max_workers=args.max_workers,
        output_dir=config.paths.output_dir,
    )
    run_engagement_report(
        token,
        config.team,
        config.pi_dates,
        objectives,
        pi=args.pi,
        max_workers=args.max_workers,
        output_dir=config.paths.output_dir,
    )
    return 0


def _cmd_plot(config: Config, args: argparse.Namespace) -> int:
    objectives = _load_objectives(config.paths.objectives_data_path)
    run_plot_report(
        config.team,
        objectives,
        pi=args.pi,
        pi_dates=config.pi_dates,
        csv_dir=config.paths.output_dir,
        images_dir=config.paths.images_dir,
        show_labels=args.show_labels,
    )
    return 0


def _cmd_generate_docs(config: Config, args: argparse.Namespace) -> int:
    objectives = _load_objectives(config.paths.objectives_data_path)
    run_generate_docs(
        config.team,
        objectives,
        current_pi=args.pi,
        images_dir_relative=config.paths.images_dir_relative,
        output_path=config.paths.docs_output_path,
    )
    return 0


def _cmd_run_all(config: Config, args: argparse.Namespace) -> int:
    args.pi = getattr(args, "pi", None)
    args.max_workers = getattr(args, "max_workers", 10)
    args.show_labels = getattr(args, "show_labels", False)
    for handler in (_cmd_generate_config, _cmd_fetch, _cmd_plot, _cmd_generate_docs):
        code = handler(config, args)
        if code != 0:
            return code
    return 0


_SUBCOMMANDS = {
    "current-pi": _cmd_current_pi,
    "generate-config": _cmd_generate_config,
    "fetch": _cmd_fetch,
    "plot": _cmd_plot,
    "generate-docs": _cmd_generate_docs,
    "run-all": _cmd_run_all,
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dse-oss-reports")
    parser.add_argument("--config", default="team.toml", help="Path to team.toml")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    sub.add_parser("current-pi", help="Print the resolved current PI and exit")
    sub.add_parser(
        "generate-config", help="Scrape GitHub issues into reports/_objectives_data.json"
    )

    fetch_parser = sub.add_parser("fetch", help="Fetch authored commits and resolved items")
    fetch_parser.add_argument("--pi", help="PI to fetch (defaults to current)")
    fetch_parser.add_argument("--max-workers", type=int, default=10)

    plot_parser = sub.add_parser("plot", help="Render per-PI PNGs from the fetched CSVs")
    plot_parser.add_argument("--pi", help="PI to plot (defaults to current)")
    plot_parser.add_argument("--show-labels", action="store_true")

    gd_parser = sub.add_parser("generate-docs", help="Render docs/objectives.md")
    gd_parser.add_argument("--pi", help="Treat this PI as 'current' (defaults to latest)")

    all_parser = sub.add_parser("run-all", help="Run all four pipeline stages in order")
    all_parser.add_argument("--pi", help="PI to operate on (defaults to current)")
    all_parser.add_argument("--max-workers", type=int, default=10)
    all_parser.add_argument("--show-labels", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return int(e.code) if e.code is not None else 2

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(message)s",
    )

    config = load_config(Path(args.config))
    return _SUBCOMMANDS[args.subcommand](config, args)
