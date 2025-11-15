from __future__ import annotations

from pathlib import Path

import pytest

import plot_manager
from config.schema import PlotinatorConfig
from plotinator.project import PlotinatorProject, ProjectMetadata, ProjectPaths


def _create_project(root: Path) -> PlotinatorProject:
    data_dir = root / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "sample.dat").write_text("1 2\n", encoding="utf-8")

    config_payload = {
        "settings": {"output_dir": "../exports"},
        "fits": [
            {
                "title": "Example",
                "formula": "a * x + b",
                "datasets": [
                    {
                        "label": "Dataset",
                        "data_source": {
                            "path": "sample.dat",
                            "columns": {"x": 1, "y": 2},
                        },
                    }
                ],
            }
        ],
    }
    config = PlotinatorConfig.from_mapping(config_payload, base_path=data_dir)
    project = PlotinatorProject(
        paths=ProjectPaths.from_root(root),
        metadata=ProjectMetadata(label="Example"),
        config=config,
    )
    project.save()
    return project


def test_resolve_job_request_defaults_to_config_json():
    request = plot_manager._resolve_job_request(None)
    assert request.config_path.endswith("config.json")
    assert request.config_payload is None
    assert request.settings is None


def test_resolve_job_request_from_project(tmp_path: Path):
    project_root = tmp_path / "demo.p10k"
    project = _create_project(project_root)

    request = plot_manager._resolve_job_request(str(project_root))
    assert request.config_payload is not None
    assert Path(request.config_path).parent == project.paths.data_dir
    assert request.settings is not None


def test_main_invokes_run_job_for_projects(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project_root = tmp_path / "demo.p10k"
    project = _create_project(project_root)

    captured: dict[str, object] = {}

    def fake_run_job(config_payload, *, config_path, settings, output_dir):  # noqa: ANN001
        captured.update(
            {
                "payload": config_payload,
                "config_path": config_path,
                "settings": settings,
                "output_dir": output_dir,
            }
        )
        return {"output_dir": output_dir}

    monkeypatch.setattr(plot_manager, "run_job", fake_run_job)

    custom_output = tmp_path / "exports"
    exit_code = plot_manager.main([str(project_root), "--output-dir", str(custom_output)])

    assert exit_code == 0
    assert captured["payload"] is not None
    assert Path(captured["config_path"]).parent == project.paths.data_dir
    assert captured["settings"] == project.config.settings
    assert captured["output_dir"] == str(custom_output.resolve())


def test_main_invokes_run_batch_for_configs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")

    captured: dict[str, object] = {}

    def fake_run_batch(path, *, output_dir=None):  # noqa: ANN001
        captured.update({"path": path, "output_dir": output_dir})
        return {"output_dir": output_dir}

    monkeypatch.setattr(plot_manager, "run_batch", fake_run_batch)

    exit_code = plot_manager.main([str(config_path), "-o", "exports"])

    assert exit_code == 0
    assert captured["path"] == str(config_path.resolve())
    assert captured["output_dir"] == str(Path("exports").resolve())


def test_resolve_job_request_missing_target() -> None:
    with pytest.raises(FileNotFoundError):
        plot_manager._resolve_job_request("missing-project.p10k")
