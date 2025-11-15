"""Data models for Plotinator project folders."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from config.schema import PlotinatorConfig


@dataclass(slots=True)
class ProjectMetadata:
    """Metadata associated with a Plotinator project."""

    schema_version: int = 1
    label: str | None = None
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"schema_version": int(self.schema_version)}
        if self.label is not None:
            payload["label"] = self.label
        if self.description is not None:
            payload["description"] = self.description
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "ProjectMetadata":
        if not value:
            return cls()
        schema_version_raw = value.get("schema_version", 1)
        try:
            schema_version = int(schema_version_raw)
        except (TypeError, ValueError):
            schema_version = 1
        label = value.get("label")
        if label is not None:
            label = str(label)
        description = value.get("description")
        if description is not None:
            description = str(description)
        return cls(schema_version=schema_version, label=label, description=description)


@dataclass(slots=True)
class ProjectPaths:
    """Collection of canonical paths within a project directory."""

    root: Path
    metadata: Path
    fits: Path
    settings: Path
    data_dir: Path
    plots_dir: Path
    exports_dir: Path

    @classmethod
    def from_root(cls, root: Path) -> "ProjectPaths":
        root_path = Path(root)
        return cls(
            root=root_path,
            metadata=root_path / "project.json",
            fits=root_path / "fits.json",
            settings=root_path / "settings.json",
            data_dir=root_path / "data",
            plots_dir=root_path / "plots",
            exports_dir=root_path / "exports",
        )


@dataclass(slots=True)
class PlotinatorProject:
    """Representation of a Plotinator project folder."""

    paths: ProjectPaths
    metadata: ProjectMetadata = field(default_factory=ProjectMetadata)
    config: PlotinatorConfig = field(default_factory=PlotinatorConfig)

    def __post_init__(self) -> None:
        self._synchronise_config_base_path()

    def _synchronise_config_base_path(self) -> None:
        if self.config.base_path != self.paths.data_dir:
            self.config.base_path = self.paths.data_dir

    def to_config(self) -> PlotinatorConfig:
        """Return a PlotinatorConfig linked to the project's data directory."""

        return replace(self.config, base_path=self.paths.data_dir)

    def update_from_config(self, config: PlotinatorConfig) -> None:
        """Update the project using a new PlotinatorConfig instance."""

        self.config = replace(config, base_path=self.paths.data_dir)
        self._synchronise_config_base_path()

    def save(self) -> None:
        """Persist the project metadata, fits, and settings to disk."""

        self.paths.root.mkdir(parents=True, exist_ok=True)
        for directory in (self.paths.data_dir, self.paths.plots_dir, self.paths.exports_dir):
            directory.mkdir(parents=True, exist_ok=True)

        self._write_json(self.paths.metadata, self.metadata.to_dict())

        config_for_serialisation = self.to_config()
        config_payload = config_for_serialisation.to_dict()
        fits_payload = config_payload.get("fits", [])
        settings_payload = config_payload.get("settings", {})

        self._write_json(self.paths.fits, fits_payload)
        self._write_json(self.paths.settings, settings_payload)

    @classmethod
    def load(cls, root: Path) -> "PlotinatorProject":
        """Load a Plotinator project from the given directory."""

        paths = ProjectPaths.from_root(root)
        metadata_payload = cls._read_json(paths.metadata, default={})
        fits_payload = cls._read_json(paths.fits, default=[])
        settings_payload = cls._read_json(paths.settings, default={})

        config_payload: dict[str, Any] = {"fits": fits_payload, "settings": settings_payload}
        config = PlotinatorConfig.from_mapping(config_payload, base_path=paths.data_dir)
        metadata = ProjectMetadata.from_dict(metadata_payload)
        return cls(paths=paths, metadata=metadata, config=config)

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")

    @staticmethod
    def _read_json(path: Path, *, default: Any) -> Any:
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as handle:
            try:
                return json.load(handle)
            except json.JSONDecodeError as exc:  # pragma: no cover - invalid project data
                raise ValueError(f"Invalid JSON content in {path}: {exc}") from exc


__all__ = ["ProjectMetadata", "ProjectPaths", "PlotinatorProject"]
