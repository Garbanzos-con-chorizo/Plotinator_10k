from __future__ import annotations

import copy
import os
import re
from typing import Any

from plotinator.config.style import StyleConfig

__all__ = [
    "BLACKLIST",
    "normalize_layout",
    "infer_parameters",
    "normalize_plots",
]

BLACKLIST = {"x", "sin", "cos", "tan", "exp", "log", "sqrt", "np", "math"}


def _coerce_positive_int(value: Any, default: int) -> int:
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        return default
    return ivalue if ivalue > 0 else default


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def normalize_layout(raw_layout: dict | None) -> dict:
    if not isinstance(raw_layout, dict):
        raw_layout = {}

    rows = _coerce_positive_int(raw_layout.get("rows"), 1)
    columns = _coerce_positive_int(raw_layout.get("columns"), 1)
    shared_x = _coerce_bool(raw_layout.get("shared_x"), False)
    shared_y = _coerce_bool(raw_layout.get("shared_y"), False)
    show_legend = _coerce_bool(raw_layout.get("show_legend"), True)

    legend_position = raw_layout.get("legend_position")
    if isinstance(legend_position, str):
        legend_position = legend_position.strip()
    else:
        legend_position = ""

    layout = {
        "rows": rows,
        "columns": columns,
        "shared_x": shared_x,
        "shared_y": shared_y,
        "show_legend": show_legend,
    }

    if legend_position:
        layout["legend_position"] = legend_position

    return layout


def _ensure_columns_dict(columns: dict | None) -> dict:
    base = {"x": 1, "y": 2, "error": None, "weight": None}
    if not isinstance(columns, dict):
        return base
    result = base.copy()
    for key in ("x", "y", "error", "weight"):
        val = columns.get(key)
        if val is None or val == "":
            result[key] = None if key in {"error", "weight"} else base[key]
            continue
        try:
            ival = int(val)
        except (TypeError, ValueError):
            raise ValueError(f"Column '{key}' must be an integer (1-based index)")
        if ival <= 0:
            raise ValueError(f"Column '{key}' must be positive (1-based index)")
        result[key] = ival
    return result


def _validate_columns_exist(path: str, column_map: dict):
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = re.split(r"[,\s]+", line.strip())
                if parts:
                    col_count = len(parts)
                    break
            else:
                col_count = 0
    except OSError as exc:
        raise FileNotFoundError(f"Unable to read data file '{path}': {exc}") from exc

    if col_count == 0:
        raise ValueError(f"Data file '{path}' contains no data rows")

    for label, col in column_map.items():
        if col is None:
            continue
        if col > col_count:
            raise ValueError(
                f"Data file '{path}' does not have column {col} required for '{label}'"
            )


def _normalize_preprocessing(raw_steps: Any) -> list:
    if not raw_steps:
        return []
    if not isinstance(raw_steps, list):
        raise ValueError("Preprocessing steps must be a list of objects")
    normalized = []
    for step in raw_steps:
        if not isinstance(step, dict):
            raise ValueError("Each preprocessing step must be an object")
        step_type = step.get("type")
        if step_type not in {"filter", "transform"}:
            raise ValueError("Preprocessing step type must be 'filter' or 'transform'")
        expr = step.get("expression")
        if not isinstance(expr, str) or not expr.strip():
            raise ValueError("Preprocessing steps require a non-empty 'expression'")
        normalized_step = {"type": step_type, "expression": expr.strip()}
        if step_type == "transform":
            target = step.get("target")
            if target is None:
                raise ValueError("Transform steps require a 'target' column (e.g., 'col2')")
            normalized_step["target"] = str(target)
        normalized.append(normalized_step)
    return normalized


def infer_parameters(formula: str) -> list[str]:
    tokens = re.findall(r"[A-Za-zα-ωΑ-Ω_][A-Za-z0-9α-ωΑ-Ω_]*", formula or "")
    params: list[str] = []
    for token in tokens:
        if token in BLACKLIST:
            continue
        if token not in params:
            params.append(token)
    return params


