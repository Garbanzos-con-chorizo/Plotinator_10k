"""Validation helpers for Plotinator project layouts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import PlotinatorProject, ProjectPaths


@dataclass(slots=True)
class ValidationIssue:
    """Describe a specific validation problem detected within a project."""

    code: str
    message: str
    path: Path | None = None
    subject: str | None = None
    hint: str | None = None
    details: dict[str, Any] | None = None


@dataclass(slots=True)
class ValidationResult:
    """Aggregate outcome produced by the project validation routine."""

    paths: ProjectPaths
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Return ``True`` when no validation issues were detected."""

        return not self.issues

    def add_issue(
        self,
        *,
        code: str,
        message: str,
        path: Path | None = None,
        subject: str | None = None,
        hint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Append a new issue to the result set."""

        self.issues.append(
            ValidationIssue(
                code=code,
                message=message,
                path=path,
                subject=subject,
                hint=hint,
                details=details,
            )
        )


class ProjectValidationError(RuntimeError):
    """Raised when validation fails for a Plotinator project."""

    def __init__(self, result: ValidationResult):
        self.result = result
        summary = result.issues[0].message if result.issues else "Project validation failed"
        super().__init__(summary)


def validate_project(
    project: PlotinatorProject,
    *,
    check_structure: bool = True,
) -> ValidationResult:
    """Validate a project instance and return a rich diagnostic report."""

    result = ValidationResult(paths=project.paths)

    if check_structure:
        _check_structure(project.paths, result)

    _check_datasets(project, result)

    return result


def _check_structure(paths: ProjectPaths, result: ValidationResult) -> None:
    """Ensure the project folder contains the expected layout."""

    structure_expectations = {
        "root": (paths.root, Path.is_dir, "Project root folder is missing"),
        "metadata": (paths.metadata, Path.is_file, "Missing project metadata file"),
        "fits": (paths.fits, Path.is_file, "Missing fits configuration file"),
        "settings": (paths.settings, Path.is_file, "Missing project settings file"),
        "data": (paths.data_dir, Path.is_dir, "Missing data directory"),
        "plots": (paths.plots_dir, Path.is_dir, "Missing plots directory"),
        "exports": (paths.exports_dir, Path.is_dir, "Missing exports directory"),
    }

    for subject, (path, predicate, message) in structure_expectations.items():
        try:
            valid = predicate(path)
        except OSError:
            valid = False
        if not valid:
            result.add_issue(
                code="missing-path",
                message=f"{message}: {path}",
                path=path,
                subject=subject,
                hint="Recreate the missing file or directory and retry.",
            )


def _check_datasets(project: PlotinatorProject, result: ValidationResult) -> None:
    """Verify that all datasets referenced by the project remain available."""

    for fit_index, fit in enumerate(project.config.fits, start=1):
        for dataset_index, dataset in enumerate(fit.datasets, start=1):
            data_path = dataset.data_source.path
            exists = data_path.exists()
            is_file = data_path.is_file() if exists else False
            if exists and is_file:
                continue

            subject = f"fits[{fit_index - 1}].datasets[{dataset_index - 1}]"
            message = (
                f"Dataset '{dataset.label}' in fit '{fit.title}' references "
                f"missing data file: {dataset.data_source.original_path or data_path}"
            )
            hint = "Restore the referenced dataset or update the dataset path."
            details: dict[str, Any] = {
                "fit": fit.title,
                "dataset": dataset.label,
                "dataset_index": dataset_index - 1,
                "fit_index": fit_index - 1,
                "requested_path": str(dataset.data_source.original_path or data_path),
                "resolved_path": str(data_path),
            }
            result.add_issue(
                code="dangling-dataset",
                message=message,
                path=data_path,
                subject=subject,
                hint=hint,
                details=details,
            )


__all__ = [
    "ValidationIssue",
    "ValidationResult",
    "ProjectValidationError",
    "validate_project",
]

