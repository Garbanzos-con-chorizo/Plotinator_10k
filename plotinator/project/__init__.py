"""Project model helpers for Plotinator workspaces."""

from .data import DataFileExistsError, DataImportError, import_data_file
from .migration import (
    LEGACY_CONFIG_FILENAME,
    TEMP_PROJECT_FOLDER,
    find_legacy_config,
    migrate_config_file,
    synthesise_temporary_project,
)
from .manager import FilesystemCallback, ProjectManager
from .models import PlotinatorProject, ProjectMetadata, ProjectPaths
from .validation import (
    ProjectValidationError,
    ValidationIssue,
    ValidationResult,
    validate_project,
)

__all__ = [
    "PlotinatorProject",
    "ProjectMetadata",
    "ProjectPaths",
    "ProjectManager",
    "validate_project",
    "FilesystemCallback",
    "ProjectValidationError",
    "ValidationResult",
    "ValidationIssue",
    "import_data_file",
    "DataFileExistsError",
    "DataImportError",
    "LEGACY_CONFIG_FILENAME",
    "TEMP_PROJECT_FOLDER",
    "find_legacy_config",
    "migrate_config_file",
    "synthesise_temporary_project",
]
