from pathlib import Path

from engine.data_pipeline import prepare_datafile


def _write_dataset(path: Path) -> None:
    path.write_text("0 1\n1 2\n", encoding="utf-8")


def test_prepare_datafile_resolves_project_relative_paths(tmp_path: Path) -> None:
    project_root = tmp_path / "Example.p10k"
    data_root = project_root / "data"
    data_root.mkdir(parents=True)
    data_file = data_root / "sample.dat"
    _write_dataset(data_file)

    plot_cfg = {
        "project_root": str(project_root.resolve()),
        "project_data_root": str(data_root.resolve()),
        "data_source": {
            "path": "sample.dat",
            "project_root": str(project_root.resolve()),
            "project_data_root": str(data_root.resolve()),
        },
    }

    result = prepare_datafile(plot_cfg, str(tmp_path))

    assert Path(result["path"]).resolve() == data_file.resolve()
    assert result["rows_before"] == 2
    assert result["rows_after"] == 2


def test_prepare_datafile_handles_prefixed_data_paths(tmp_path: Path) -> None:
    project_root = tmp_path / "Example.p10k"
    data_root = project_root / "data"
    data_root.mkdir(parents=True)
    data_file = data_root / "sample.dat"
    _write_dataset(data_file)

    plot_cfg = {
        "project_root": str(project_root.resolve()),
        "project_data_root": str(data_root.resolve()),
        "data_source": {
            "path": "data/sample.dat",
            "project_root": str(project_root.resolve()),
            "project_data_root": str(data_root.resolve()),
        },
    }

    result = prepare_datafile(plot_cfg, str(tmp_path))

    assert Path(result["path"]).resolve() == data_file.resolve()
