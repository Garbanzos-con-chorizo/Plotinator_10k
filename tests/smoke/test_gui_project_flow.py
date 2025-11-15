"""Smoke coverage for the GUI-oriented project workflow used in Plotinator."""

from __future__ import annotations

from pathlib import Path

from config import PlotinatorConfig
from plotinator.project import PlotinatorProject, ProjectManager


def test_gui_project_flow(tmp_path: Path) -> None:
    """Simulate the GUI operations of creating, editing, and saving a project."""

    manager = ProjectManager()
    project_root = tmp_path / "flow.p10k"
    project = manager.new_project(project_root)

    imported_data = project.paths.data_dir / "series.dat"
    imported_data.write_text("0 0\n1 1\n2 4\n", encoding="utf-8")

    initial_config = PlotinatorConfig.from_mapping(
        {
            "settings": {"output_dir": "../exports", "max_workers": 1},
            "fits": [
                {
                    "title": "Initial Fit",
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
                            "label": "Series",
                            "data_source": {
                                "path": "series.dat",
                                "columns": {"x": 1, "y": 2},
                            },
                        }
                    ],
                }
            ],
        },
        base_path=project.paths.data_dir,
    )
    project.update_from_config(initial_config)

    edited_config = PlotinatorConfig.from_mapping(
        {
            "settings": {"output_dir": "../exports", "max_workers": 2},
            "fits": [
                {
                    "title": "Refined Fit",
                    "formula": "a*x + b",
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
                            "label": "Series",
                            "data_source": {
                                "path": "series.dat",
                                "columns": {"x": 1, "y": 2},
                            },
                            "style": {"line_color": "#FF0000"},
                        }
                    ],
                }
            ],
        },
        base_path=project.paths.data_dir,
    )
    project.update_from_config(edited_config)

    manager.save_project()

    reopened = PlotinatorProject.load(project_root)
    fit = reopened.config.fits[0]
    dataset = fit.datasets[0]
    assert fit.title == "Refined Fit"
    assert fit.fit_formula == "a*x + b"
    assert fit.residuals is False
    assert reopened.config.settings.max_workers == 2
    assert dataset.data_source.path == imported_data.resolve()
    assert dataset.style.line_color == "#FF0000"
