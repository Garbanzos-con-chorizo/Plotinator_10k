"""Markdown report generation utilities."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

__all__ = [
    "load_results",
    "build_markdown_document",
    "write_markdown_report",
]


def load_results(results_path: str | Path) -> dict[str, Any]:
    """Load the JSON results file produced by the batch runner."""
    results_file = Path(results_path)
    with results_file.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _format_parameters(parameters: dict[str, Any]) -> Iterable[str]:
    if not parameters:
        yield "_No parameters extracted._"
        return

    yield "**Parameters:**"
    yield "| Name | Value | Error |"
    yield "|------|-------:|------:|"
    for name, values in parameters.items():
        yield f"| {name} | {values['value']:.6g} | {values['error']:.6g} |"


def _format_metrics(metrics: dict[str, Any] | None) -> Iterable[str]:
    if not metrics:
        return

    yield (
        "\n**Residual Metrics:**  \n"
        f"Mean = {metrics['mean']:.4g} Std = {metrics['std']:.4g} RMSE = {metrics['rmse']:.4g}\n"
    )


def _format_data_source(data_source: dict[str, Any] | None) -> Iterable[str]:
    if not data_source:
        return

    yield "\n**Data Source:**"
    source_path = data_source.get("path", "")
    if source_path:
        yield f"- Path: `{source_path}`"

    columns = data_source.get("columns") or {}
    if columns:
        base_cols: list[str] = []
        if columns.get("x"):
            base_cols.append(f"x → col {columns['x']}")
        if columns.get("y"):
            base_cols.append(f"y → col {columns['y']}")
        if base_cols:
            yield f"- Columns: {', '.join(base_cols)}"
        if columns.get("error"):
            yield f"- Error column: col {columns['error']}"
        if columns.get("weight"):
            yield f"- Weight column: col {columns['weight']}"

    before = data_source.get("rows_before")
    after = data_source.get("rows_after")
    if before is not None and after is not None:
        yield f"- Rows: {after} / {before} used after preprocessing"

    preprocessing = data_source.get("preprocessing") or []
    if preprocessing:
        yield "- Preprocessing steps:"
        for step in preprocessing:
            if step.get("type") == "filter":
                info = step.get("retained_rows")
                suffix = f" → {info} rows" if info is not None else ""
                yield f"  - Filter `{step['expression']}`{suffix}"
            else:
                yield f"  - Transform `{step['target']}` := `{step['expression']}`"


def _format_images(item: dict[str, Any], output_folder: Path) -> Iterable[str]:
    output_plot = item.get("output_plot")
    if output_plot:
        plot_path = Path(output_plot).resolve()
        rel_plot = Path(os_path_relative(plot_path, output_folder))
        yield f"![Plot]({rel_plot.as_posix()})"

    residuals_path = item.get("residuals_plot")
    if residuals_path:
        rel_res = Path(os_path_relative(Path(residuals_path).resolve(), output_folder))
        yield f"![Residuals]({rel_res.as_posix()})"


def os_path_relative(path: Path, start: Path) -> str:
    """Return a POSIX-style relative path."""
    try:
        rel = path.relative_to(start)
        return rel.as_posix()
    except ValueError:
        return Path(os.path.relpath(str(path), str(start))).as_posix()


def build_markdown_document(results: dict[str, Any], output_folder: str | Path) -> str:
    """Construct the Markdown document as a string."""
    out_dir = Path(output_folder).resolve()
    md_lines: list[str] = []

    timestamp = results.get("timestamp", "")
    md_lines.extend(["# Plotinator Batch Report", f"**Date:** {timestamp}", "\n---\n"])

    for item in results.get("results", []):
        title = item.get("title", "Untitled plot")
        formula = item.get("formula", "")
        md_lines.append(f"## {title}")
        md_lines.append(f"**Formula:** `{formula}`  ")

        md_lines.extend(_format_parameters(item.get("parameters", {})))
        md_lines.extend(_format_metrics(item.get("metrics")))
        md_lines.extend(_format_data_source(item.get("data_source")))

        confidence = item.get("confidence_notes")
        if confidence:
            md_lines.append(f"\n> {confidence}")

        md_lines.extend(_format_images(item, out_dir))
        md_lines.append("\n---\n")

    return "\n".join(md_lines)


def write_markdown_report(
    results_path: str | Path,
    *,
    output_folder: str | Path | None = None,
    filename: str = "report.md",
) -> Path:
    """Generate a Markdown report file from a results JSON path."""
    results_file = Path(results_path)
    output_dir = Path(output_folder) if output_folder else results_file.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    results = load_results(results_file)
    markdown_text = build_markdown_document(results, output_dir)

    markdown_path = output_dir / filename
    markdown_path.write_text(markdown_text, encoding="utf-8")
    return markdown_path
