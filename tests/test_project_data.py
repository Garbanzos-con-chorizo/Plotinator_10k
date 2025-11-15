from pathlib import Path

import pytest

from plotinator.project import PlotinatorProject, ProjectPaths
from plotinator.project.data import DataFileExistsError, import_data_file


def _make_project(tmp_path: Path) -> PlotinatorProject:
    root = tmp_path / "example.p10k"
    paths = ProjectPaths.from_root(root)
    project = PlotinatorProject(paths=paths)
    project.save()
    return project


def test_import_data_file_copies_into_data_dir(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source = tmp_path / "sample.dat"
    source.write_text("1 2\n", encoding="utf-8")

    destination = import_data_file(project, source)

    assert destination.parent == project.paths.data_dir
    assert destination.name == source.name
    assert destination.read_text(encoding="utf-8") == "1 2\n"


def test_import_data_file_detects_duplicates(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source = tmp_path / "duplicate.dat"
    source.write_text("first\n", encoding="utf-8")

    import_data_file(project, source)

    with pytest.raises(DataFileExistsError):
        import_data_file(project, source)


def test_import_data_file_can_overwrite(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source = tmp_path / "overwrite.dat"
    source.write_text("initial\n", encoding="utf-8")

    import_data_file(project, source)
    source.write_text("updated\n", encoding="utf-8")

    destination = import_data_file(project, source, overwrite=True)

    assert destination.read_text(encoding="utf-8") == "updated\n"

