"""Validation tests for configuration loading helpers."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from config import ConfigError, PlotinatorConfig, load_config, load_config_file


def test_load_config_constructs_models(
    minimal_config: dict, sample_paths, sample_data_file: Path
) -> None:
    """load_config should return fully-hydrated configuration models."""

    config = load_config(minimal_config, base_path=sample_paths.config_dir)

    assert isinstance(config, PlotinatorConfig)
    assert config.base_path == sample_paths.config_dir
    assert len(config.fits) == 1
    fit = config.fits[0]
    assert fit.title == "Synthetic Trend"
    dataset = fit.datasets[0]
    assert dataset.data_source.path == sample_data_file


def test_load_config_requires_fits(sample_paths) -> None:
    """Configs without a fits list should raise ConfigError."""

    with pytest.raises(ConfigError, match="Config missing required 'fits' list"):
        load_config({}, base_path=sample_paths.config_dir)


def test_load_config_validates_column_mappings(
    minimal_config: dict, sample_paths, sample_data_file: Path
) -> None:
    """Invalid column indices should surface a helpful error message."""

    bad_config = copy.deepcopy(minimal_config)
    bad_config["fits"][0]["data_source"]["columns"]["y"] = 5

    with pytest.raises(ConfigError) as exc_info:
        load_config(bad_config, base_path=sample_paths.config_dir)

    message = str(exc_info.value)
    assert "Error in fit #1" in message
    assert "does not have column 5" in message
    assert str(sample_data_file) in message


def test_load_config_file_reads_json(
    minimal_config: dict, sample_paths, sample_data_file: Path
) -> None:
    """load_config_file should resolve relative paths from the file location."""

    config_file = sample_paths.config_dir / "job.json"
    config_file.write_text(json.dumps(minimal_config), encoding="utf-8")

    config = load_config_file(config_file)

    assert isinstance(config, PlotinatorConfig)
    dataset = config.fits[0].datasets[0]
    assert dataset.data_source.path == sample_data_file
    assert dataset.data_source.original_path == sample_data_file.name


def test_load_config_file_requires_pyyaml(sample_paths) -> None:
    """Attempting to load YAML without PyYAML should emit a clear error."""

    yaml_path = sample_paths.config_dir / "job.yaml"
    yaml_path.write_text("fits: []\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="PyYAML is required to load YAML configuration files"):
        load_config_file(yaml_path)


def test_data_source_accepts_project_root_relative_paths(sample_paths: SimpleNamespace) -> None:
    """Relative paths anchored at the project root should resolve inside data/."""

    project_root = sample_paths.config_dir / "demo_project"
    data_dir = project_root / "data"
    data_dir.mkdir(parents=True)

    data_file = data_dir / "series.dat"
    data_file.write_text("0 0\n1 1\n", encoding="utf-8")

    config_payload = {
        "fits": [
            {
                "title": "Root-relative dataset",
                "formula": "m*x + c",
                "data_source": {
                    "path": f"data/{data_file.name}",
                    "columns": {"x": 1, "y": 2},
                },
            }
        ]
    }

    config = load_config(config_payload, base_path=data_dir)

    data_source = config.fits[0].datasets[0].data_source
    assert data_source.path == data_file
    assert data_source.original_path == f"data/{data_file.name}"
