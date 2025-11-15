from pathlib import Path

from engine.config import normalize_plots


def test_normalize_plots_detects_project_context(tmp_path: Path) -> None:
    project_root = tmp_path / "Example.p10k"
    data_root = project_root / "data"
    data_root.mkdir(parents=True)
    (project_root / "project.json").write_text("{}", encoding="utf-8")

    data_file = data_root / "sample.dat"
    data_file.write_text("0 0\n1 1\n", encoding="utf-8")

    cfg = {
        "fits": [
            {
                "title": "Example",
                "formula": "a*x",
                "data_source": {
                    "path": "sample.dat",
                    "columns": {"x": 1, "y": 2},
                },
            }
        ]
    }

    plots = normalize_plots(cfg, str(project_root / "fits.json"))

    assert plots
    plot = plots[0]
    assert plot["project_root"] == str(project_root.resolve())
    assert plot["project_data_root"] == str(data_root.resolve())
    dataset = plot["datasets"][0]
    assert dataset["datafile"] == str(data_file.resolve())
    assert dataset["data_source"]["project_data_root"] == str(data_root.resolve())
