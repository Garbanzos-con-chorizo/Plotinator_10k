"""Integration-style tests covering project persistence and migration flows."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from config import ConfigError, PlotinatorConfig
from plotinator.project import PlotinatorProject, ProjectManager, migrate_config_file


def _make_project_config(data_dir: Path) -> dict:
    return {
        "settings": {"output_dir": "../exports", "max_workers": 2},
        "fits": [
            {
                "title": "Demo Fit",
                "formula": "a * x + b",
                "residuals": True,
                "layout": {
                    "rows": 1,
                    "columns": 1,
                    "shared_x": False,
                    "shared_y": False,
                    "show_legend": True,
                },
                "datasets": [
                    {
                        "label": "Dataset A",
                        "data_source": {
                            "path": "sample.dat",
                            "columns": {"x": 1, "y": 2},
                        },
                    }
                ],
            }
        ],
    }


def test_project_round_trip_via_manager(tmp_path: Path) -> None:
    """Saving and reloading a project should preserve metadata and config."""

    manager = ProjectManager()
    project_root = tmp_path / "analysis.p10k"
    project = manager.new_project(project_root)
    project.metadata.label = "Analysis"
    project.metadata.description = "Synthetic validation"

    data_file = project.paths.data_dir / "sample.dat"
    data_file.write_text("0 0\n1 1\n", encoding="utf-8")

    config = PlotinatorConfig.from_mapping(_make_project_config(project.paths.data_dir), base_path=project.paths.data_dir)
    project.update_from_config(config)

    manager.save_project()

    assert project.paths.metadata.exists()
    assert project.paths.fits.exists()
    assert project.paths.settings.exists()

    reloaded = PlotinatorProject.load(project_root)
    assert reloaded.metadata.label == "Analysis"
    assert reloaded.metadata.description == "Synthetic validation"

    dataset = reloaded.config.fits[0].datasets[0]
    assert dataset.data_source.path == data_file.resolve()
    assert dataset.data_source.original_path == "sample.dat"
    assert reloaded.config.settings.output_dir == project.paths.exports_dir.resolve()


def test_migration_materialises_legacy_workspace(tmp_path: Path) -> None:
    """Migrating a legacy config.json copies datasets and normalises paths."""

    legacy_root = tmp_path / "legacy"
    legacy_root.mkdir()
    legacy_data = legacy_root / "sample.dat"
    legacy_data.write_text("0 0\n1 1\n2 4\n", encoding="utf-8")

    legacy_config = legacy_root / "config.json"
    legacy_payload = _make_project_config(legacy_root)
    with legacy_config.open("w", encoding="utf-8") as handle:
        json.dump(legacy_payload, handle)

    target_root = tmp_path / "Migrated.p10k"
    project = migrate_config_file(legacy_config, target_root)

    assert project.paths.root == target_root
    assert project.paths.metadata.is_file()
    assert project.paths.fits.is_file()
    assert project.paths.settings.is_file()
    assert (project.paths.data_dir / "sample.dat").is_file()

    migrated = PlotinatorProject.load(target_root)
    dataset = migrated.config.fits[0].datasets[0]
    assert dataset.data_source.path == (project.paths.data_dir / "sample.dat").resolve()
    assert dataset.data_source.original_path == "sample.dat"


def test_project_load_detects_invalid_dataset_columns(tmp_path: Path) -> None:
    """Loading a project with invalid column references should raise ConfigError."""

    project_root = tmp_path / "broken.p10k"
    data_dir = project_root / "data"
    plots_dir = project_root / "plots"
    exports_dir = project_root / "exports"
    for directory in (data_dir, plots_dir, exports_dir):
        directory.mkdir(parents=True, exist_ok=True)

    (data_dir / "sample.dat").write_text("0 0\n1 1\n", encoding="utf-8")

    metadata_path = project_root / "project.json"
    metadata_path.write_text(json.dumps({"label": "Broken"}), encoding="utf-8")

    settings_path = project_root / "settings.json"
    settings_path.write_text(json.dumps({}), encoding="utf-8")

    fits_payload = {
        "fits": [
            {
                "title": "Bad Fit",
                "formula": "a*x + b",
                "residuals": True,
                "layout": {
                    "rows": 1,
                    "columns": 1,
                    "shared_x": False,
                    "shared_y": False,
                    "show_legend": True,
                },
                "datasets": [
                    {
                        "label": "Bad Dataset",
                        "data_source": {
                            "path": "sample.dat",
                            "columns": {"x": 1, "y": 5},
                        },
                    }
                ],
            }
        ]
    }
    fits_path = project_root / "fits.json"
    fits_path.write_text(json.dumps(fits_payload["fits"]), encoding="utf-8")

    with pytest.raises(ConfigError):
        PlotinatorProject.load(project_root)
