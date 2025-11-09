from __future__ import annotations

import json
from pathlib import Path

import pytest

from reports import markdown_builder
from reports import pdf_exporter


def test_load_results_reads_json(tmp_path: Path) -> None:
    payload = {"timestamp": "2024-01-01", "results": []}
    results_path = tmp_path / "results.json"
    results_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = markdown_builder.load_results(results_path)

    assert loaded == payload


def test_build_markdown_document_renders_sections(tmp_path: Path) -> None:
    output_dir = tmp_path / "report"
    output_dir.mkdir()
    assets_dir = output_dir / "assets"
    assets_dir.mkdir()

    plot_path = assets_dir / "plot.png"
    plot_path.write_bytes(b"")
    residual_path = assets_dir / "residuals.png"
    residual_path.write_bytes(b"")

    results = {
        "timestamp": "2024-03-15T12:00:00Z",
        "results": [
            {
                "title": "Harmonic Fit",
                "formula": "A*sin(omega*x) + c",
                "parameters": {
                    "A": {"value": 1.23456, "error": 0.02},
                    "omega": {"value": 0.98765, "error": 0.01},
                },
                "metrics": {"mean": 0.1, "std": 0.02, "rmse": 0.03},
                "data_source": {
                    "path": str(assets_dir / "data.csv"),
                    "columns": {"x": 1, "y": 2, "error": 3},
                    "rows_before": 100,
                    "rows_after": 95,
                    "preprocessing": [
                        {"type": "filter", "expression": "x > 0", "retained_rows": 95},
                    ],
                },
                "confidence_notes": "Stable fit within tolerance.",
                "output_plot": str(plot_path),
                "residuals_plot": str(residual_path),
            }
        ],
    }

    markdown = markdown_builder.build_markdown_document(results, output_dir)

    assert "# Plotinator Batch Report" in markdown
    assert "Harmonic Fit" in markdown
    assert "Mean = 0.1" in markdown
    assert "Path: `" in markdown
    assert "Filter `x > 0`" in markdown
    assert "![Plot](assets/plot.png)" in markdown
    assert "![Residuals](assets/residuals.png)" in markdown


def test_write_markdown_report_creates_file(tmp_path: Path) -> None:
    results = {"timestamp": "2024-03-15T12:00:00Z", "results": []}
    results_path = tmp_path / "results.json"
    results_path.write_text(json.dumps(results), encoding="utf-8")

    markdown_path = markdown_builder.write_markdown_report(
        results_path,
        output_folder=tmp_path / "out",
        filename="summary.md",
    )

    assert markdown_path.name == "summary.md"
    assert markdown_path.parent == tmp_path / "out"
    assert markdown_path.exists()
    contents = markdown_path.read_text(encoding="utf-8")
    assert "# Plotinator Batch Report" in contents


@pytest.fixture
def fake_pandoc(monkeypatch: pytest.MonkeyPatch):
    calls: list[dict[str, object]] = []

    def ensure() -> str:
        calls.append({"ensure": True})
        return "/usr/bin/pandoc"

    def convert_file(source: str, *, to: str, format: str, outputfile: str, extra_args: list[str] | None = None):
        calls.append(
            {
                "source": source,
                "to": to,
                "format": format,
                "outputfile": outputfile,
                "extra_args": extra_args,
            }
        )
        Path(outputfile).write_text("converted", encoding="utf-8")

    monkeypatch.setattr(pdf_exporter, "ensure_pandoc_available", ensure)
    monkeypatch.setattr(pdf_exporter.pypandoc, "convert_file", convert_file)

    return calls


def test_export_pdf_uses_default_arguments(tmp_path: Path, fake_pandoc: list[dict[str, object]]) -> None:
    md_path = tmp_path / "report.md"
    md_path.write_text("Hello", encoding="utf-8")

    pdf_path = pdf_exporter.export_pdf(md_path)

    assert pdf_path == md_path.with_suffix(".pdf").resolve()
    assert pdf_path.exists()

    ensure_calls = [call for call in fake_pandoc if "ensure" in call]
    convert_calls = [call for call in fake_pandoc if "source" in call]
    assert ensure_calls
    assert convert_calls

    convert_call = convert_calls[0]
    assert convert_call["source"] == md_path.name
    assert convert_call["to"] == "pdf"
    assert convert_call["format"] == "md"
    assert convert_call["outputfile"] == "report.pdf"
    assert convert_call["extra_args"] == pdf_exporter.DEFAULT_EXTRA_ARGS["pdf"]


def test_export_pdf_respects_custom_output_path(tmp_path: Path, fake_pandoc: list[dict[str, object]]) -> None:
    md_path = tmp_path / "docs" / "report.md"
    md_path.parent.mkdir()
    md_path.write_text("Content", encoding="utf-8")

    output_path = tmp_path / "exports" / "custom-name.pdf"

    pdf_path = pdf_exporter.export_pdf(
        md_path,
        output_path=output_path,
        extra_args=["--metadata", "title=Custom"],
    )

    assert pdf_path == output_path.resolve()
    assert output_path.exists()

    convert_calls = [call for call in fake_pandoc if "source" in call]
    # Last call corresponds to this test invocation
    convert_call = convert_calls[-1]
    assert convert_call["source"] == md_path.name
    assert convert_call["outputfile"] == "report.pdf"
    assert convert_call["extra_args"] == ["--metadata", "title=Custom"]
