"""Compatibility helpers that bridge the legacy engine with the new schema."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from config import LayoutConfig, infer_parameters as _infer_parameters, load_config

__all__ = [
    "normalize_layout",
    "infer_parameters",
    "normalize_plots",
]


def normalize_layout(raw_layout: dict | None) -> dict:
    """Normalize layout dictionaries using the schema model."""

    return LayoutConfig.from_mapping(raw_layout, context="layout").to_dict()


def infer_parameters(formula: str) -> list[str]:
    """Infer fitting parameter names from a formula."""

    return _infer_parameters(formula)


def normalize_plots(cfg: dict, config_path: str) -> list[dict[str, Any]]:
    """Normalize the list of plot definitions for the engine."""

    base_path = Path(config_path).resolve().parent
    job = load_config(cfg, base_path=base_path)
    return job.to_engine_payload()
