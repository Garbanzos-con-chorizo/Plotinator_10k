# Plotinator Open Beta v1.2.0

Plotinator Open Beta v1.2.0 is a modular automation toolkit for producing high-quality fitting plots from
large batches of experimental datasets. The stack now ships as a Python package with separate
layers for configuration, execution, user interface, and reporting so each surface can evolve
independently.

## Highlights

- **Schema-driven configuration** – The `config` package validates JSON/YAML jobs into strongly-typed
  dataclasses with helpful error messages, column mapping guards, and preprocessing metadata.
- **Modular engine** – The `engine` package prepares datasets, generates gnuplot scripts, performs
  fits, and aggregates metrics. A thin CLI wrapper keeps scripting simple while enabling programmatic
  reuse.
- **Desktop GUI** – `plotinator_gui.py` provides a ttkbootstrap-powered editor that loads the schema
  models directly, helping non-technical users manage fits and launch batches without touching JSON.
  v1.2.0 introduces a quick theme toggle, persistent batch-log filtering/export controls, and preview
  history navigation so you can compare fits without re-running jobs.
- **Reporting pipeline** – `generate_pdf.py` converts engine output into Markdown and PDF artefacts via
  Pandoc, producing narrative-ready reports after each batch run.

## Understanding `.p10k` Projects

The 1.2.0 release formalises Plotinator projects as self-contained folders ending with the `.p10k`
extension. Each project wraps metadata, fit definitions, and copied datasets so the GUI, CLI, and
reporting tools share a consistent workspace.

```text
MyExperiment.p10k/
├── project.json      # Metadata: schema version, human-friendly label, description
├── fits.json         # All fit definitions (formulae, dataset bindings, styling)
├── settings.json     # Engine + export defaults consumed by CLI/GUI/report tools
├── data/             # Normalised dataset copies used during batch execution
├── plots/            # Reserved for generated plots and residual previews
└── exports/          # Reserved for rendered reports and derived artefacts
```

| Folder/File       | Purpose                                                                 |
| ----------------- | ----------------------------------------------------------------------- |
| `project.json`    | Stores schema metadata plus optional labels/descriptions for the UI.    |
| `fits.json`       | Captures every fit, dataset assignment, and styling directive.          |
| `settings.json`   | Persists batch defaults such as worker counts and export toggles.       |
| `data/`           | Houses dataset copies so projects remain portable across machines.      |
| `plots/`          | Destination for on-demand previews captured by the GUI preview drawer.  |
| `exports/`        | Destination for generated Markdown/PDF reports and CSV summaries.       |

### Sample `settings.json`

```json
{
  "schema_version": 2,
  "batch": {
    "max_workers": 4,
    "overwrite_outputs": false
  },
  "exports": {
    "generate_pdf": true,
    "attach_preview_images": true
  }
}
```

The GUI reads and writes these JSON files directly, while the CLI resolves relative dataset paths
against `<project>/data` to guarantee reproducible runs.

### Included sample project

A ready-to-run troubleshooting project lives in `projects/TroubleshootingDemo.p10k`. Point the CLI
or GUI at that folder (or its `settings.json`) to confirm dataset resolution: its
`data/troubleshoot_sample.dat` file sits inside the project so relative paths cannot escape the
expected data root. Copy additional `.dat` files into that `data/` directory when debugging
"missing data" errors.

## Installation

```bash
pip install plotinator-open-beta
```

