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
