from pathlib import Path

from plotinator.ui.workspace import WorkspaceState


def test_workspace_state_records_and_persists(tmp_path: Path) -> None:
    storage = tmp_path / "state.json"
    project_root = tmp_path / "Example.p10k"
    project_root.mkdir()
    (project_root / "project.json").write_text("{}", encoding="utf-8")

    state = WorkspaceState.load(storage)
    state.record_project(project_root)
    state.autosave_minutes = 7
    state.save()

    reloaded = WorkspaceState.load(storage)
    assert reloaded.autosave_minutes == 7
    assert reloaded.last_opened == project_root.resolve()
    assert reloaded.recent_projects[0] == project_root.resolve()


def test_workspace_state_prune_missing_entries(tmp_path: Path) -> None:
    storage = tmp_path / "state.json"
    missing_project = tmp_path / "Missing.p10k"

    state = WorkspaceState.load(storage)
    state.recent_projects = [missing_project]
    state.last_opened = missing_project
    state.save()

    reloaded = WorkspaceState.load(storage)
    reloaded.prune_missing()
    assert reloaded.recent_projects == []
    assert reloaded.last_opened is None
