"""Compatibility helpers that bridge the legacy engine with the new schema."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from config import LayoutConfig, load_config
from config import infer_parameters as _infer_parameters

__all__ = [
    "normalize_layout",
    "infer_parameters",
    "normalize_plots",
]


def normalize_layout(raw_layout: dict | None) -> dict:
    """Normalize layout dictionaries using the schema model."""

    return LayoutConfig.from_mapping(raw_layout, context="layout").to_dict()


def infer_parameters(formula: str) -> list[str]:
    """Infer fitting parameter names from a formula."""

    return _infer_parameters(formula)


def _coerce_path(value: Any) -> Path | None:
    if value is None or value == "":
        return None
    try:
        path = Path(str(value)).expanduser()
    except Exception:
        return None
    try:
        return path.resolve()
    except OSError:
        # ``resolve`` can fail on some platforms when intermediate directories are
        # missing; fall back to the non-resolved path in that scenario.
        return path


def _determine_project_context(
    cfg: Mapping[str, Any] | None, config_path: Path
) -> tuple[Path | None, Path]:
    base_dir = config_path.parent.resolve()
    project_root: Path | None = None
    data_root: Path | None = None

    if isinstance(cfg, Mapping):
        raw_project_root = cfg.get("project_root") or cfg.get("projectRoot")
        project_section = cfg.get("project")

        if raw_project_root is not None:
            project_root = _coerce_path(raw_project_root)

        if isinstance(project_section, Mapping):
            section_root = project_section.get("root") or project_section.get("path")
            if section_root is not None and project_root is None:
                project_root = _coerce_path(section_root)

            data_value = (
                project_section.get("data_root")
                or project_section.get("data")
                or project_section.get("data_dir")
            )
            if data_value is not None:
                data_path = _coerce_path(data_value)
                if data_path is None and project_root is not None:
                    try:
                        candidate = project_root / str(data_value)
                    except Exception:
                        candidate = None
                    else:
                        data_path = _coerce_path(candidate)
                if data_path is not None:
                    data_root = data_path

    if project_root is None:
        marker = base_dir / "project.json"
        if marker.is_file():
            project_root = base_dir

    if data_root is None and project_root is not None:
        candidate = project_root / "data"
        if candidate.exists():
            data_root = candidate.resolve()

    if data_root is None:
        data_root = base_dir

    return project_root, data_root


def normalize_plots(cfg: dict, config_path: str) -> list[dict[str, Any]]:
    """Normalize the list of plot definitions for the engine."""

    config_file = Path(config_path).resolve()
    cfg_mapping = cfg if isinstance(cfg, Mapping) else None
    project_root, data_root = _determine_project_context(cfg_mapping, config_file)
    job = load_config(cfg, base_path=data_root)
    plots = job.to_engine_payload()

    project_root_str = str(project_root) if project_root is not None else None
    data_root_str = str(data_root)
    config_dir_str = str(config_file.parent.resolve())

    for plot in plots:
        plot.setdefault("config_base_dir", config_dir_str)
        if project_root_str:
            plot.setdefault("project_root", project_root_str)
        plot.setdefault("project_data_root", data_root_str)

        datasets = plot.get("datasets") or []
        for dataset in datasets:
            dataset.setdefault("config_base_dir", config_dir_str)
            if project_root_str:
                dataset.setdefault("project_root", project_root_str)
            dataset.setdefault("project_data_root", data_root_str)

            data_source = dataset.get("data_source")
            if isinstance(data_source, Mapping):
                data_source = dict(data_source)
                data_source.setdefault("config_base_dir", config_dir_str)
                if project_root_str:
                    data_source.setdefault("project_root", project_root_str)
                data_source.setdefault("project_data_root", data_root_str)
                dataset["data_source"] = data_source

    return plots
