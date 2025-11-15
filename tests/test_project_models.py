from __future__ import annotations

import json
from pathlib import Path

from config.schema import PlotinatorConfig
from plotinator.project import PlotinatorProject, ProjectMetadata, ProjectPaths


def _make_config(base_dir: Path) -> PlotinatorConfig:
    config_payload = {
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
    return PlotinatorConfig.from_mapping(config_payload, base_path=base_dir)


def test_project_save_and_load_round_trip(tmp_path: Path) -> None:
    project_root = tmp_path / "example.p10k"
    data_dir = project_root / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "sample.dat").write_text("1 2\n", encoding="utf-8")

    metadata = ProjectMetadata(schema_version=2, label="Example")
    config = _make_config(data_dir)
    paths = ProjectPaths.from_root(project_root)
    project = PlotinatorProject(paths=paths, metadata=metadata, config=config)

    project.save()

    assert paths.metadata.exists()
    assert paths.fits.exists()
    assert paths.settings.exists()
    assert paths.data_dir.is_dir()
    assert paths.plots_dir.is_dir()
    assert paths.exports_dir.is_dir()

    saved_fits = json.loads(paths.fits.read_text(encoding="utf-8"))
    assert saved_fits[0]["datasets"][0]["data_source"]["path"] == "sample.dat"
    saved_settings = json.loads(paths.settings.read_text(encoding="utf-8"))
    assert saved_settings == {
        "max_workers": 2,
        "output_dir": str(paths.exports_dir.resolve()),
    }

    loaded = PlotinatorProject.load(project_root)
    assert loaded.metadata == metadata
    dataset = loaded.config.fits[0].datasets[0]
    assert dataset.data_source.path == (data_dir / "sample.dat").resolve()
    assert dataset.data_source.original_path == "sample.dat"
    assert loaded.to_config().base_path == loaded.paths.data_dir

    updated_payload = {
        "settings": {"output_dir": "../plots"},
        "fits": [
            {
                "title": "Updated Fit",
                "formula": "a * x + b",
                "residuals": False,
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
    new_config = PlotinatorConfig.from_mapping(updated_payload, base_path=data_dir)
    loaded.update_from_config(new_config)
    assert loaded.config.fits[0].title == "Updated Fit"
