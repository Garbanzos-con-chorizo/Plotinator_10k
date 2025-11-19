# Project Samples

This folder keeps ready-to-run `.p10k` workspaces under the main Plotinator checkout. Each project already contains its own `data/` folder so dataset paths resolve cleanly during validation.

## TroubleshootingDemo.p10k

- Purpose: quick repro for "data file not found" errors when paths are misaligned.
- Data: `troubleshoot_sample.dat` (three-column sample with inline error values) inside the project's `data/` folder.
- Usage: point the CLI or GUI at `projects/TroubleshootingDemo.p10k` or any file within it (for example `settings.json`). Dataset references intentionally omit the `data/` prefix so they resolve against the project's data root without double-path issues.

Copy additional datasets into the `data/` folder when experimenting; the engine will pick them up as long as references stay within the project root.
