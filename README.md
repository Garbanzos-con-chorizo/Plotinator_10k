# Plotinator 10k

Plotinator 10k is an automation toolkit for producing high-quality fitting plots from large batches of experimental datasets. The long-term goal is to give laboratory teams an end-to-end workflow: describe fits declaratively, let Plotinator run gnuplot to perform curve fitting, capture numerical diagnostics, and render polished visual and PDF reports without having to drive gnuplot manually.

The repository currently contains the foundations of that workflow in three major areas:

* A **configuration-driven batch runner** (`plot_manager.py`) that reads a JSON configuration, normalises styling options, executes gnuplot fits, and records residual metrics.
* A **desktop editor** (`plotinator10000.py`) built with Tkinter + ttkbootstrap that helps non-technical users manage the configuration file, launch batch runs, and inspect logs.
* A **report generator** (`generate_pdf.py`) that converts the captured JSON results into Markdown and then into a PDF report via Pandoc.

## Vision & planned behaviour

Once complete, Plotinator 10k will provide:

1. **Configurable fitting recipes** – Every fit specifies the dataset, column mapping, fit function, styling, and whether residual analysis is required. The batch runner will resolve sensible defaults (e.g., initial parameter guesses) and guard against dangerous input (e.g., blacklisting unsafe symbols in gnuplot expressions).
2. **Robust batch execution** – The runner will spawn gnuplot for each fit (with optional parallelism), capture stdout/stderr, and persist intermediate artefacts such as plot images, residual plots, and structured JSON summaries.
3. **Interactive orchestration** – The GUI will let operators pick data folders, add/remove fits, tweak styling, kick off batch jobs, watch progress, and open the latest report with minimal friction.
4. **Automated reporting** – After each batch run, the Markdown+PDF pipeline will produce a narrative report containing plots, parameter tables, residual statistics, and provenance metadata for each dataset.
5. **Packaging support** – A future Python package (and potentially platform-specific bundles) will install the CLI + GUI, ensure gnuplot/Pandoc availability, and expose simple entry points for lab teams.

## Current status snapshot

| Component | Status | Notes |
|-----------|--------|-------|
| Configuration schema | 🟡 Draft | `config.json` stores a `fits` list. Layout, style, and dataset metadata helpers exist but still need full validation & documentation.
| Batch runner (`plot_manager.py`) | 🟡 Core logic present | Generates gnuplot scripts, computes residual metrics with NumPy, and logs output. Needs CLI wiring, error handling polish, and packaging into a callable module.
| GUI (`plotinator10000.py`) | 🟡 Usable prototype | ttkbootstrap UI loads/saves the config, provides fit editors, and can trigger batch runs (threading stub present). Further work required for long-running process management & result visualisation.
| Reporting (`generate_pdf.py`) | 🟡 Functional script | Builds Markdown from `fit_results.json` and converts to PDF via Pandoc + wkhtmltopdf. Requires integration hook from batch runner and configuration for output directories.
| Automated tests | 🔴 Missing | No unit or integration test suite yet.
| Packaging | 🔴 Pending | Dependencies tracked manually; no `pyproject.toml` or installer scripts yet.

## Repository layout

```
Plotinator_10k/
├── config.json              # Example configuration stub consumed by the GUI & runner
├── plot_manager.py          # Core batch orchestration, gnuplot code generation, residual analysis
├── plotinator10000.py       # Tk/ttkbootstrap desktop application for editing configs and launching runs
├── generate_pdf.py          # Markdown → PDF report pipeline using pypandoc
├── plotinator/              # Package directory (currently only style helpers)
│   └── config/style.py      # StyleConfig dataclass with validation & gnuplot legend helpers
├── data/                    # Placeholder for input datasets (not tracked)
└── outputs/                 # Target folder for generated plots, logs, reports
```

## Data & execution flow (current prototype)

1. **Configuration** – Users edit `config.json` either manually or via the GUI. Each fit entry describes datasets, layout, style, gnuplot formula, and optional residual analysis settings.
2. **Batch run** – The runner (currently invoked programmatically) iterates through each fit, writes a gnuplot script, executes it, saves plots + logs, and aggregates metadata/metrics into `fit_results.json`.
3. **Reporting** – `generate_pdf.py` consumes the JSON results, writes a Markdown report, and invokes Pandoc to export a PDF. The GUI’s “Open report” button will eventually surface the most recent artefact to the operator.

## Next implementation steps

* Promote the batch runner to a first-class CLI command (e.g., `python -m plotinator.runner config.json`) with options for output directories and parallel workers.
* Finish wiring the GUI buttons to actual runner invocations and progress updates, including graceful cancellation and error surfaces.
* Add schema validation for the configuration (consider `pydantic` or `jsonschema`) and document expected fields.
* Implement automated tests for gnuplot code generation, residual computations, and GUI configuration handling (headless-friendly).
* Introduce a packaging manifest (`pyproject.toml`) with console scripts for the runner and GUI, alongside reproducible environment tooling (e.g., `uv`, `pip-tools`, or `poetry`).

## Dependency checklist for packaging & installation

The following dependencies have already been used in the repository and should be captured when we formalise packaging:

### Python runtime

* Python 3.11+ (uses `typing.Annotated` style hints and modern standard-library features).

### Python packages

* `numpy` – numerical operations for residual/parameter calculations in `plot_manager.py`.
* `ttkbootstrap` – themed widgets for the Tkinter GUI.
* `pypandoc` – wrapper around Pandoc used for Markdown→PDF conversion.
* Potential future helpers to evaluate: `jsonschema`/`pydantic` (config validation), `typer`/`click` (CLI), `pytest` (testing). These are not yet imported but recommended for the roadmap.

### System requirements

* **gnuplot** – must be installed and available on `PATH`; the runner emits `.plt` scripts and executes them via `subprocess`.
* **Pandoc** – required by `pypandoc`; can be discovered through `PANDOC_PATH` or system `PATH`.
* **wkhtmltopdf** – PDF engine used by `generate_pdf.py` for Pandoc conversions.
* **Ghostscript** (optional) – improves PDF font embedding during conversion, recommended for production pipelines.

Documenting these dependencies now will make it easier to assemble installers, Docker images, or CI workflows later.

## Development tips

* When iterating on the GUI, use a virtual environment with the dependencies installed (`pip install numpy ttkbootstrap pypandoc`). The standard Tkinter module ships with CPython on most platforms.
* `gnuplot` and `wkhtmltopdf` are external tools; ensure they are on your system `PATH` before running batch jobs or PDF exports.
* The batch runner writes temporary scripts and logs to each fit’s working directory. Inspect `outputs/<timestamp>/log.txt` when diagnosing failures.
* Keep the `outputs/` directory in `.gitignore` (already the case) to avoid committing generated artefacts.

Stay tuned—once packaging is in place we will provide a single command to install Plotinator 10k and run both the GUI and automated batch workflows.
