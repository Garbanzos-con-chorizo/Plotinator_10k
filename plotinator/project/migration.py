"""Helpers for migrating legacy Plotinator workspaces."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterable

from config.schema import PlotinatorConfig
from .models import PlotinatorProject, ProjectMetadata, ProjectPaths

LEGACY_CONFIG_FILENAME = "config.json"
TEMP_PROJECT_FOLDER = "Untitled.p10k"

__all__ = [
    "LEGACY_CONFIG_FILENAME",
    "TEMP_PROJECT_FOLDER",
    "find_legacy_config",
    "synthesise_temporary_project",
    "migrate_config_file",
]


def find_legacy_config(location: Path) -> Path | None:
    """Return the path to a loose ``config.json`` if one is present."""

    candidate = Path(location)
    if candidate.is_file() and candidate.name == LEGACY_CONFIG_FILENAME:
        return candidate

    if candidate.is_dir():
        config_path = candidate / LEGACY_CONFIG_FILENAME
        project_marker = candidate / "project.json"
        if config_path.is_file() and not project_marker.exists():
            return config_path

    return None


def synthesise_temporary_project(location: Path, *, temp_root: Path | None = None) -> PlotinatorProject | None:
    """Create a migrated project for legacy workspaces inside a temp directory."""

    config_path = find_legacy_config(location)
    if config_path is None:
        return None

    temporary_root = Path(temp_root) if temp_root is not None else _default_temp_project_root()
    if temporary_root.exists():
        shutil.rmtree(temporary_root)

    return migrate_config_file(config_path, temporary_root)


def migrate_config_file(path: Path, target: Path) -> PlotinatorProject:
    """Convert a legacy ``config.json`` into the modern project folder layout."""

    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"Legacy configuration file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    legacy_root = config_path.parent.resolve()
    config = PlotinatorConfig.from_mapping(payload, base_path=legacy_root)

    workspace_name = legacy_root.name or config_path.stem or "Untitled"
    metadata = ProjectMetadata(label=workspace_name)

    target_root = Path(target)
    if target_root.exists():
        shutil.rmtree(target_root)

    paths = ProjectPaths.from_root(target_root)
    project = PlotinatorProject(paths=paths, metadata=metadata, config=config)

    _materialise_data_files(project, legacy_root)
    project.save()
    return project


def _default_temp_project_root() -> Path:
    return Path(tempfile.gettempdir()) / TEMP_PROJECT_FOLDER


def _materialise_data_files(project: PlotinatorProject, legacy_root: Path) -> None:
    destination = project.paths.data_dir
    destination.mkdir(parents=True, exist_ok=True)

    copied: set[Path] = set()
    for fit in project.config.fits:
        for dataset in fit.datasets:
            source_path = dataset.data_source.path.resolve()
            relative_path = _derive_relative_path(dataset.data_source.original_path, source_path, legacy_root)
            dest_path = destination / relative_path
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            dest_resolved = dest_path.resolve()
            if dest_resolved not in copied:
                if source_path != dest_resolved:
                    shutil.copy2(source_path, dest_path)
                else:
                    dest_path.touch(exist_ok=True)
                copied.add(dest_resolved)

            dataset.data_source.path = dest_resolved
            dataset.data_source.original_path = relative_path.as_posix()


def _derive_relative_path(original: str, source_path: Path, legacy_root: Path) -> Path:
    default = Path(source_path.name)

    workspace_candidate = _sanitise_parts(source_path.relative_to(legacy_root).parts) if _is_within_root(source_path, legacy_root) else None
    if workspace_candidate:
        trimmed = _trim_legacy_data_prefix(workspace_candidate)
        if trimmed:
            return Path(*trimmed)

    original_candidate = _sanitise_original(original)
    if original_candidate:
        trimmed = _trim_legacy_data_prefix(original_candidate)
        if trimmed:
            return Path(*trimmed)

    return default


def _trim_legacy_data_prefix(parts: tuple[str, ...]) -> tuple[str, ...]:
    if not parts:
        return parts
    if parts[0].lower() == "data" and len(parts) > 1:
        return parts[1:]
    return parts


def _is_within_root(source_path: Path, legacy_root: Path) -> bool:
    try:
        source_path.relative_to(legacy_root)
        return True
    except ValueError:
        return False


def _sanitise_parts(parts: Iterable[str]) -> tuple[str, ...] | None:
    cleaned: list[str] = []
    for part in parts:
        if not part or part == ".":
            continue
        if part == "..":
            return None
        cleaned.append(part)
    return tuple(cleaned)


def _sanitise_original(original: str | None) -> tuple[str, ...] | None:
    if not original:
        return None
    windows = PureWindowsPath(original)
    posix = PurePosixPath(original)
    if windows.is_absolute() or posix.is_absolute():
        return None
    candidate = windows.parts if len(windows.parts) >= len(posix.parts) else posix.parts
    return _sanitise_parts(candidate)

