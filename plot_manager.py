from __future__ import annotations

import copy
import datetime
import json
import math
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

from plotinator.config.style import StyleConfig
from plotinator.engine.geometries import GEOMETRY_REGISTRY


PYFIT_RE = re.compile(
    r"^PYFIT\s+([A-Za-z_]\w*)\s+([-+]?[\d\.]+(?:[eE][-+]?\d+)?)\s+([-+]?[\d\.]+(?:[eE][-+]?\d+)?)$",
    re.MULTILINE,
)
BLACKLIST = {"x", "sin", "cos", "tan", "exp", "log", "sqrt", "np", "math"}


# ---------- helpers ----------


def _coerce_positive_int(value, default: int) -> int:
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        return default
    return ivalue if ivalue > 0 else default


def _coerce_bool(value, default: bool) -> bool:
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


def _normalize_layout(raw_layout: dict | None) -> dict:
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


def run_gnuplot_script(gnuplot_code: str, workdir: str) -> str:
    """Run a gnuplot script inside *workdir* and return combined stdout/stderr."""

    script_path = os.path.join(workdir, "temp_plot.plt")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(gnuplot_code)

    result = subprocess.run(
        ["gnuplot", script_path],
        cwd=workdir,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    output = (result.stdout or "") + (result.stderr or "")

    with open(os.path.join(workdir, "log.txt"), "w", encoding="utf-8") as lf:
        lf.write(output)

    return output


def parse_fit_output(output_text: str) -> dict:
    params = {}
    for name, val, err in PYFIT_RE.findall(output_text):
        params[name] = {"value": float(val), "error": float(err)}
    return params


def compute_residual_metrics(
    datafile: str, column_map: dict, params: dict, formula: str
) -> dict:
    """Compute residual statistics (mean, std, RMSE) for the fitted curve."""

    expr = formula
    for name, values in params.items():
        expr = re.sub(rf"\\b{name}\\b", str(values["value"]), expr)

    x_col = int(column_map.get("x", 1)) - 1
    y_col = int(column_map.get("y", 2)) - 1
    data = np.loadtxt(datafile, usecols=(x_col, y_col))
    if data.ndim == 1:
        data = data.reshape(-1, 2)
    x, y = data[:, 0], data[:, 1]

    f = np.vectorize(lambda xx: eval(expr, {"x": xx, "math": math, "np": np}))
    yfit = f(x)
    residuals = y - yfit

    mean = float(np.mean(residuals))
    std = float(np.std(residuals))
    rmse = float(np.sqrt(np.mean(residuals**2)))

    return {"mean": mean, "std": std, "rmse": rmse}


def generate_gnuplot_code(
    cfg: dict, out_plot: str | None, out_residuals: str | None = None
) -> str:
    raw_style = cfg.get("style_model") or cfg.get("style")
    style_cfg = (
        raw_style
        if isinstance(raw_style, StyleConfig)
        else StyleConfig.from_dict(raw_style, fallback_color=cfg.get("color"))
    )

    pt = style_cfg.point_type
    lw = style_cfg.line_width
    col = style_cfg.line_color

    formula = cfg["fit_formula"]
    params = cfg["fit_params"]
    params_csv = ",".join(params)
    datafile = os.path.abspath(cfg["datafile"]).replace("\\", "/")
    column_map = cfg.get("column_map", {})
    x_col = column_map.get("x", 1)
    y_col = column_map.get("y", 2)
    err_col = column_map.get("error")
    weight_col = column_map.get("weight")
    use_err = bool(err_col)

    def _style_commands(
        title: str,
        x_label: str,
        y_label: str,
        *,
        force_linear_y: bool = False,
        include_terminal: bool = True,
        include_title: bool = True,
        show_legend: bool | None = None,
        suppress_xlabel: bool = False,
        suppress_ylabel: bool = False,
        suppress_xtics: bool = False,
        suppress_ytics: bool = False,
    ) -> str:
        lines: list[str] = ["set encoding utf8"]

        if include_terminal:
            lines.append(
                f"set terminal pngcairo size 800,600 font \"{_escape(style_cfg.font_family)},{style_cfg.font_size}\""
            )

        if include_title:
            lines.append(
                f"set title \"{_escape(title)}\" font \",{style_cfg.title_font_size}\""
            )
        else:
            lines.append("unset title")

        if suppress_xlabel:
            lines.append("set xlabel \"\"")
        else:
            lines.append(
                f"set xlabel \"{_escape(x_label)}\" font \",{style_cfg.axis_label_font_size}\""
            )

        if suppress_ylabel:
            lines.append("set ylabel \"\"")
        else:
            lines.append(
                f"set ylabel \"{_escape(y_label)}\" font \",{style_cfg.axis_label_font_size}\""
            )

        lines.append(f"set xtics font \",{style_cfg.tick_font_size}\"")
        lines.append(f"set ytics font \",{style_cfg.tick_font_size}\"")

        if style_cfg.x_scale == "log":
            lines.append("set logscale x")
        else:
            lines.append("unset logscale x")

        if not force_linear_y and style_cfg.y_scale == "log":
            lines.append("set logscale y")
        else:
            lines.append("unset logscale y")

        if suppress_xtics:
            lines.append("set format x \"\"")
        elif style_cfg.x_tick_format:
            lines.append(f"set format x \"{_escape(style_cfg.x_tick_format)}\"")
        else:
            lines.append("set format x")

        if suppress_ytics:
            lines.append("set format y \"\"")
        elif style_cfg.y_tick_format and not force_linear_y:
            lines.append(f"set format y \"{_escape(style_cfg.y_tick_format)}\"")
        else:
            lines.append("set format y")

        if style_cfg.grid:
            lines.append(f"set grid {style_cfg.grid_layer}")
        else:
            lines.append("unset grid")

        if show_legend is None:
            show_legend = style_cfg.legend_visible

        if show_legend and not force_linear_y:
            lines.append(style_cfg.legend_gnuplot_clause())
        else:
            lines.append("unset key")

        return "\n".join(lines)

    guesses = estimate_initial_params(datafile, params, column_map)
    overrides = cfg.get("initial_params") or {}
    for key, value in overrides.items():
        if key in guesses and isinstance(value, (int, float)):
            guesses[key] = float(value)
    init_lines = "\n".join([f"{p} = {guesses.get(p, 1.0)}" for p in params])
    prints = "\n".join(
        [
            (
                f'if (exists("{p}_err")) {{ print sprintf("PYFIT %s %0.16g %0.16g", "{p}", {p}, {p}_err) }} '
                f'else {{ print sprintf("PYFIT %s %0.16g %0.16g", "{p}", {p}, 0.0) }}'
            )
            for p in params
        ]
    )

    fit_using: list[str] = []
    if x_col != 1 or y_col != 2 or err_col or weight_col:
        fit_using.extend([str(x_col), str(y_col)])
        if err_col:
            fit_using.append(str(err_col))
        elif weight_col:
            fit_using.append(str(weight_col))

    fit_clause = f'fit f(x) "{datafile}"'
    if fit_using:
        fit_clause += f" using {':'.join(fit_using)}"
    fit_clause += f" via {params_csv}"

    layout_cfg = _normalize_layout(cfg.get("layout"))

    base_style = _style_commands(
        cfg["title"],
        style_cfg.axis_label_with_unit("x"),
        style_cfg.axis_label_with_unit("y"),
        include_title=not bool(out_plot),
        show_legend=False,
    )

    lines: list[str] = [
        base_style,
        "",
        "set fit errorvariables",
        init_lines,
        "",
        f"f(x) = {formula}",
        fit_clause,
        "",
        prints,
        "",
    ]

    if out_plot:
        out_plot_path = os.path.abspath(out_plot).replace("\\", "/")
        datasets = list(cfg.get("datasets") or [])
        if not datasets:
            datasets = [
                {
                    "label": cfg.get("title", "Dataset"),
                    "datafile": datafile,
                    "column_map": column_map,
                    "error_bars": use_err,
                    "style_model": style_cfg,
                    "style": style_cfg.to_dict(),
                }
            ]

        pane_groups: dict[int, list[dict]] = {}
        pane_titles: dict[int, str] = {}
        name_slots: dict[str, int] = {}
        max_slot = 0

        for idx, dataset in enumerate(datasets, start=1):
            ds = dataset
            pane_title = None
            slot: int | None = None

            pane_index = ds.get("pane_index")
            if pane_index is not None:
                try:
                    slot = int(pane_index)
                except (TypeError, ValueError):
                    slot = None
                else:
                    if slot <= 0:
                        slot = None

            if slot is None:
                pane_name = ds.get("pane")
                if pane_name:
                    pane_key = str(pane_name)
                    slot = name_slots.setdefault(pane_key, len(name_slots) + 1)
                    pane_title = pane_key

            if slot is None:
                slot = 1

            if pane_title is None:
                pane_title = (
                    str(ds.get("pane"))
                    if ds.get("pane")
                    else ds.get("label")
                    or f"Pane {slot}"
                )

            pane_groups.setdefault(slot, []).append(ds)
            pane_titles.setdefault(slot, pane_title)
            max_slot = max(max_slot, slot)

        rows = max(1, int(layout_cfg.get("rows", 1)))
        columns = max(1, int(layout_cfg.get("columns", 1)))
        total_slots = max(rows * columns, max_slot or 1)
        shared_x = bool(layout_cfg.get("shared_x"))
        shared_y = bool(layout_cfg.get("shared_y"))
        show_legend = bool(layout_cfg.get("show_legend", True))

        lines.append(f"set output \"{out_plot_path}\"")
        lines.append(
            f"set multiplot layout {rows},{columns} title \"{_escape(cfg['title'])}\""
        )

        x_label = style_cfg.axis_label_with_unit("x")
        y_label = style_cfg.axis_label_with_unit("y")

        for slot in range(1, total_slots + 1):
            pane_datasets = pane_groups.get(slot, [])
            pane_title = pane_titles.get(slot, f"{cfg['title']} — Pane {slot}")
            row_idx = (slot - 1) // columns if columns else 0
            col_idx = (slot - 1) % columns if columns else 0

            suppress_xlabel = shared_x and row_idx < rows - 1
            suppress_ylabel = shared_y and col_idx > 0

            pane_style = _style_commands(
                pane_title,
                x_label,
                y_label,
                include_terminal=False,
                show_legend=show_legend and bool(pane_datasets),
                suppress_xlabel=suppress_xlabel,
                suppress_ylabel=suppress_ylabel,
                suppress_xtics=suppress_xlabel,
                suppress_ytics=suppress_ylabel,
            )
            lines.append(pane_style)

            if not pane_datasets:
                lines.append("plot NaN notitle")
                continue

            plot_parts: list[str] = []
            for ds in pane_datasets:
                ds_style_model = ds.get("style_model")
                if not isinstance(ds_style_model, StyleConfig):
                    ds_style_model = StyleConfig.from_dict(
                        ds.get("style"), fallback_color=style_cfg.line_color
                    )
                ds_file = os.path.abspath(ds.get("datafile", datafile)).replace("\\", "/")
                ds_cols = ds.get("column_map") or {}
                dx = int(ds_cols.get("x", 1))
                dy = int(ds_cols.get("y", 2))
                derr = ds_cols.get("error")
                dlabel = ds.get("label") or f"Dataset {slot}"

                if derr:
                    plot_parts.append(
                        (
                            f"\"{ds_file}\" using {dx}:{dy}:{derr} with yerrorbars "
                            f"title \"{_escape(dlabel)}\" pt {ds_style_model.point_type} "
                            f"lw {ds_style_model.line_width} lc rgb \"{ds_style_model.line_color}\""
                        )
                    )
                else:
                    plot_parts.append(
                        (
                            f"\"{ds_file}\" using {dx}:{dy} with points "
                            f"title \"{_escape(dlabel)}\" pt {ds_style_model.point_type} "
                            f"lc rgb \"{ds_style_model.line_color}\""
                        )
                    )

            plot_parts.append(
                (
                    f"f(x) title sprintf(\"{formula}\") with lines "
                    f"lw {lw} lc rgb \"{col}\""
                )
            )

            lines.append("plot " + ", \\\n+     ".join(plot_parts))

        lines.append("unset multiplot")
        lines.append("unset output")
        lines.append("")

    if out_residuals:
        out_res_path = os.path.abspath(out_residuals).replace("\\", "/")
        residual_style = _style_commands(
            f"Residuals — {cfg['title']}",
            style_cfg.axis_label_with_unit("x"),
            "Residual (y - f(x))",
            force_linear_y=True,
            include_terminal=not bool(out_plot),
            show_legend=False,
        )
        lines.append(f"set output \"{out_res_path}\"")
        lines.append(residual_style)
        lines.append(
            (
                f"plot \"{datafile}\" using {x_col}:(column({y_col}) - f(column({x_col}))) "
                f"with points pt {pt} title \"Residuals\", \\\n+     0 with lines notitle lc rgb \"gray\""
            )
        )
        lines.append("unset output")

    return "\n".join(lines)


def _ensure_columns_dict(columns: dict | None) -> dict:
    base = {"x": 1, "y": 2, "z": None, "error": None, "weight": None}
    if not isinstance(columns, dict):
        return base
    result = base.copy()
    for key in ("x", "y", "z", "error", "weight"):
        val = columns.get(key)
        if val is None or val == "":
            result[key] = None if key in {"z", "error", "weight"} else base[key]
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


def _normalize_preprocessing(raw_steps) -> list:
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
    dataset_color = dataset.get("color")
    if style_overrides:
        override_cfg = StyleConfig.from_dict(
            style_overrides,
            fallback_color=dataset_color or style_model.line_color,
        )
        for field in style_overrides.keys():
            if field in style_model.__dataclass_fields__:
                setattr(style_model, field, getattr(override_cfg, field))
    if dataset_color:
        style_model.line_color = dataset_color

    label = (
        dataset.get("label")
        or dataset.get("title")
        or dataset.get("name")
        or f"Dataset {dataset_index}"
    )

    pane = dataset.get("pane")
    if isinstance(pane, str):
        pane = pane.strip()
    elif pane is not None and not isinstance(pane, (int, float)):
        pane = str(pane)

    pane_index = dataset.get("pane_index")
    if pane_index is not None:
        try:
            pane_index = int(pane_index)
        except (TypeError, ValueError):
            pane_index = None
        else:
            if pane_index <= 0:
                pane_index = None

    dataset_info = {
        "label": label,
        "datafile": data_path,
        "column_map": columns,
        "error_bars": bool(columns.get("error")),
        "style": style_model.to_dict(),
        "style_model": style_model,
        "data_source": {
            "path": data_path,
            "columns": columns,
            "preprocessing": preprocessing,
        },
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
        title = fit.get("title", "Untitled")

        raw_geometry = fit.get("geometry")
        if isinstance(raw_geometry, dict):
            geometry_type = raw_geometry.get("type", "curve")
            geometry_options = raw_geometry.get("options")
        elif isinstance(raw_geometry, str):
            geometry_type = raw_geometry
            geometry_options = {}
        else:
            geometry_type = "curve"
            geometry_options = {}

        try:
            geometry = GEOMETRY_REGISTRY.get(geometry_type)
        except KeyError as exc:
            raise ValueError(f"Fit '{title}' references unknown geometry '{geometry_type}'") from exc

        style_cfg = StyleConfig.from_dict(fit.get("style"), fallback_color=fit.get("color"))
        if fit.get("color"):
            style_cfg.line_color = fit["color"]
        else:
            fit["color"] = style_cfg.line_color
        style = style_cfg.to_dict()

        layout = _normalize_layout(fit.get("layout"))

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

        column_map = primary_dataset["column_map"]
        try:
            normalized_options = geometry.normalize_options(geometry_options, column_map=column_map)
        except ValueError as exc:
            raise ValueError(f"Fit '{title}' has invalid geometry options: {exc}") from exc

        if geometry.supports_fit:
            formula = fit.get("formula") or fit.get("fit_formula") or "a*x + b"
            params_dict = fit.get("parameters") if isinstance(fit.get("parameters"), dict) else {}
            params = list(params_dict.keys()) if params_dict else infer_parameters(formula)
            if not params:
                raise ValueError(f"Cannot infer parameters for formula '{formula}'")
            initial_params = {}
            for key in params:
                try:
                    initial_params[key] = float(params_dict.get(key, ""))
                except (TypeError, ValueError, AttributeError):
                    continue
        else:
            formula = fit.get("formula") or fit.get("fit_formula") or ""
            params = []
            initial_params = {}

        residuals_enabled = bool(fit.get("residuals", True)) and geometry.supports_residuals

        normalized.append(
            {
                "title": title,
                "fit_formula": formula,
                "datafile": primary_dataset["datafile"],
                "residuals": residuals_enabled,
                "style": style,
                "style_model": style_cfg,
                "fit_params": params,
                "initial_params": initial_params,
                "column_map": column_map,
                "error_bars": primary_dataset["error_bars"],
                "data_source": primary_dataset["data_source"],
                "datasets": datasets,
                "layout": layout,
                "geometry": {"type": geometry.type, "options": normalized_options},
            }
        )

    return normalized


# ---------- main ----------


def _load_data_matrix(path: str) -> np.ndarray:
    data = np.loadtxt(path, ndmin=2)
    if data.ndim == 1:
        data = data.reshape(-1, 1)
    if data.size == 0 or data.shape[0] == 0:
        raise ValueError(f"Data file '{path}' contained no usable rows")
    return data


def _column_ref_to_index(ref: str | int) -> int:
    if isinstance(ref, int):
        idx = ref - 1
    else:
        text = str(ref).strip().lower()
        if text.startswith("col"):
            text = text[3:]
        idx = int(text) - 1
    if idx < 0:
        raise ValueError("Column references must be 1-based and positive")
    return idx


def _build_eval_context(data: np.ndarray) -> dict:
    ctx = {f"col{i+1}": data[:, i] for i in range(data.shape[1])}
    ctx.update({"np": np, "math": math})
    return ctx


def _apply_preprocessing(data: np.ndarray, steps: list[dict]) -> tuple[np.ndarray, list[dict]]:
    if not steps:
        return data, []

    processed = data
    applied: list[dict] = []
    for step in steps:
        ctx = _build_eval_context(processed)
        expr = step["expression"]
        if step["type"] == "filter":
            try:
                mask = eval(expr, {"np": np, "math": math}, ctx)
            except Exception as exc:
                raise ValueError(f"Failed to evaluate filter expression '{expr}': {exc}") from exc
            mask = np.asarray(mask)
            if mask.dtype != bool:
                mask = mask.astype(bool)
            if mask.shape[0] != processed.shape[0]:
                raise ValueError(
                    f"Filter expression '{expr}' produced mask of length {mask.shape[0]}, expected {processed.shape[0]}"
                )
            processed = processed[mask]
            applied.append({"type": "filter", "expression": expr, "retained_rows": int(processed.shape[0])})
        elif step["type"] == "transform":
            target_idx = _column_ref_to_index(step["target"])
            if target_idx >= processed.shape[1]:
                raise ValueError(
                    f"Transform target column '{step['target']}' (index {target_idx+1}) is out of bounds"
                )
            try:
                values = eval(expr, {"np": np, "math": math}, ctx)
            except Exception as exc:
                raise ValueError(f"Failed to evaluate transform expression '{expr}': {exc}") from exc
            values = np.asarray(values)
            if values.ndim == 0:
                processed[:, target_idx] = values
            else:
                if values.shape[0] != processed.shape[0]:
                    raise ValueError(
                        f"Transform expression '{expr}' produced {values.shape[0]} rows, expected {processed.shape[0]}"
                    )
                processed[:, target_idx] = values
            applied.append({"type": "transform", "expression": expr, "target": step["target"]})
        else:
            raise ValueError(f"Unsupported preprocessing step type: {step['type']}")

        if processed.shape[0] == 0:
            raise ValueError("All rows were removed by preprocessing steps")

    return processed, applied


def prepare_datafile(plot_cfg: dict, plot_dir: str) -> dict:
    data_source = plot_cfg.get("data_source") or {}
    source_path = data_source.get("path") or plot_cfg.get("datafile")
    steps = data_source.get("preprocessing") or []

    if not steps:
        data = _load_data_matrix(source_path)
        return {
            "path": source_path,
            "rows_before": int(data.shape[0]),
            "rows_after": int(data.shape[0]),
            "applied_steps": [],
        }

    raw_data = _load_data_matrix(source_path)
    processed, applied = _apply_preprocessing(raw_data.copy(), steps)

    processed_path = os.path.join(plot_dir, "preprocessed.dat")
    np.savetxt(processed_path, processed, fmt="%.12g")

    return {
        "path": processed_path,
        "rows_before": int(raw_data.shape[0]),
        "rows_after": int(processed.shape[0]),
        "applied_steps": applied,
    }


def process_plot(plot_cfg: dict, base_output: str) -> dict:
    """Handle a single plot end-to-end: create folder, run fit, residuals, and metrics."""

    plot_cfg = copy.deepcopy(plot_cfg)
    safe_title = plot_cfg["title"].replace(" ", "_")
    plot_dir = os.path.join(base_output, f"plot_{safe_title}")
    os.makedirs(plot_dir, exist_ok=True)

    geometry_info = plot_cfg.get("geometry") or {"type": "curve", "options": {}}
    geometry_type = geometry_info.get("type", "curve")
    geometry = GEOMETRY_REGISTRY.get(geometry_type)

    out_plot = os.path.join(plot_dir, "plot.png").replace("\\", "/")

    datasets_cfg = list(plot_cfg.get("datasets") or [])
    if not datasets_cfg:
        datasets_cfg = [
            {
                "label": plot_cfg.get("title", "Dataset"),
                "datafile": plot_cfg.get("datafile"),
                "column_map": plot_cfg.get("column_map", {}),
                "error_bars": plot_cfg.get("error_bars"),
                "style_model": plot_cfg.get("style_model"),
                "style": plot_cfg.get("style"),
                "data_source": plot_cfg.get("data_source", {}),
            }
        ]

    prepared_datasets: list[dict] = []
    datasets_report: list[dict] = []

    for idx, dataset in enumerate(datasets_cfg, start=1):
        ds_copy = copy.deepcopy(dataset)
        dataset_dir = os.path.join(plot_dir, f"dataset_{idx}")
        os.makedirs(dataset_dir, exist_ok=True)

        prep_cfg = {
            "data_source": ds_copy.get("data_source"),
            "datafile": ds_copy.get("datafile"),
        }
        prep_info = dict(prepare_datafile(prep_cfg, dataset_dir))
        prep_info["path"] = os.path.abspath(prep_info["path"]).replace("\\", "/")
        prepared_path = prep_info["path"]
        ds_copy["datafile"] = prepared_path
        ds_copy["prepared_data"] = prep_info

        prepared_datasets.append(ds_copy)

        ds_data_source = copy.deepcopy(ds_copy.get("data_source", {}))
        if ds_data_source.get("path"):
            ds_data_source["path"] = os.path.abspath(ds_data_source["path"]).replace(
                "\\", "/"
            )

        ds_copy["data_source"] = ds_data_source

        datasets_report.append(
            {
                "label": ds_copy.get("label"),
                "pane": ds_copy.get("pane"),
                "pane_index": ds_copy.get("pane_index"),
                "columns": ds_copy.get("column_map", {}),
                "style": ds_copy.get("style", {}),
                "data_source": ds_data_source,
                "prepared_data": prep_info,
            }
        )

    plot_cfg["datasets"] = prepared_datasets
    primary_dataset = prepared_datasets[0]
    data_prep = primary_dataset.get("prepared_data", {})
    plot_cfg["datafile"] = primary_dataset["datafile"]
    plot_cfg["data_source"] = primary_dataset.get(
        "data_source", plot_cfg.get("data_source", {})
    )
    plot_cfg["column_map"] = primary_dataset.get(
        "column_map", plot_cfg.get("column_map", {})
    )

    main_code = generate_gnuplot_code(plot_cfg, out_plot)
    output_text = run_gnuplot_script(main_code, workdir=plot_dir)
    params = parse_fit_output(output_text) if geometry.supports_fit else {}

    residuals_path: str | None
    metrics: dict | None
    if geometry.supports_residuals and plot_cfg.get("residuals", True) and params:
        residuals_path = os.path.join(plot_dir, "residuals.png").replace("\\", "/")
        metrics = compute_residual_metrics(
            plot_cfg["datafile"], plot_cfg.get("column_map", {}), params, plot_cfg["fit_formula"]
        )
        resid_code = generate_gnuplot_code(plot_cfg, out_plot=None, out_residuals=residuals_path)
        run_gnuplot_script(resid_code, workdir=plot_dir)
    else:
        residuals_path = None
        metrics = None

    column_map = plot_cfg.get("column_map", {})
    confidence_notes = None
    if column_map.get("error"):
        confidence_notes = f"Fit weighted by error column {column_map['error']}"
    elif column_map.get("weight"):
        confidence_notes = f"Fit weighted by column {column_map['weight']}"

    assets = [
        {
            "type": geometry.type,
            "path": out_plot,
            "caption": geometry.asset_caption(plot_cfg),
        }
    ]
    if residuals_path:
        assets.append(
            {
                "type": "residuals",
                "path": residuals_path,
                "caption": geometry.residual_caption(plot_cfg),
            }
        )

    result = {
        "title": plot_cfg["title"],
        "formula": plot_cfg["fit_formula"],
        "parameters": params,
        "metrics": metrics,
        "datafile": plot_cfg["datafile"],
        "output_plot": out_plot,
        "residuals_plot": residuals_path,
        "data_source": {
            "path": os.path.abspath(
                plot_cfg.get("data_source", {}).get("path", plot_cfg["datafile"])
            ).replace("\\", "/"),
            "columns": column_map,
            "rows_before": data_prep.get("rows_before"),
            "rows_after": data_prep.get("rows_after"),
            "preprocessing": data_prep.get("applied_steps", []),
        },
        "layout": plot_cfg.get("layout", {}),
        "datasets": datasets_report,
        "canvases": {
            "combined": out_plot,
            "residuals": residuals_path,
        },
        "confidence_notes": confidence_notes,
        "geometry": geometry_info,
        "assets": assets,
        "matplotlib_stub": geometry.generate_matplotlib_stub(plot_cfg),
    }

    print(f"[OK] Finished: {plot_cfg['title']}")
    return result


def main() -> int:
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.json"

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    try:
        plots = normalize_plots(cfg, config_path)
    except Exception as exc:
        print(f"[X] {exc}")
        return 1

    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    base_output = os.path.abspath(os.path.join("outputs", ts))
    os.makedirs(base_output, exist_ok=True)

    print(f"[RUN] Starting batch at {ts} ({len(plots)} plots)")

    results = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(process_plot, plot_cfg, base_output) for plot_cfg in plots]
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                print(f"[X] Error in one plot: {e}")

    all_results = {"timestamp": ts, "results": results}
    json_path = os.path.join(base_output, "fit_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    print(f"\n[COMPLETE] All fits complete. Results saved to:\n{json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
