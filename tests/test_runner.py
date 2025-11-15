from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pytest

from config import JobSettings
from engine import runner
from plotinator.project import ProjectPaths


def _install_pipeline_stubs(
    monkeypatch: pytest.MonkeyPatch,
    output_dir: Path,
    *,
    export_pdf_exception: Exception | None = None,
) -> None:
    """Replace external tooling with deterministic fakes for the run pipeline."""

    def fake_generate_gnuplot_code(
        plot_cfg: dict,
        out_plot: Optional[str] = None,
        out_residuals: Optional[str] = None,
    ) -> str:
        target = out_plot or out_residuals or "plot"
        return f"# gnuplot script for {target}"

    def fake_run_gnuplot_script(_: str, workdir: str) -> str:
        work_path = Path(workdir)
        work_path.mkdir(parents=True, exist_ok=True)
        (work_path / "plot.png").write_bytes(b"PNG")
        (work_path / "residuals.png").write_bytes(b"PNG")
        log_text = (
            "final sum of squares of residuals : 4.2\n"
            "variance of residuals (reduced chisquare) = WSSR/ndf   : 2.1\n"
            "rms of residuals      (FIT_STDFIT) = sqrt(WSSR/ndf)    : 1.45\n"
            "degrees of freedom    (FIT_NDF)                        : 2\n"
            "PYFIT a 1 0.1\n"
            "PYFIT b 2 0.2\n"
        )
        (work_path / "log.txt").write_text(log_text, encoding="utf-8")
        return log_text

    def fake_parse_fit_output(_: str) -> dict[str, dict[str, float]]:
        return {
            "a": {"value": 1.0, "error": 0.1},
            "b": {"value": 2.0, "error": 0.2},
        }

    def fake_compute_metrics(*_: object) -> dict[str, float]:
        return {"r2": 0.99, "rmse": 0.5}

    def fake_write_markdown(
        results_path: str,
        *,
        output_folder: str | Path | None = None,
        filename: str = "report.md",
    ) -> Path:
        target_dir = Path(output_folder) if output_folder else output_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        md_path = target_dir / filename
        md_path.write_text(f"results: {results_path}", encoding="utf-8")
        return md_path

    def fake_export_pdf(markdown_path: str, *_, **__) -> Path:
        if export_pdf_exception is not None:
            raise export_pdf_exception
        pdf_path = Path(markdown_path).with_suffix(".pdf")
        pdf_path.write_bytes(b"%PDF-1.4\n")
        return pdf_path

    monkeypatch.setattr(runner, "generate_gnuplot_code", fake_generate_gnuplot_code)
    monkeypatch.setattr(runner, "run_gnuplot_script", fake_run_gnuplot_script)
    monkeypatch.setattr(runner, "parse_fit_output", fake_parse_fit_output)
    monkeypatch.setattr(runner, "compute_residual_metrics", fake_compute_metrics)
    monkeypatch.setattr(runner, "write_markdown_report", fake_write_markdown)
    monkeypatch.setattr(runner, "export_pdf", fake_export_pdf)