To work from a local checkout:

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
plotinator-cli path/to/project.p10k
plotinator-cli path/to/project.p10k --output-dir /custom/exports
```

- Accepts either a legacy `config.json` file or a modern `.p10k` project directory.
- Normalises dataset layouts and style configuration.
- Exports to the project's configured output directory unless `--output-dir` is provided, otherwise
  falls back to `outputs/<timestamp>/`.
- Executes gnuplot fits (with optional parallel workers) and writes results to the selected output
  directory.

### Launch the desktop GUI

```bash
plotinator-gui
```

- Edit fits, datasets, styling, and preprocessing steps using a friendly interface.
- Save changes back to disk through the schema layer.
- Kick off batch runs directly from the GUI, watching live logs in the sidebar.
- Use the toolbar theme toggle, log filter/export controls, and preview history buttons to surface
  new diagnostics without leaving the main window.

### Migrating legacy workspaces

1. Launch the GUI and choose **Data Folder** (or run `plotinator-cli` pointing to an old
   `config.json`).
2. When a loose legacy file is detected, Plotinator will synthesise a `.p10k` project in your
   temporary directory and display a toast describing the destination.
3. Review the generated folder, then use **Save Config** to persist it in a permanent location. The
   wizard copies datasets into `data/`, generates `project.json`, `fits.json`, and `settings.json`, and
   rewires every dataset reference to the portable paths.
4. Replace scripts or shortcuts that previously referenced `config.json` with the new project
   directory. CLI runs now target `path/to/Project.p10k/settings.json` or the root project folder.
5. Consult [docs/LEGACY_WORKSPACES.md](docs/LEGACY_WORKSPACES.md) for side-by-side schema comparisons
   and manual migration tips (useful for air-gapped deployments).

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
├── plotinator_gui.py       # ttkbootstrap GUI shell using the schema + engine API
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
3. Build the distribution artefacts:
   ```bash
   python -m build
   ```
   - Windows packaging requires the external binaries (`gnuplot`, `pandoc`, `wkhtmltopdf`) to be installed locally. Export their
     paths via `GNUPLOT_PATH`, `PANDOC_PATH`, and `WKHTMLTOPDF_PATH` before freezing the app.
   - Run `pyinstaller packaging/plotinator.spec --clean --noconfirm` to produce the CLI, GUI, and report executables under
     `dist/plotinator-bundle`. Smoke-test `plotinator-cli.exe`, `plotinator-gui.exe`, and `plotinator-report.exe` in place to
     ensure they launch and detect the bundled `external/` dependencies.
  - Regenerate `packaging/windows/plotinator-files.wxs` with WiX 3.11 `heat.exe`, then run `packaging/windows/build-installer.bat`
     to produce `dist/Plotinator_10k.msi`. The [Installer Guide](docs/INSTALLER.md) mirrors the exact commands. Install the MSI on
     a clean VM to verify the GUI can run a sample batch and export a PDF report.
4. Publish to your artefact repository of choice (PyPI, internal index, etc.).

### Open beta build retrieval & validation

Tagged builds trigger the **Windows release packaging** workflow, which publishes two artefacts
under the run's *Artifacts* panel:

- `plotinator-bundle-<tag>` – zipped PyInstaller output from `dist/plotinator-bundle/`.
- `plotinator-msi-<tag>` – the WiX-generated installer (`dist/Plotinator_10k.msi`).

To download them, either use the GitHub web UI or fetch via the CLI:

```bash
gh run download --repo <org>/Plotinator_10k --name plotinator-bundle-<tag>
gh run download --repo <org>/Plotinator_10k --name plotinator-msi-<tag>
```

Validate the artefacts before handing them to external testers:

1. Verify file integrity on Windows by computing hashes and comparing against the workflow summary.
   ```powershell
    Get-FileHash .\plotinator-bundle-<tag>.zip -Algorithm SHA256
    Get-FileHash .\Plotinator_10k.msi -Algorithm SHA256
   ```
2. Provision a clean Windows VM (no cached dependencies) and extract the bundle.
   - Launch `plotinator-cli.exe`, `plotinator-gui.exe`, and `plotinator-report.exe` to ensure the
     embedded Python environment loads.
   - Run the sample configuration shipped in `config.json` to confirm plotting, reporting, and
     dependency discovery still work end-to-end.
3. Install the MSI on the same VM and repeat the smoke test to confirm Start Menu shortcuts and file
   associations behave as expected.

For deeper packaging diagnostics, see the [Installer Guide](docs/INSTALLER.md).

## Packaging Troubleshooting

Common packaging failures and how to recover are documented in the [Installer Guide](docs/INSTALLER.md#packaging-troubleshooting).

## License

Plotinator Open Beta v1.2.0 is distributed under the terms of the MIT License. See [LICENSE](LICENSE) for
additional details.
