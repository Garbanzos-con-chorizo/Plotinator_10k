# Migrating Legacy Plotinator Workspaces

Plotinator versions prior to the project-domain models stored all workspace
information inside a single `config.json` that lived next to the raw data
files. The modern format replaces this flat layout with a dedicated `.p10k`
folder that contains:

* `project.json` – metadata (schema version, label, description).
* `fits.json` – the list of fits and datasets, separated from the metadata.
* `settings.json` – execution defaults (export targets, worker count).
* `data/` – a local copy of every dataset referenced by the project.
* `plots/` and `exports/` – reserved directories for generated artefacts.

## Schema Changes

The new schema mirrors the data classes inside `plotinator.project.models` and
`config.schema`:

| Legacy (`config.json`) | Modern (`.p10k`) |
| ---------------------- | ---------------- |
| Single JSON document combining metadata, job settings, and fits. | Separate `project.json`, `settings.json`, and `fits.json` files. |
| Dataset paths interpreted relative to the location of `config.json`. | Dataset paths resolved relative to `<project>/data`. |
| Original data files stored in-place. | Data files are copied into `<project>/data`, preserving relative references. |

During migration each dataset retains a relative path so that the fits refer to
the copied files inside the project folder. Absolute references are converted
to filenames to avoid leaking machine-specific paths.

## Migration Behaviour

* Detecting a loose `config.json` triggers the migration helpers defined in
  `plotinator.project.migration`.
* The legacy configuration is converted into a temporary
  `%TEMP%/Untitled.p10k` project unless another target is specified.
* Data files referenced by the legacy configuration are copied into the
  project's `data/` directory, reusing the original relative layout when it is
  safe to do so.
* The original `config.json` is left untouched. The migration operates on a
  copy and writes the new project files to the `.p10k` folder only.

After migrating you can open the generated `.p10k` directory directly in the
application to continue working with the preserved fits and settings.

