"""Utilities for managing dataset files within Plotinator projects."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .models import PlotinatorProject


class DataImportError(RuntimeError):
    """Base exception for project data import failures."""


class DataFileExistsError(DataImportError):
    """Raised when attempting to import a file that already exists."""

    def __init__(self, destination: Path) -> None:
        super().__init__(f"Data file already exists: {destination.name}")
        self.destination = destination


def import_data_file(
    project: PlotinatorProject,
    source_path: Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Import ``source_path`` into ``project``'s ``data`` directory.

    Parameters
    ----------
    project:
        The project receiving the dataset.
    source_path:
        The path to the source file to import.
    overwrite:
        When ``True`` an existing file with the same name will be replaced.

    Returns
    -------
    Path
        The resolved destination path inside the project's ``data`` directory.

    Raises
    ------
    FileNotFoundError
        If ``source_path`` does not exist.
    IsADirectoryError
        If ``source_path`` is a directory.
    DataFileExistsError
        When the destination already exists and ``overwrite`` is ``False``.
    """

    source = Path(source_path)
    try:
        source_resolved = source.resolve(strict=True)
    except FileNotFoundError:  # pragma: no cover - bubbled to caller
        raise FileNotFoundError(f"Source data file not found: {source}") from None

    if not source_resolved.is_file():
        raise IsADirectoryError(f"Source data file must be a file: {source}")

    data_dir = project.paths.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    try:
        data_root = data_dir.resolve()
    except FileNotFoundError:
        data_root = data_dir

    try:
        source_inside_project = source_resolved.is_relative_to(data_root)
    except AttributeError:  # pragma: no cover - Python < 3.9 compatibility
        source_inside_project = str(source_resolved).startswith(str(data_root))

    destination = data_dir / source_resolved.name
    try:
        destination_resolved = destination.resolve(strict=True)
    except FileNotFoundError:
        destination_resolved = destination

    if destination.exists():
        try:
            same_file = os.path.samefile(source_resolved, destination_resolved)
        except OSError:
            same_file = destination_resolved == source_resolved
        if same_file and source_inside_project:
            return destination_resolved
        if not overwrite:
            raise DataFileExistsError(destination)
        if destination.is_dir():
            raise IsADirectoryError(f"Destination is a directory: {destination}")
        destination.unlink()

    try:
        os.link(source_resolved, destination)
    except OSError:
        shutil.copy2(source_resolved, destination)

    return destination.resolve()


__all__ = ["import_data_file", "DataFileExistsError", "DataImportError"]