def _normalize_dataset_entry(
    dataset: dict,
    *,
    base_dir: str,
    default_style: StyleConfig,
    fit_title: str,
    dataset_index: int,
) -> dict:
    if not isinstance(dataset, dict):
        raise ValueError(
            f"Dataset #{dataset_index} for fit '{fit_title}' must be an object"
        )

    raw_data_source = dataset.get("data_source")
    raw_source = raw_data_source if isinstance(raw_data_source, dict) else {}
    data_path = (
        raw_source.get("path")
        or dataset.get("path")
        or (dataset.get("datafile") if isinstance(dataset.get("datafile"), str) else "")
    )
    if not data_path:
        raise FileNotFoundError(
            f"Data file not specified for dataset #{dataset_index} in fit '{fit_title}'"
        )
    if not os.path.isabs(data_path):
        data_path = os.path.abspath(os.path.join(base_dir, data_path))
    if not os.path.exists(data_path):
        raise FileNotFoundError(
            f"Data file not found for dataset #{dataset_index} in fit '{fit_title}': {data_path}"
        )

    raw_columns = raw_source.get("columns") if isinstance(raw_source, dict) else None
    if raw_columns is None:
        raw_columns = dataset.get("columns")
    columns = _ensure_columns_dict(raw_columns)
    _validate_columns_exist(data_path, columns)

    raw_preprocessing = raw_source.get("preprocessing") if isinstance(raw_source, dict) else None
    if raw_preprocessing is None:
        raw_preprocessing = dataset.get("preprocessing")
    preprocessing = _normalize_preprocessing(raw_preprocessing)

    style_model = copy.deepcopy(default_style)
    raw_style = dataset.get("style")
    style_overrides = raw_style if isinstance(raw_style, dict) else {}
    if style_overrides:
        style_model.apply_overrides(style_overrides)

    color = dataset.get("color")
    if color:
        style_model.line_color = color

    label = dataset.get("label") or f"Dataset {dataset_index}"
    pane = dataset.get("pane")
    pane_index = dataset.get("pane_index")
    if pane_index is not None:
        try:
            pane_index = int(pane_index)
        except (TypeError, ValueError):
            pane_index = None
        else:
            if pane_index <= 0:
                pane_index = None

    data_source = {
        "path": data_path,
        "columns": columns,
        "preprocessing": preprocessing,
    }

    dataset_info = {
        "label": label,
        "datafile": data_path,
        "column_map": columns,
        "error_bars": bool(columns.get("error")),
        "style": style_model.to_dict(),
        "style_model": style_model,
        "data_source": data_source,
    }

    if pane not in {None, ""}:
        dataset_info["pane"] = pane
    if pane_index is not None:
        dataset_info["pane_index"] = pane_index

    return dataset_info


def normalize_plots(cfg: dict, config_path: str) -> list[dict]:
    if isinstance(cfg.get("plots"), list):
        return cfg["plots"]

    fits = cfg.get("fits") or []
    if not isinstance(fits, list):
        raise ValueError("Config must contain a 'fits' list")

    base_dir = os.path.dirname(os.path.abspath(config_path))
    normalized: list[dict] = []
    for fit in fits:
        formula = fit.get("formula") or fit.get("fit_formula") or "a*x + b"
        params_dict = fit.get("parameters") if isinstance(fit.get("parameters"), dict) else {}
        params = list(params_dict.keys()) if params_dict else infer_parameters(formula)
        if not params:
            raise ValueError(f"Cannot infer parameters for formula '{formula}'")

        style_cfg = StyleConfig.from_dict(fit.get("style"), fallback_color=fit.get("color"))
        if fit.get("color"):
            style_cfg.line_color = fit["color"]
        else:
            fit["color"] = style_cfg.line_color
        style = style_cfg.to_dict()

        layout = normalize_layout(fit.get("layout"))

        datasets_cfg = fit.get("datasets") if isinstance(fit.get("datasets"), list) else []
        datasets: list[dict] = []
        if datasets_cfg:
            for idx, dataset_cfg in enumerate(datasets_cfg, start=1):
                datasets.append(
                    _normalize_dataset_entry(
                        dataset_cfg,
                        base_dir=base_dir,
                        default_style=style_cfg,
                        fit_title=fit.get("title", "Untitled"),
                        dataset_index=idx,
                    )
                )
        else:
            data_source = fit.get("data_source") if isinstance(fit.get("data_source"), dict) else {}
            fallback_dataset = copy.deepcopy(data_source)
            if not isinstance(fallback_dataset, dict):
                fallback_dataset = {}
            if fit.get("datafile") and not fallback_dataset.get("path"):
                fallback_dataset["path"] = fit.get("datafile")
            datasets.append(
                _normalize_dataset_entry(
                    {"label": fit.get("title", "Untitled"), "data_source": fallback_dataset},
                    base_dir=base_dir,
                    default_style=style_cfg,
                    fit_title=fit.get("title", "Untitled"),
                    dataset_index=1,
                )
            )

        if not datasets:
            raise ValueError(
                f"Fit '{fit.get('title', 'Untitled')}' must define at least one dataset"
            )

        primary_dataset = datasets[0]
        initial_params = {}
        for key in params:
            try:
                initial_params[key] = float(params_dict.get(key, ""))
            except (TypeError, ValueError, AttributeError):
                continue

        normalized.append(
            {
                "title": fit.get("title", "Untitled"),
                "fit_formula": formula,
                "datafile": primary_dataset["datafile"],
                "residuals": bool(fit.get("residuals", True)),
                "style": style,
                "style_model": style_cfg,
                "fit_params": params,
                "initial_params": initial_params,
                "column_map": primary_dataset["column_map"],
                "error_bars": primary_dataset["error_bars"],
                "data_source": primary_dataset["data_source"],
                "datasets": datasets,
                "layout": layout,
            }
        )

    return normalized
