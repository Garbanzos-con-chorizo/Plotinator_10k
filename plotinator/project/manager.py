"""High-level orchestration helpers for Plotinator project folders."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Callable, Iterable, Sequence

from config.schema import ConfigError
from .data import import_data_file as _import_data_file
from .migration import synthesise_temporary_project
from .models import PlotinatorProject, ProjectMetadata, ProjectPaths
from .validation import ProjectValidationError, ValidationResult, validate_project


FilesystemCallback = Callable[[ProjectPaths], None]


class ProjectManager:
    """Coordinate project lifecycle operations and filesystem notifications."""

    def __init__(
        self,
        *,
        filesystem_callbacks: Iterable[FilesystemCallback] | None = None,
    ) -> None:
        self._project: PlotinatorProject | None = None
        self._filesystem_callbacks: list[FilesystemCallback] = (
            list(filesystem_callbacks) if filesystem_callbacks is not None else []
        )
        self._clean_snapshot: str | None = None
        self._dirty: bool = False
        self._available_data_files: list[Path] = []

    # ------------------------------------------------------------------
    # Public API

    def register_filesystem_callback(self, callback: FilesystemCallback) -> None:
        """Register a callback invoked when project files are materialised."""

        self._filesystem_callbacks.append(callback)

    # Lifecycle ---------------------------------------------------------

    def new_project(
        self,
        location: Path | str,
        *,
        metadata: ProjectMetadata | None = None,
    ) -> PlotinatorProject:
        """Create a new project at ``location`` and persist an empty layout."""

        root = Path(location)
        paths = ProjectPaths.from_root(root)
        project = PlotinatorProject(
            paths=paths,
            metadata=metadata if metadata is not None else ProjectMetadata(),
        )
        project.save()
        self._set_project(project)
        self._notify_filesystem()
        return project

    def open_project(self, location: Path | str) -> PlotinatorProject:
        """Open an existing project or migrate a legacy workspace."""

        path = Path(location)
        project = self._load_project(path)
        self._enforce_valid(project, check_structure=True)
        self._set_project(project)
        self._notify_filesystem()
        return project

    def save_project(self) -> PlotinatorProject:
        """Persist the current project state to disk."""

        project = self.current_project()
        self._normalise_project_datasets(project)
        project.save()
        self._enforce_valid(project, check_structure=True)
        self._update_snapshot()
        self._notify_filesystem()
        return project

    def save_project_as(self, location: Path | str) -> PlotinatorProject:
        """Save the current project to a new root directory."""

        current = self.current_project()
        target_root = Path(location)
        new_paths = ProjectPaths.from_root(target_root)
        config_copy = current.to_config()
        metadata_copy = ProjectMetadata.from_dict(current.metadata.to_dict())
        new_project = PlotinatorProject(paths=new_paths, metadata=metadata_copy, config=config_copy)

        self._materialise_project_clone(current, new_project)
        self._enforce_valid(new_project, check_structure=False)
        new_project.save()
        self._enforce_valid(new_project, check_structure=True)
        self._copy_directory(current.paths.plots_dir, new_project.paths.plots_dir)
        self._copy_directory(current.paths.exports_dir, new_project.paths.exports_dir)

        self._set_project(new_project)
        self._notify_filesystem()
        return new_project

    def current_project(self) -> PlotinatorProject:
        """Return the active project instance."""

        project = self._project
        if project is None:
            raise RuntimeError("No project is currently loaded")
        return project

    # Convenience -------------------------------------------------------

    @property
    def dirty(self) -> bool:
        """Return whether the current project has unsaved changes."""

        project = self._project
        if project is None:
            return False
        snapshot = self._serialise_state(project)
        self._dirty = snapshot != self._clean_snapshot
        return self._dirty

    def data_path(self, *parts: Path | str) -> Path:
        """Resolve a path within the project's data directory."""

        return self._resolve_project_path(self.current_project().paths.data_dir, parts)

    @property
    def available_data_files(self) -> tuple[Path, ...]:
        """Return cached data files discovered within the project."""

        return tuple(self._available_data_files)

    def refresh_available_data_files(self) -> tuple[Path, ...]:
        """Rescan the project's data directory and update the cache."""

        project = self.current_project()
        self._refresh_available_data_files(project)
        return tuple(self._available_data_files)

    def import_data_file(
        self, source_path: Path | str, *, overwrite: bool = False
    ) -> Path:
        """Copy or link a data file into the project's ``data`` directory."""

        project = self.current_project()
        destination = _import_data_file(project, Path(source_path), overwrite=overwrite)
        self._refresh_available_data_files(project)
        return destination

    def exports_path(self, *parts: Path | str) -> Path:
        """Resolve a path within the project's exports directory."""

        return self._resolve_project_path(self.current_project().paths.exports_dir, parts)

    def preview_path(self, *parts: Path | str) -> Path:
        """Resolve a path used for preview artefacts (plots directory)."""

        return self._resolve_project_path(self.current_project().paths.plots_dir, parts)

    # ------------------------------------------------------------------
    # Internal helpers

    def _set_project(self, project: PlotinatorProject) -> None:
        self._project = project
        self._normalise_project_datasets(project)
        self._refresh_available_data_files(project)
        self._clean_snapshot = self._serialise_state(project)
        self._dirty = False

    def _update_snapshot(self) -> None:
        project = self._project
        if project is None:
            self._clean_snapshot = None
            self._dirty = False
            return
        self._clean_snapshot = self._serialise_state(project)
        self._dirty = False
        self._refresh_available_data_files(project)

    def _load_project(self, location: Path) -> PlotinatorProject:
        if location.is_dir():
            candidate = location / "project.json"
            if candidate.is_file():
                return self._safe_load(location)
            migrated = synthesise_temporary_project(location)
            if migrated is not None:
                self._enforce_valid(migrated, check_structure=True)
                return migrated
        elif location.is_file():
            parent = location.parent
            marker = parent / "project.json"
            if marker.is_file():
                return self._safe_load(parent)
            migrated = synthesise_temporary_project(location)
            if migrated is not None:
                self._enforce_valid(migrated, check_structure=True)
                return migrated
        raise FileNotFoundError(f"Unable to locate a project at {location}")

    def _safe_load(self, root: Path) -> PlotinatorProject:
        try:
            return PlotinatorProject.load(root)
        except (ConfigError, ValueError) as exc:
            paths = ProjectPaths.from_root(root)
            result = ValidationResult(paths=paths)
            message = str(exc)
            code = "invalid-config" if isinstance(exc, ConfigError) else "invalid-json"
            if isinstance(exc, ConfigError) and "Data file not found for" in message:
                code = "dangling-dataset"
            target_path = paths.fits
            for candidate in (paths.metadata, paths.fits, paths.settings):
                if candidate.name in message:
                    target_path = candidate
                    break
            result.add_issue(
                code=code,
                message=message,
                path=target_path,
                subject="config",
                hint="Review the configuration files and correct the reported problem.",
            )
            raise ProjectValidationError(result) from exc

    def _materialise_project_clone(
        self,
        source: PlotinatorProject,
        target: PlotinatorProject,
    ) -> None:
        root = target.paths.root
        if root.exists() and any(root.iterdir()):
            raise FileExistsError(f"Target project directory already exists: {root}")
        root.mkdir(parents=True, exist_ok=True)
        self._rebase_datasets(source, target)

    def _rebase_datasets(self, source: PlotinatorProject, target: PlotinatorProject) -> None:
        source_data_root = source.paths.data_dir
        destination_root = target.paths.data_dir
        copied: set[Path] = set()

        for fit in target.config.fits:
            for dataset in fit.datasets:
                original_path = dataset.data_source.path
                relative_path = self._determine_relative_dataset_path(
                    dataset.data_source.original_path,
                    original_path,
                    source_data_root,
                )
                destination = destination_root / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)

                source_resolved = original_path.resolve()
                destination_resolved = destination.resolve()
                if destination_resolved not in copied:
                    if source_resolved != destination_resolved:
                        shutil.copy2(source_resolved, destination)
                    else:
                        destination.touch(exist_ok=True)
                    copied.add(destination_resolved)

                dataset.data_source.path = destination_resolved
                dataset.data_source.original_path = relative_path.as_posix()

    @staticmethod
    def _determine_relative_dataset_path(
        original: str | None,
        current_path: Path,
        data_root: Path,
    ) -> Path:
        if original:
            original_path = Path(original)
            if not original_path.is_absolute():
                return original_path
        try:
            return current_path.resolve().relative_to(data_root.resolve())
        except ValueError:
            return Path(current_path.name)

    @staticmethod
    def _copy_directory(source: Path, destination: Path) -> None:
        if not source.exists():
            return
        destination.mkdir(parents=True, exist_ok=True)
        for item in source.iterdir():
            target_path = destination / item.name
            if item.is_dir():
                ProjectManager._copy_directory(item, target_path)
            else:
                shutil.copy2(item, target_path)

    def _refresh_available_data_files(self, project: PlotinatorProject) -> None:
        try:
            data_root = project.paths.data_dir.resolve()
        except FileNotFoundError:
            data_root = project.paths.data_dir
        if not data_root.exists():
            self._available_data_files = []
            return

        files: list[Path] = []
        try:
            for candidate in data_root.rglob("*"):
                try:
                    if not candidate.is_file():
                        continue
                except OSError:
                    continue
                try:
                    files.append(candidate.resolve())
                except FileNotFoundError:
                    continue
        except OSError:
            self._available_data_files = []
            return

        files.sort()
        self._available_data_files = files

    def _normalise_project_datasets(self, project: PlotinatorProject) -> None:
        try:
            data_root = project.paths.data_dir.resolve()
        except FileNotFoundError:
            data_root = project.paths.data_dir
        try:
            project_root = project.paths.root.resolve()
        except FileNotFoundError:
            project_root = project.paths.root

        for fit in project.config.fits:
            for dataset in fit.datasets:
                source = dataset.data_source
                candidate_path = source.path
                if not candidate_path.is_absolute():
                    candidate_path = project_root / candidate_path
                try:
                    resolved = candidate_path.resolve()
                except FileNotFoundError:
                    resolved = candidate_path
                try:
                    relative = resolved.relative_to(data_root)
                except ValueError:
                    continue

                destination = data_root / relative
                try:
                    source.path = destination.resolve()
                except FileNotFoundError:
                    source.path = destination
                source.original_path = relative.as_posix()

    def _serialise_state(self, project: PlotinatorProject) -> str:
        payload = {
            "metadata": project.metadata.to_dict(),
            "config": project.to_config().to_dict(),
        }
        return json.dumps(payload, sort_keys=True)

    def _notify_filesystem(self) -> None:
        project = self._project
        if project is None:
            return
        for callback in self._filesystem_callbacks:
            callback(project.paths)

    def _enforce_valid(self, project: PlotinatorProject, *, check_structure: bool) -> None:
        result = validate_project(project, check_structure=check_structure)
        if not result.ok:
            raise ProjectValidationError(result)

    @staticmethod
    def _resolve_project_path(base: Path, parts: Sequence[Path | str]) -> Path:
        return base.joinpath(*parts)


__all__ = ["ProjectManager", "FilesystemCallback"]

