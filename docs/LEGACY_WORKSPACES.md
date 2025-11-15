# Migrating Legacy Plotinator Workspaces

Plotinator 10k v1.2.0 introduces project-domain models that organise every
workspace into a dedicated `.p10k` directory. Earlier releases relied on a
single `config.json` file living alongside the raw datasets. This guide shows
how to convert that flat layout into the portable project structure adopted by
the GUI, CLI, and reporting pipeline.

```text
Legacy Folder/              Modern Project/
├── config.json      ──▶    ├── project.json
├── dataset_a.dat          ├── fits.json
├── dataset_b.dat          ├── settings.json
└── images/                ├── data/
                           ├── plots/
                           └── exports/
```

Each generated `.p10k` folder mirrors the runtime structure documented in the
[root README](../README.md#understanding-p10k-projects).

## Schema Changes

The new schema mirrors the data classes inside `plotinator.project.models` and
`config.schema`:

| Legacy (`config.json`) | Modern (`.p10k`) |
| ---------------------- | ---------------- |
| Single JSON document combining metadata, job settings, and fits. | Separate `project.json`, `settings.json`, and `fits.json` files. |
| Dataset paths interpreted relative to the location of `config.json`. | Dataset paths resolved relative to `<project>/data`. |
| Original data files stored in-place. | Data files are copied into `<project>/data`, preserving relative references. |
| No explicit schema metadata field. | `project.json` records `schema_version`, labels, and descriptions for the GUI header. |

During migration each dataset retains a relative path so that the fits refer to
the copied files inside the project folder. Absolute references are converted
to filenames to avoid leaking machine-specific paths.

## Migration Behaviour

1. Detecting a loose `config.json` triggers the helpers in
   `plotinator.project.migration`.
2. The conversion runs in a sandbox under `%TEMP%/Untitled.p10k` (Windows) or
   `/tmp/Plotinator-<timestamp>.p10k` (Linux/macOS) unless you choose a specific
   destination.
3. Data files referenced by the legacy configuration are copied into the
   project's `data/` directory, preserving relative folder hierarchies whenever
   possible.
4. New `project.json`, `fits.json`, and `settings.json` files are generated from
   the legacy payload. Migrated datasets are normalised to relative paths within
   `data/`.
5. The original `config.json` remains untouched for rollback. The migration
   pipeline only writes to the target `.p10k` directory.
6. Once satisfied, move or rename the `.p10k` folder and run the CLI/GUI against
   it directly.

### Manual Migration Checklist

| Step | Action | CLI / GUI cue |
| ---- | ------ | ------------- |
| 1 | Back up the legacy workspace. | Copy the entire directory to a safe location. |
| 2 | Open the legacy folder in the GUI or run `plotinator-cli path/to/config.json`. | A toast/log entry confirms temporary project creation before execution continues. |
| 3 | Inspect the generated `.p10k` folder. | Ensure `data/` contains all datasets and JSON files open cleanly in an editor. |
| 4 | Use **Save Config** from the GUI toolbar or manually move the generated `.p10k` folder. | Writes the project to your chosen destination. |
| 5 | Update automation scripts to point at `<project>.p10k`. | CLI accepts either the project root or an individual JSON file inside it. |

After migration you can open the `.p10k` directory directly in the application
to continue working with the preserved fits and settings.

