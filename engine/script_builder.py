from __future__ import annotations

import math
import os
import re
from typing import Iterable

import numpy as np

from plotinator.config.style import StyleConfig

from .config import normalize_layout

__all__ = [
    "estimate_initial_params",
    "parse_fit_output",
    "parse_fit_statistics",
    "compute_residual_metrics",
    "generate_gnuplot_code",
]

PYFIT_RE = re.compile(
    r"^PYFIT\s+([A-Za-z_]\w*)\s+([-+]?[\d\.]+(?:[eE][-+]?\d+)?)\s+([-+]?[\d\.]+(?:[eE][-+]?\d+)?)$",
    re.MULTILINE,
)

FIT_CHISQ_RE = re.compile(r"sum of squares of residuals\s*:\s*([-+\deE\.]+)")
FIT_REDUCED_RE = re.compile(r"reduced chisquare\).*:\s*([-+\deE\.]+)")
FIT_RMS_RE = re.compile(r"rms of residuals.*:\s*([-+\deE\.]+)")
FIT_NDF_RE = re.compile(r"degrees of freedom.*:\s*(\d+)")


def estimate_initial_params(
    datafile: str, params: Iterable[str], column_map: dict | None = None
) -> dict[str, float]:
    column_map = column_map or {}
    x_idx = int(column_map.get("x", 1)) - 1
    y_idx = int(column_map.get("y", 2)) - 1
    arr = np.loadtxt(datafile, usecols=(x_idx, y_idx))
    if arr.ndim == 1:
        arr = arr.reshape(-1, 2)
    y = arr[:, 1]

    y_abs = np.abs(y)
    scale = float(
        max(
            y_abs.mean() if y_abs.size else 0.0,
            np.ptp(y_abs) if y_abs.size else 0.0,
            1.0,
        )
    )

    floor_eps = max(1e-3, scale * 1e-6)

    guesses: dict[str, float] = {}
    for i, param in enumerate(params, start=1):
        val = 0.5 * i * scale
        if abs(val) < floor_eps:
            val = floor_eps
        guesses[param] = float(val)

    seen: set[float] = set()
    bump = floor_eps
    for key in list(guesses.keys()):
        value = guesses[key]
        if not (np.isfinite(value) and abs(value) >= floor_eps):
            value = floor_eps
        while value in seen:
            value += bump
        seen.add(value)
        guesses[key] = value

    return guesses


def parse_fit_output(output_text: str) -> dict:
    params = {}
    for name, val, err in PYFIT_RE.findall(output_text):
        params[name] = {"value": float(val), "error": float(err)}
    return params


def parse_fit_statistics(output_text: str) -> dict[str, float]:
    """Extract chi-squared style statistics from a gnuplot fit log."""

    stats: dict[str, float] = {}

    if match := FIT_CHISQ_RE.search(output_text):
        try:
            stats["chi_squared"] = float(match.group(1))
        except ValueError:
            pass

    if match := FIT_REDUCED_RE.search(output_text):
        try:
            stats["reduced_chi_squared"] = float(match.group(1))
        except ValueError:
            pass

    if match := FIT_RMS_RE.search(output_text):
        try:
            stats["rms"] = float(match.group(1))
        except ValueError:
            pass

    if match := FIT_NDF_RE.search(output_text):
        try:
            stats["degrees_of_freedom"] = float(match.group(1))
        except ValueError:
            pass

    return stats


def compute_residual_metrics(
    datafile: str, column_map: dict, params: dict, formula: str
) -> dict[str, float]:
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


def _escape(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace('"', '\"')


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

    layout_cfg = normalize_layout(cfg.get("layout"))

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
                (
                    "set terminal pngcairo size 800,600 font "
                    f"\"{_escape(style_cfg.font_family)},{style_cfg.font_size}\""
                )
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

        x_range_clause = style_cfg.axis_range_clause("x")
        if x_range_clause:
            lines.append(x_range_clause)
        else:
            lines.append("set autoscale x")

        if force_linear_y:
            lines.append("set autoscale y")
        else:
            y_range_clause = style_cfg.axis_range_clause("y")
            if y_range_clause:
                lines.append(y_range_clause)
            else:
                lines.append("set autoscale y")

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

        lines.append(style_cfg.axis_ticks_clause("x"))
        if force_linear_y:
            lines.append("set ytics autofreq")
        else:
            lines.append(style_cfg.axis_ticks_clause("y"))

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
    def _format_param_print(name: str) -> str:
        return "".join(
            [
                f'if (exists("{name}_err")) {{ ',
                (
                    'print sprintf("PYFIT %s %0.16g %0.16g", '
                    f'"{name}", {name}, {name}_err) }} '
                ),
                "else { ",
                (
                    'print sprintf("PYFIT %s %0.16g %0.16g", '
                    f'"{name}", {name}, 0.0) }}'
                ),
            ]
        )

    prints = "\n".join(_format_param_print(p) for p in params)

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

        rows = max(1, int(layout_cfg.get("rows", 1)))
        columns = max(1, int(layout_cfg.get("columns", 1)))

        for _idx, dataset in enumerate(datasets, start=1):
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
        residual_plot_parts = [
            f'plot "{datafile}" using {x_col}:(column({y_col}) - f(column({x_col})))',
            f'with points pt {pt} title "Residuals", \\',
            '     0 with lines notitle lc rgb "gray"',
        ]
        residual_plot = " ".join(residual_plot_parts[:2]) + "\n" + residual_plot_parts[2]
        lines.append(residual_plot)
        lines.append("unset output")

    return "\n".join(lines)
