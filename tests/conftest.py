"""Shared fixtures and pytest configuration for the Plotinator test suite."""

from __future__ import annotations

import warnings
from pathlib import Path
from types import SimpleNamespace

import pytest

_MISSING_PYTEST_COV = False


@pytest.fixture
def sample_paths(tmp_path: Path) -> SimpleNamespace:
    """Provide isolated directories for config input and job outputs."""

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    output_dir = tmp_path / "artifacts"
    return SimpleNamespace(config_dir=config_dir, output_dir=output_dir)


@pytest.fixture
def sample_data_file(sample_paths: SimpleNamespace) -> Path:
    """Create a simple two-column dataset for fitting tests."""

    data_path = sample_paths.config_dir / "sample.dat"
    data_path.write_text("0 0\n1 1\n2 4\n", encoding="utf-8")
    return data_path


@pytest.fixture
def minimal_config(sample_data_file: Path) -> dict:
    """Return a minimal Plotinator configuration referencing the sample data."""

    return {
        "fits": [
            {
                "title": "Synthetic Trend",
                "formula": "m*x + c",
                "data_source": {
                    "path": sample_data_file.name,
                    "columns": {"x": 1, "y": 2},
                },
            }
        ]
    }


@pytest.fixture
def config_path(sample_paths: SimpleNamespace) -> Path:
    """Dummy config path used to anchor relative config resolution."""

    config_path = sample_paths.config_dir / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    return config_path


def pytest_addoption(parser):  # type: ignore[no-untyped-def]
    """Register stub coverage options when pytest-cov is unavailable."""
    global _MISSING_PYTEST_COV

    try:
        import pytest_cov  # noqa: F401
    except ImportError:  # pragma: no cover - exercised only when plugin missing
        _MISSING_PYTEST_COV = True
        cov_group = parser.getgroup("cov")
        cov_group.addoption(
            "--cov",
            action="append",
            dest="cov",
            metavar="MODULE",
            default=[],
            help="Stub option added when pytest-cov is not installed.",
        )
        cov_group.addoption(
            "--cov-report",
            action="append",
            dest="cov_report",
            metavar="TYPE",
            default=[],
            help="Stub option added when pytest-cov is not installed.",
        )
    else:
        _MISSING_PYTEST_COV = False


def pytest_configure(config):  # type: ignore[no-untyped-def]
    """Emit a warning when coverage options are ignored."""
    if not _MISSING_PYTEST_COV:
        return

    if getattr(config.option, "cov", None) or getattr(config.option, "cov_report", None):
        warnings.warn(
            "pytest-cov is not installed; coverage options configured in pyproject.toml will be ignored.",
            RuntimeWarning,
            stacklevel=0,
        )
