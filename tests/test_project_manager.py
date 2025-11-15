from __future__ import annotations

import json
from pathlib import Path

import pytest

from config.schema import PlotinatorConfig
from plotinator.project import DataFileExistsError, ProjectManager


def _write_legacy_config(root: Path) -> None:
    data_path = root / "data.csv"
    data_path.write_text("x,y\n1,2\n", encoding="utf-8")
    config_payload = {
        "fits": [
            {
                "title": "Example",
                "formula": "a*x",
                "residuals": True,
                "datasets": [
                    {
                        "label": "Primary",
                        "data_source": {
                            "path": "data.csv",
                            "columns": {"x": 1, "y": 2},
                        },
                    }
                ],
            }
        ],
        "settings": {},
    }
    (root / "config.json").write_text(json.dumps(config_payload), encoding="utf-8")


def test_new_project_creates_directory_layout(tmp_path: Path) -> None:
    events: list[Path] = []
    manager = ProjectManager(filesystem_callbacks=[lambda paths: events.append(paths.root)])

    project_root = tmp_path / "example.p10k"
    project = manager.new_project(project_root)

    assert project.paths.root == project_root
    assert project.paths.metadata.is_file()
    assert project.paths.fits.is_file()
    assert project.paths.settings.is_file()
    assert project.paths.data_dir.is_dir()
    assert project.paths.plots_dir.is_dir()
    assert project.paths.exports_dir.is_dir()
    assert events[-1] == project_root
    assert manager.dirty is False


def test_dirty_tracking_reacts_to_metadata_and_settings(tmp_path: Path) -> None:
    manager = ProjectManager()
    project = manager.new_project(tmp_path / "dirty.p10k")

    assert manager.dirty is False
    project.metadata.label = "Updated"
    assert manager.dirty is True

    manager.save_project()
    assert manager.dirty is False

    project.config.settings.max_workers = 4
    assert manager.dirty is True


def test_save_project_as_clones_structure(tmp_path: Path) -> None:
    manager = ProjectManager()
    project = manager.new_project(tmp_path / "source.p10k")
    data_file = manager.data_path("sample.csv")
    data_file.write_text("x,y\n1,2\n", encoding="utf-8")

    config_payload = {
        "fits": [
            {
                "title": "Clone",
                "formula": "a*x",
                "residuals": True,
                "datasets": [
                    {
                        "label": "Primary",
                        "data_source": {
                            "path": "sample.csv",
                            "columns": {"x": 1, "y": 2},
                        },
                    }
                ],
            }
        ],
        "settings": {},
    }

    config = PlotinatorConfig.from_mapping(config_payload, base_path=project.paths.data_dir)
    project.update_from_config(config)
    manager.save_project()

    target_root = tmp_path / "clone.p10k"
    clone = manager.save_project_as(target_root)

    clone_data_file = clone.paths.data_dir / "sample.csv"
    assert clone.paths.root == target_root
    assert clone_data_file.read_text(encoding="utf-8") == "x,y\n1,2\n"
    dataset = clone.config.fits[0].datasets[0]
    assert dataset.data_source.path == clone_data_file.resolve()
    assert dataset.data_source.original_path == "sample.csv"


def test_open_project_migrates_legacy_workspace(tmp_path: Path) -> None:
    legacy_root = tmp_path / "legacy"
    legacy_root.mkdir()
    _write_legacy_config(legacy_root)

    manager = ProjectManager()
    project = manager.open_project(legacy_root)

    assert project.metadata.label == "legacy"
    assert project.paths.metadata.is_file()
    assert manager.dirty is False


def test_import_data_file_updates_available_cache(tmp_path: Path) -> None:
    manager = ProjectManager()
    manager.new_project(tmp_path / "cache.p10k")

    assert manager.available_data_files == ()

    source = tmp_path / "data.dat"
    source.write_text("1 2\n", encoding="utf-8")

    destination = manager.import_data_file(source)

    assert destination in manager.available_data_files

    with pytest.raises(DataFileExistsError):
        manager.import_data_file(source)

    source.write_text("2 3\n", encoding="utf-8")
    updated = manager.import_data_file(source, overwrite=True)

    assert updated.read_text(encoding="utf-8") == "2 3\n"
    assert updated in manager.available_data_files


def test_save_project_normalises_absolute_dataset_paths(tmp_path: Path) -> None:
    manager = ProjectManager()
    project = manager.new_project(tmp_path / "normalise.p10k")

    source = tmp_path / "source.dat"
    source.write_text("1 2\n", encoding="utf-8")

    destination = manager.import_data_file(source)

    config_payload = {
        "fits": [
            {
                "title": "Absolute",
                "formula": "a*x",
                "residuals": False,
                "datasets": [
                    {
                        "label": "Primary",
                        "data_source": {
                            "path": destination.as_posix(),
                            "columns": {"x": 1, "y": 2},
                        },
                    }
                ],
            }
        ],
        "settings": {},
    }

    config = PlotinatorConfig.from_mapping(config_payload, base_path=project.paths.data_dir)
    project.update_from_config(config)

    manager.save_project()

    dataset = project.config.fits[0].datasets[0]
    assert dataset.data_source.original_path == destination.name
    assert dataset.data_source.path == destination.resolve()

    saved_fits = json.loads(project.paths.fits.read_text(encoding="utf-8"))
    assert saved_fits[0]["datasets"][0]["data_source"]["path"] == destination.name