def test_run_job_produces_artifacts(
    minimal_config: dict,
    sample_paths,
    config_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_job should write results and reports into the provided output directory."""

    events: list[dict] = []
    _install_pipeline_stubs(monkeypatch, sample_paths.output_dir)

    result = runner.run_job(
        minimal_config,
        config_path=str(config_path),
        settings=JobSettings(max_workers=1),
        output_dir=sample_paths.output_dir,
        on_event=events.append,
    )

    output_dir = Path(result["output_dir"])
    assert output_dir == sample_paths.output_dir
    assert (output_dir / "fit_results.json").exists()
    assert result["errors"] == []

    with open(result["results_path"], "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload["results"]
    params = payload["results"][0]["parameters"]
    assert params["a"]["value"] == pytest.approx(1.0)
    assert params["a"]["error"] == pytest.approx(0.1)
    assert params["b"]["value"] == pytest.approx(2.0)
    assert params["b"]["error"] == pytest.approx(0.2)
    assert payload["errors"] == []

    first_result = result["results"][0]
    assert Path(first_result["datafile"]) == (sample_paths.config_dir / "sample.dat")
    metrics = first_result["metrics"]
    assert metrics["r2"] == pytest.approx(0.99)
    assert metrics["rmse"] == pytest.approx(0.5)
    assert metrics["rms"] == pytest.approx(1.45)
    assert metrics["chi_squared"] == pytest.approx(4.2)
    assert metrics["reduced_chi_squared"] == pytest.approx(2.1)

    markdown_path = Path(result["markdown_path"])
    assert markdown_path.exists()
    pdf_path = Path(result["pdf_path"])
    assert pdf_path.exists()

    event_types = {event["type"] for event in events}
    assert {"job-start", "plot-start", "report-exported", "job-complete"}.issubset(event_types)
    assert any(event["type"] == "plot-complete" for event in events)

    plot_complete_events = [event for event in events if event["type"] == "plot-complete"]
    assert plot_complete_events
    preview = plot_complete_events[0].get("preview") or {}
    plot_path = preview.get("output_plot")
    if plot_path:
        assert Path(plot_path).exists()
    residual_path = preview.get("residuals_plot")
    if residual_path:
        assert Path(residual_path).exists()
    assert preview.get("metrics", {}).get("chi_squared") == pytest.approx(4.2)
    assert preview.get("parameters", {}).get("a", {}).get("error") == pytest.approx(0.1)
    cleanup_dir = preview.get("cleanup_dir")
    if cleanup_dir:
        assert Path(cleanup_dir).exists()


def test_run_job_with_project_paths(
    minimal_config: dict,
    sample_paths,
    config_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Providing project paths should redirect outputs into project folders."""

    events: list[dict] = []
    project_root = tmp_path / "project"
    project_paths = ProjectPaths.from_root(project_root)

    _install_pipeline_stubs(monkeypatch, project_paths.plots_dir)

    result = runner.run_job(
        minimal_config,
        config_path=str(config_path),
        settings=JobSettings(max_workers=1),
        on_event=events.append,
        project_paths=project_paths,
    )

    output_dir = Path(result["output_dir"])
    assert output_dir.is_dir()
    assert output_dir.parent == project_paths.plots_dir.resolve()
    assert Path(result["results_path"]).is_relative_to(output_dir)

    assert result["markdown_path"] is not None
    assert result["pdf_path"] is not None
    markdown_path = Path(result["markdown_path"])
    pdf_path = Path(result["pdf_path"])
    expected_exports_dir = (project_paths.exports_dir / output_dir.name).resolve()
    assert markdown_path.parent == expected_exports_dir
    assert pdf_path.parent == expected_exports_dir
    assert markdown_path.exists()
    assert pdf_path.exists()

    plot_events = [event for event in events if event.get("type") == "plot-complete"]
    assert plot_events
    for event in plot_events:
        preview = event.get("preview") or {}
        cleanup_dir = preview.get("cleanup_dir")
        if cleanup_dir:
            cleanup_path = Path(cleanup_dir)
            assert cleanup_path.is_relative_to(output_dir)

def test_run_job_handles_pdf_export_error(
    minimal_config: dict,
    sample_paths,
    config_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PDF export failures should be reported but not abort the job."""

    events: list[dict] = []
    _install_pipeline_stubs(
        monkeypatch,
        sample_paths.output_dir,
        export_pdf_exception=RuntimeError("pdf unavailable"),
    )

    result = runner.run_job(
        minimal_config,
        config_path=str(config_path),
        settings=JobSettings(max_workers=1),
        output_dir=sample_paths.output_dir,
        on_event=events.append,
    )

    assert result["pdf_path"] is None
    assert Path(result["markdown_path"]).exists()
    assert result["errors"] == []

    pdf_errors = [event for event in events if event["type"] == "report-error"]
    assert pdf_errors and pdf_errors[0]["stage"] == "pdf"
    assert any(event["type"] == "job-complete" for event in events)
    assert any(event["type"] == "plot-complete" for event in events)


def test_run_job_records_plot_failures(
    minimal_config: dict,
    sample_paths,
    config_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plot failures should be captured in the persisted results and events."""

    events: list[dict] = []
    _install_pipeline_stubs(monkeypatch, sample_paths.output_dir)

    good_plot = {
        "title": "Successful Plot",
        "formula": "m*x + c",
        "data_source": {
            "path": minimal_config["fits"][0]["data_source"]["path"],
            "columns": {"x": 1, "y": 2},
        },
    }

    bad_plot = {
        "title": "Explosive Plot",
        "formula": "m*x + c",
        "data_source": {
            "path": minimal_config["fits"][0]["data_source"]["path"],
            "columns": {"x": 1, "y": 2},
        },
    }

    config = {"fits": [good_plot, bad_plot]}

    def fake_process_plot(plot_cfg: dict, _base_output: object, dispatcher=None, **__: object) -> dict:
        if plot_cfg["title"] == "Explosive Plot":
            raise RuntimeError("kaboom")
        if dispatcher is not None:
            dispatcher.emit("plot-start", title=plot_cfg.get("title"))
            dispatcher.emit("plot-complete", title=plot_cfg.get("title"))
        return {
            "title": plot_cfg["title"],
            "parameters": {},
            "metrics": {},
            "datafile": str(sample_paths.config_dir / "sample.dat"),
        }

    monkeypatch.setattr(runner, "process_plot", fake_process_plot)

    result = runner.run_job(
        config,
        config_path=str(config_path),
        settings=JobSettings(max_workers=1),
        output_dir=sample_paths.output_dir,
        on_event=events.append,
    )

    assert len(result["results"]) == 1
    assert result["results"][0]["title"] == "Successful Plot"
    assert len(result["errors"]) == 1
    assert result["errors"][0]["title"] == "Explosive Plot"
    assert "kaboom" in result["errors"][0]["error"]

    with open(result["results_path"], "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    assert len(payload["results"]) == 1
    assert len(payload["errors"]) == 1

    event_types = [event["type"] for event in events]
    assert "plot-error" in event_types
    assert "plot-complete" in event_types
