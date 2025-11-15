from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config.schema import JobSettings
from engine.runner import run_batch, run_job
from plotinator.project import PlotinatorProject


@dataclass(slots=True)
class _JobRequest:
    """Container describing how the engine should be invoked."""

    config_path: str
    config_payload: dict[str, Any] | None = None
    settings: JobSettings | None = None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plotinator-cli",
        description=(
            "Execute Plotinator batch fits using a configuration file or a .p10k project "
            "directory."
        ),
    )
    parser.add_argument(
        "source",
        nargs="?",
        help=(
            "Path to config.json or a .p10k project directory. Defaults to ./config.json "
            "when omitted."
        ),
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        metavar="PATH",
        help=(
            "Write plots, residuals, and reports to PATH instead of the project settings or "
            "timestamped defaults."
        ),
    )
    return parser


def _resolve_job_request(target: str | None) -> _JobRequest:
    """Resolve CLI target into a configuration payload for the engine."""

    if not target:
        return _JobRequest(config_path=str(Path("config.json").resolve()))

    raw_path = Path(target).expanduser()
    path = raw_path.resolve()
    if path.is_dir():
        project_marker = path / "project.json"
        if project_marker.is_file():
            return _job_request_from_project(path)
        config_candidate = path / "config.json"
        if config_candidate.is_file():
            return _JobRequest(config_path=str(config_candidate))
    elif path.is_file():
        if path.name == "project.json" and path.parent.is_dir():
            return _job_request_from_project(path.parent)
        if path.suffix == ".p10k":
            return _job_request_from_project(path)
        return _JobRequest(config_path=str(path))

    if raw_path.suffix == ".p10k" or path.suffix == ".p10k":
        if path.exists():
            return _job_request_from_project(path)
        raise FileNotFoundError(f"Project directory not found: {target}")

    if raw_path.name == "project.json" and path.parent.is_dir():
        return _job_request_from_project(path.parent)

    return _JobRequest(config_path=str(path))


def _job_request_from_project(root: Path) -> _JobRequest:
    project_root = Path(root)
    if not project_root.exists():
        raise FileNotFoundError(f"Project directory not found: {project_root}")
    project = PlotinatorProject.load(project_root)
    config = project.to_config()
    payload = config.to_dict()
    virtual_config_path = project.paths.data_dir / "config.json"
    return _JobRequest(
        config_path=str(virtual_config_path),
        config_payload=payload,
        settings=config.settings,
    )


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        job_request = _resolve_job_request(args.source)
    except FileNotFoundError as exc:
        parser.error(str(exc))
        return 2

    output_dir = args.output_dir
    if output_dir:
        output_dir = os.fspath(Path(output_dir).expanduser().resolve())

    try:
        if job_request.config_payload is not None:
            run_job(
                job_request.config_payload,
                config_path=job_request.config_path,
                settings=job_request.settings,
                output_dir=output_dir,
            )
        else:
            run_batch(
                job_request.config_path,
                output_dir=output_dir,
            )
    except Exception as exc:  # noqa: BLE001 - convert to CLI status code
        print(f"[X] {exc}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
