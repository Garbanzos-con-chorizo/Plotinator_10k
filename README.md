# Plotinator 10k

Plotinator 10k is a modular automation toolkit for producing high-quality fitting plots from
large batches of experimental datasets. The stack now ships as a Python package with separate
layers for configuration, execution, user interface, and reporting so each surface can evolve
independently.

## Highlights

- **Schema-driven configuration** – The `config` package validates JSON/YAML jobs into strongly-typed
  dataclasses with helpful error messages, column mapping guards, and preprocessing metadata.
- **Modular engine** – The `engine` package prepares datasets, generates gnuplot scripts, performs
  fits, and aggregates metrics. A thin CLI wrapper keeps scripting simple while enabling programmatic
  reuse.
- **Desktop GUI** – `plotinator10000.py` provides a ttkbootstrap-powered editor that loads the schema
  models directly, helping non-technical users manage fits and launch batches without touching JSON.
- **Reporting pipeline** – `generate_pdf.py` converts engine output into Markdown and PDF artefacts via
  Pandoc, producing narrative-ready reports after each batch run.

## Installation

```bash
pip install .
```

The project targets **Python 3.10+** and expects external tools to be available on your `PATH`:

- [gnuplot](http://www.gnuplot.info/) for curve fitting and plotting.
- [Pandoc](https://pandoc.org/) and [wkhtmltopdf](https://wkhtmltopdf.org/) for PDF conversion.

Optional extras:

```bash
pip install .[yaml]   # enable YAML configuration files via PyYAML
pip install .[dev]    # install pytest + ruff for local development
```

## Quickstart

### Run a batch from the CLI

```bash
plotinator-cli path/to/config.json
```

- Reads the configuration file using the schema models.
- Normalises dataset layouts and style configuration.
- Executes gnuplot fits (with optional parallel workers) and writes results to `outputs/<timestamp>/`.

### Launch the desktop GUI

```bash
plotinator-gui
```

- Edit fits, datasets, styling, and preprocessing steps using a friendly interface.
- Save changes back to disk through the schema layer.
- Kick off batch runs directly from the GUI, watching live logs in the sidebar.

### Generate a PDF report

```bash
plotinator-report
```

- Consumes the most recent `fit_results.json` emitted by the engine.
- Builds a Markdown narrative and exports a PDF using Pandoc + wkhtmltopdf.

## Architecture Overview

```
Plotinator_10k/
├── engine/                 # Batch runner, data preparation, gnuplot orchestration
├── config/                 # Schema models, validation helpers, serialization utilities
├── plotinator/             # Package metadata and shared configuration helpers
├── plot_manager.py         # CLI entry point that wraps the engine
├── plotinator10000.py      # ttkbootstrap GUI shell using the schema + engine API
├── generate_pdf.py         # Markdown/PDF report pipeline
├── config.json             # Example configuration demonstrating multi-dataset fits
└── outputs/                # Generated artefacts (plots, residuals, reports)
```

Each layer communicates through clear interfaces:

- `config.PlotinatorConfig` models the entire job and exposes `.to_engine_payload()` for execution.
- `engine.run_batch()` accepts paths or schema objects and returns structured results for downstream
  consumers (GUI, reports, tests).
- `generate_pdf` reads the engine output JSON and focuses solely on documentation concerns.

## Development Notes

1. Create a virtual environment and install the project with development extras:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e .[dev]
   ```
2. Ensure `gnuplot`, `pandoc`, and `wkhtmltopdf` are installed locally before exercising the batch
   pipeline or PDF exporter.
3. Use `ruff` for linting and `pytest` as tests are added.

## Release Process

1. Update `CHANGELOG.md` and bump the version in `pyproject.toml` (mirrored by
   `plotinator.__version__`).
2. Run the smoke tests or demo configuration to ensure CLI, GUI, and reporting still interoperate.
3. Build the distribution:
   ```bash
   python -m build
   ```
4. Publish to your artefact repository of choice (PyPI, internal index, etc.).

## License

Plotinator 10k is distributed under the terms of the MIT License. See [LICENSE](LICENSE) for
additional details.
