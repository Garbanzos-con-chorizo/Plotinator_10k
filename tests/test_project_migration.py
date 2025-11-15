from __future__ import annotations

import json
from pathlib import Path

import pytest

from plotinator.project import (
    PlotinatorProject,
    find_legacy_config,
    migrate_config_file,
    synthesise_temporary_project,
)


@pytest.fixture()
def legacy_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "legacy"
    data_dir = workspace / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "sample.dat").write_text("1 2\n", encoding="utf-8")

    config_payload = {
        "settings": {"max_workers": 3},
        "fits": [
            {
                "title": "Legacy Fit",
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
                        "label": "Dataset",
                        "data_source": {
                            "path": "data/sample.dat",
                            "columns": {"x": 1, "y": 2},
                        },
                    }
                ],
            }
        ],
    }

    config_path = workspace / "config.json"
    config_path.write_text(json.dumps(config_payload), encoding="utf-8")
    return workspace


def test_find_legacy_config_from_directory(legacy_workspace: Path) -> None:
    config_path = find_legacy_config(legacy_workspace)
    assert config_path == legacy_workspace / "config.json"

    # Add a modern project marker to ensure the helper ignores it.
    (legacy_workspace / "project.json").write_text("{}", encoding="utf-8")
    assert find_legacy_config(legacy_workspace) is None


def test_migrate_config_file_creates_project_structure(legacy_workspace: Path, tmp_path: Path) -> None:
    target = tmp_path / "Migrated.p10k"
    project = migrate_config_file(legacy_workspace / "config.json", target)

    assert project.paths.root == target
    assert project.paths.metadata.exists()
    assert project.paths.fits.exists()
    assert project.paths.settings.exists()

    saved_fits = json.loads(project.paths.fits.read_text(encoding="utf-8"))
    dataset_payload = saved_fits[0]["datasets"][0]
    assert dataset_payload["data_source"]["path"] == "sample.dat"

    copied_data = project.paths.data_dir / "sample.dat"
    assert copied_data.exists()

    reloaded = PlotinatorProject.load(target)
    dataset = reloaded.config.fits[0].datasets[0]
    assert dataset.data_source.path == copied_data.resolve()
    assert dataset.data_source.original_path == "sample.dat"

    # Ensure the original config is untouched.
    with (legacy_workspace / "config.json").open("r", encoding="utf-8") as handle:
        original_payload = json.load(handle)
    assert original_payload["settings"]["max_workers"] == 3


def test_synthesise_temporary_project(monkeypatch: pytest.MonkeyPatch, legacy_workspace: Path, tmp_path: Path) -> None:
    temp_root = tmp_path / "temp"
    temp_root.mkdir()

    monkeypatch.setattr("plotinator.project.migration._default_temp_project_root", lambda: temp_root / "Untitled.p10k")

    project = synthesise_temporary_project(legacy_workspace)
    assert project is not None
    assert project.paths.root == temp_root / "Untitled.p10k"
    assert project.paths.metadata.exists()

