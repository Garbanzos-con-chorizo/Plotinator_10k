# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2024-05-28
### Added
- Initial packaged release of Plotinator 10k with modular engine, configuration schema, and GUI integration.
- New `pyproject.toml` with console entry points for the CLI runner, GUI, and report generator.
- Version metadata exposed via `plotinator.__version__`.
- Developer tooling recommendations, including Ruff configuration and optional development extras.

### Changed
- Refreshed README with up-to-date architecture, install, and usage guidance for the packaged release.
- GUI application now exposes a `main()` function for console script entry points.

### Fixed
- Consolidated packaging metadata to ensure `engine`, `config`, and `plotinator` modules ship together.
