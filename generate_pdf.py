from __future__ import annotations

import os
from pathlib import Path

from reports.markdown_builder import write_markdown_report
from reports.pdf_exporter import export_pdf


def generate_markdown_report(results_path: str, output_folder: str) -> str:
    """Convert ``fit_results.json`` into a Markdown report."""
    markdown_path = write_markdown_report(
        Path(results_path),
        output_folder=Path(output_folder),
    )
    return str(markdown_path)


def convert_to_pdf(md_path: str) -> str:
    pdf_path = export_pdf(md_path)
    return str(pdf_path)


def main():
    base_folder = os.path.join("outputs", sorted(os.listdir("outputs"))[-1])
    json_path = os.path.join(base_folder, "fit_results.json")

    print(f"[RUN] Generating report from {json_path}...")
    md_path = generate_markdown_report(json_path, base_folder)
    print(f"[DONE] Markdown created: {md_path}")

    
    #print(f"[DEBUG]: Checking markdown path: {md_path}")
    #if not os.path.isfile(md_path):
    #   raise FileNotFoundError(f"Markdown file not found: {md_path}")

    pdf_path = convert_to_pdf(md_path)
    print(f"[SUCCESS] PDF exported: {pdf_path}")


if __name__ == "__main__":
    main()
