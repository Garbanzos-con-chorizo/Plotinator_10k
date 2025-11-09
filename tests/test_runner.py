from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pytest

from config import JobSettings
from engine import runner


def _install_pipeline_stubs(
    monkeypatch: pytest.MonkeyPatch,
    output_dir: Path,
    *,
    export_pdf_exception: Exception | None = None,
) -> None:
    """Replace external tooling with deterministic fakes for the run pipeline."""

    def fake_generate_gnuplot_code(plot_cfg: dict, out_plot: Optional[str] = None, out_residuals: Optional[str] = None) -> str:
        target = out_plot or out_residuals or "plot"
        return f"# gnuplot script for {target}"

    def fake_run_gnuplot_script(_: str, workdir: str) -> str:
        work_path = Path(workdir)
        work_path.mkdir(parents=True, exist_ok=True)
        (work_path / "log.txt").write_text("gnuplot log", encoding="utf-8")
        return "FIT: a = 1\nFIT: b = 2\n"

    def fake_parse_fit_output(_: str) -> dict[str, float]:
        return {"a": 1.0, "b": 2.0}

    def fake_compute_metrics(*_: object) -> dict[str, float]:
        return {"r2": 0.99}

    def fake_write_markdown(results_path: str) -> Path:
        md_path = output_dir / "report.md"
        md_path.write_text(f"results: {results_path}", encoding="utf-8")
        return md_path

    def fake_export_pdf(markdown_path: str) -> Path:
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

    with open(result["results_path"], "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload["results"]
    assert payload["results"][0]["parameters"] == {"a": 1.0, "b": 2.0}

    first_result = result["results"][0]
    assert Path(first_result["datafile"]) == (sample_paths.config_dir / "sample.dat")
    assert first_result["metrics"] == {"r2": 0.99}

    markdown_path = Path(result["markdown_path"])
    assert markdown_path.exists()
    pdf_path = Path(result["pdf_path"])
    assert pdf_path.exists()

    event_types = {event["type"] for event in events}
    assert {"job-start", "plot-start", "report-exported", "job-complete"}.issubset(event_types)
    assert any(event["type"] == "plot-complete" for event in events)


def test_run_job_handles_pdf_export_error(
    minimal_config: dict,
    sample_paths,
    config_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PDF export failures should be reported but not abort the job."""

    events: list[dict] = []
    _install_pipeline_stubs(monkeypatch, sample_paths.output_dir, export_pdf_exception=RuntimeError("pdf unavailable"))

    result = runner.run_job(
        minimal_config,
        config_path=str(config_path),
        settings=JobSettings(max_workers=1),
        output_dir=sample_paths.output_dir,
        on_event=events.append,
    )

    assert result["pdf_path"] is None
    assert Path(result["markdown_path"]).exists()

    pdf_errors = [event for event in events if event["type"] == "report-error"]
    assert pdf_errors and pdf_errors[0]["stage"] == "pdf"
    assert any(event["type"] == "job-complete" for event in events)
    assert any(event["type"] == "plot-complete" for event in events)
