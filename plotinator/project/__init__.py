"""Project model helpers for Plotinator workspaces."""

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
    "LEGACY_CONFIG_FILENAME",
    "TEMP_PROJECT_FOLDER",
    "find_legacy_config",
    "migrate_config_file",
    "synthesise_temporary_project",
]
