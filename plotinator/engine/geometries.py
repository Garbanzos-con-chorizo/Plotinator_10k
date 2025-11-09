from __future__ import annotations

"""Geometry registry and rendering helpers for Plotinator."""

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List

import numpy as np

from plotinator.config.style import StyleConfig


def _escape(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace('"', '\"')


def estimate_initial_params(
    datafile: str, params: list[str], column_map: dict | None = None
) -> dict:
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


@dataclass(slots=True)
class GeometryDefinition:
    """Describe a geometry/plot type supported by Plotinator."""

    type: str
    label: str
    supports_fit: bool = True
    supports_residuals: bool = True
    dimension: int = 2
    default_options: dict[str, Any] = field(default_factory=dict)

    def normalize_options(self, options: dict | None, *, column_map: dict) -> dict:
        if not isinstance(options, dict):
            options = {}
        normalized = self.default_options.copy()
        normalized.update({k: v for k, v in options.items() if v is not None})
        return normalized

    # ------------------------------------------------------------------
    def generate_gnuplot_script(
        self,
        plot_cfg: dict,
        style_cfg: StyleConfig,
        *,
        out_plot: str | None,
        out_residuals: str | None = None,
    ) -> str:
        raise NotImplementedError

    # ------------------------------------------------------------------
    def residual_caption(self, plot_cfg: dict) -> str:
        return "Residuals"

    # ------------------------------------------------------------------
    def asset_caption(self, plot_cfg: dict) -> str:
        return self.label

    # ------------------------------------------------------------------
    def generate_matplotlib_stub(self, plot_cfg: dict) -> str:
        """Return a small Matplotlib snippet to replicate the geometry."""

        geom = plot_cfg.get("geometry", {}).get("type", self.type)
        return (
            "# Matplotlib rendering for geometry '{geom}' is not wired yet.\n"
            "# This stub documents the intended usage."
        ).format(geom=geom)


class GeometryRegistry:
    def __init__(self) -> None:
        self._types: dict[str, GeometryDefinition] = {}

    def register(self, geometry: GeometryDefinition) -> None:
        self._types[geometry.type] = geometry

    def get(self, type_name: str) -> GeometryDefinition:
        try:
            return self._types[type_name]
        except KeyError as exc:
            raise KeyError(f"Unknown geometry type: {type_name}") from exc

    def choices(self) -> List[str]:
        return sorted(self._types.keys())

    def definitions(self) -> Iterable[GeometryDefinition]:
        return self._types.values()


class CurveGeometry(GeometryDefinition):
    def __init__(self) -> None:
        super().__init__("curve", "Curve fit", supports_fit=True, supports_residuals=True)

    def normalize_options(self, options: dict | None, *, column_map: dict) -> dict:
        return {}

    def generate_gnuplot_script(
        self,
        plot_cfg: dict,
        style_cfg: StyleConfig,
        *,
        out_plot: str | None,
        out_residuals: str | None = None,
    ) -> str:
        params = plot_cfg.get("fit_params", [])
        formula = plot_cfg.get("fit_formula", "a*x + b")
        params_csv = ",".join(params)
        datafile = plot_cfg["datafile"].replace("\\", "/")
        column_map = plot_cfg.get("column_map", {})
        x_col = column_map.get("x", 1)
        y_col = column_map.get("y", 2)
        err_col = column_map.get("error")
        weight_col = column_map.get("weight")
        pt = style_cfg.point_type
        lw = style_cfg.line_width
        col = style_cfg.line_color

        guesses = estimate_initial_params(datafile, params, column_map)
        overrides = plot_cfg.get("initial_params") or {}
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

        def _style_commands(title: str, x_label: str, y_label: str, *, force_linear_y: bool = False) -> str:
            lines: list[str] = [
                "set encoding utf8",
                (
                    "set terminal pngcairo size 800,600 font "
                    f"\"{_escape(style_cfg.font_family)},{style_cfg.font_size}\""
                ),
                f"set title \"{_escape(title)}\" font \",{style_cfg.title_font_size}\"",
                f"set xlabel \"{_escape(x_label)}\" font \",{style_cfg.axis_label_font_size}\"",
                f"set ylabel \"{_escape(y_label)}\" font \",{style_cfg.axis_label_font_size}\"",
                f"set xtics font \",{style_cfg.tick_font_size}\"",
                f"set ytics font \",{style_cfg.tick_font_size}\"",
            ]

            if style_cfg.x_scale == "log":
                lines.append("set logscale x")
            else:
                lines.append("unset logscale x")

            if not force_linear_y and style_cfg.y_scale == "log":
                lines.append("set logscale y")
            else:
                lines.append("unset logscale y")

            if style_cfg.x_tick_format:
                lines.append(f"set format x \"{_escape(style_cfg.x_tick_format)}\"")
            else:
                lines.append("set format x")

            if style_cfg.y_tick_format and not force_linear_y:
                lines.append(f"set format y \"{_escape(style_cfg.y_tick_format)}\"")
            else:
                lines.append("set format y")

            if style_cfg.grid:
                lines.append(f"set grid {style_cfg.grid_layer}")
            else:
                lines.append("unset grid")

            if style_cfg.legend_visible and not force_linear_y:
                lines.append(style_cfg.legend_gnuplot_clause())
            else:
                lines.append("unset key")

            return "\n".join(lines)

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

        code = f"""
{_style_commands(plot_cfg['title'], style_cfg.axis_label_with_unit('x'), style_cfg.axis_label_with_unit('y'))}

set fit errorvariables
{init_lines}

f(x) = {formula}
{fit_clause}

{prints}

"""
        if out_plot:
            code += f"set output \"{out_plot}\"\n"
            data_cols = [str(x_col), str(y_col)]
            if err_col:
                data_cols.append(str(err_col))
            data_using = ":".join(data_cols)
            if bool(err_col):
                code += (
                    f"plot \"{datafile}\" using {data_using} with yerrorbars title \"Data ±σ\" pt {pt}, \\\n"
                    f"     f(x) title sprintf(\"{formula}\") with lines lw {lw} lc rgb \"{col}\"\n"
                )
            else:
                code += (
                    f"plot \"{datafile}\" using {data_using} title \"Data\" with points pt {pt}, \\\n"
                    f"     f(x) title sprintf(\"{formula}\") with lines lw {lw} lc rgb \"{col}\"\n"
                )
            code += "unset output\n"

        if out_residuals:
            code += f"""
set output "{out_residuals}"
{_style_commands(f"Residuals — {plot_cfg['title']}", style_cfg.axis_label_with_unit('x'), "Residual (y - f(x))", force_linear_y=True)}
plot "{datafile}" using {x_col}:(column({y_col}) - f(column({x_col}))) with points pt {pt} title "Residuals", \\
     0 with lines notitle lc rgb "gray"
unset output
"""
        return code

    def asset_caption(self, plot_cfg: dict) -> str:
        formula = plot_cfg.get("fit_formula")
        if formula:
            return f"Curve fit: {formula}"
        return super().asset_caption(plot_cfg)


class HistogramGeometry(GeometryDefinition):
    def __init__(self) -> None:
        super().__init__(
            "histogram",
            "Histogram",
            supports_fit=False,
            supports_residuals=False,
            dimension=2,
            default_options={"bins": 30, "column": "x", "density": False},
        )

    def normalize_options(self, options: dict | None, *, column_map: dict) -> dict:
        normalized = super().normalize_options(options, column_map=column_map)
        try:
            normalized["bins"] = max(1, int(normalized.get("bins", 30)))
        except (TypeError, ValueError):
            raise ValueError("Histogram 'bins' must be a positive integer")

        column = normalized.get("column", "x")
        if column not in {"x", "y"}:
            raise ValueError("Histogram 'column' must reference 'x' or 'y'")
        normalized["column"] = column

        normalized["density"] = bool(normalized.get("density", False))
        return normalized

    def generate_gnuplot_script(
        self,
        plot_cfg: dict,
        style_cfg: StyleConfig,
        *,
        out_plot: str | None,
        out_residuals: str | None = None,
    ) -> str:
        if not out_plot:
            return ""

        datafile = plot_cfg["datafile"].replace("\\", "/")
        options = plot_cfg.get("geometry", {}).get("options", {})
        bins = int(options.get("bins", 30))
        target_col = options.get("column", "x")
        column_map = plot_cfg.get("column_map", {})
        col_index = column_map.get(target_col, 1 if target_col == "x" else 2)
        density = bool(options.get("density", False))

        base = [
            "set encoding utf8",
            (
                "set terminal pngcairo size 800,600 font "
                f"\"{_escape(style_cfg.font_family)},{style_cfg.font_size}\""
            ),
            f"set output \"{out_plot}\"",
            f"set title \"{_escape(plot_cfg['title'])}\" font \",{style_cfg.title_font_size}\"",
            f"set xlabel \"{_escape(style_cfg.axis_label_with_unit(target_col))}\"",
            "set ylabel \"Frequency\"" if not density else "set ylabel \"Density\"",
            "set style fill solid 0.6 border -1",
        ]

        base.extend(
            [
                f"stats \"{datafile}\" using {col_index} nooutput",
                f"bins = {bins}",
                "if (STATS_max == STATS_min) bins = 1",
                "bin_width = (STATS_max - STATS_min) / bins",
                "if (bin_width <= 0) bin_width = 1",
                "bin(x) = bin_width * floor((x - STATS_min) / bin_width) + STATS_min + bin_width/2.0",
                "set boxwidth bin_width * 0.9",
            ]
        )

        if density:
            base.append("norm = STATS_records * bin_width")
            using_expr = "(bin($%d)):(1.0/norm)" % col_index
        else:
            using_expr = "(bin($%d)):(1.0)" % col_index

        base.append(
            (
                f"plot \"{datafile}\" using {using_expr} smooth freq with boxes "
                f"lc rgb \"{style_cfg.line_color}\" title \"Histogram ({bins} bins)\""
            )
        )
        base.append("unset output")
        return "\n".join(base) + "\n"

    def asset_caption(self, plot_cfg: dict) -> str:
        opts = plot_cfg.get("geometry", {}).get("options", {})
        bins = opts.get("bins") or self.default_options["bins"]
        return f"Histogram ({bins} bins)"


class SurfaceGeometry(GeometryDefinition):
    def __init__(self) -> None:
        super().__init__(
            "surface",
            "3D surface",
            supports_fit=False,
            supports_residuals=False,
            dimension=3,
            default_options={"palette": "rgb 7,5,15", "view": "60,30", "pm3d": True},
        )

    def normalize_options(self, options: dict | None, *, column_map: dict) -> dict:
        if not column_map.get("z"):
            raise ValueError("Surface plots require a 'z' column in the dataset")
        normalized = super().normalize_options(options, column_map=column_map)
        view = normalized.get("view", "60,30")
        if not isinstance(view, str) or "," not in view:
            raise ValueError("Surface 'view' must be a string like '60,30'")
        normalized["view"] = view
        normalized["pm3d"] = bool(normalized.get("pm3d", True))
        palette = normalized.get("palette")
        if palette and not isinstance(palette, str):
            raise ValueError("Surface 'palette' must be a string name")
        return normalized

    def generate_gnuplot_script(
        self,
        plot_cfg: dict,
        style_cfg: StyleConfig,
        *,
        out_plot: str | None,
        out_residuals: str | None = None,
    ) -> str:
        if not out_plot:
            return ""

        column_map = plot_cfg.get("column_map", {})
        opts = plot_cfg.get("geometry", {}).get("options", {})
        x_col = column_map.get("x", 1)
        y_col = column_map.get("y", 2)
        z_col = column_map.get("z")
        palette = opts.get("palette")
        datafile = plot_cfg["datafile"].replace("\\", "/")

        lines = [
            "set encoding utf8",
            (
                "set terminal pngcairo size 960,720 font "
                f"\"{_escape(style_cfg.font_family)},{style_cfg.font_size}\""
            ),
            f"set output \"{out_plot}\"",
            f"set title \"{_escape(plot_cfg['title'])}\" font \",{style_cfg.title_font_size}\"",
            f"set xlabel \"{_escape(style_cfg.axis_label_with_unit('x'))}\"",
            f"set ylabel \"{_escape(style_cfg.axis_label_with_unit('y'))}\"",
            f"set zlabel \"{_escape(style_cfg.axis_label_with_unit('z'))}\"",
            f"set view {opts.get('view', '60,30')}",
            "set hidden3d",
        ]
        if opts.get("pm3d", True):
            lines.extend(["set pm3d at s", "set surface"])
        if palette:
            lines.append(f"set palette {palette}")

        lines.append(
            (
                f"splot \"{datafile}\" using {x_col}:{y_col}:{z_col} "
                "with pm3d title \"Surface\""
                if opts.get("pm3d", True)
                else f"splot \"{datafile}\" using {x_col}:{y_col}:{z_col} with lines title \"Surface\""
            )
        )
        lines.append("unset output")
        return "\n".join(lines) + "\n"

    def asset_caption(self, plot_cfg: dict) -> str:
        return "3D surface render"


class HeatmapGeometry(GeometryDefinition):
    def __init__(self) -> None:
        super().__init__(
            "heatmap",
            "Heatmap",
            supports_fit=False,
            supports_residuals=False,
            dimension=3,
            default_options={"palette": "rgb 7,5,15", "smooth": False},
        )

    def normalize_options(self, options: dict | None, *, column_map: dict) -> dict:
        if not column_map.get("z"):
            raise ValueError("Heatmaps require a 'z' column in the dataset")
        normalized = super().normalize_options(options, column_map=column_map)
        normalized["smooth"] = bool(normalized.get("smooth", False))
        palette = normalized.get("palette")
        if palette and not isinstance(palette, str):
            raise ValueError("Heatmap 'palette' must be a string name")
        return normalized

    def generate_gnuplot_script(
        self,
        plot_cfg: dict,
        style_cfg: StyleConfig,
        *,
        out_plot: str | None,
        out_residuals: str | None = None,
    ) -> str:
        if not out_plot:
            return ""

        column_map = plot_cfg.get("column_map", {})
        x_col = column_map.get("x", 1)
        y_col = column_map.get("y", 2)
        z_col = column_map.get("z")
        opts = plot_cfg.get("geometry", {}).get("options", {})
        palette = opts.get("palette")
        datafile = plot_cfg["datafile"].replace("\\", "/")

        lines = [
            "set encoding utf8",
            (
                "set terminal pngcairo size 900,600 font "
                f"\"{_escape(style_cfg.font_family)},{style_cfg.font_size}\""
            ),
            f"set output \"{out_plot}\"",
            f"set title \"{_escape(plot_cfg['title'])}\" font \",{style_cfg.title_font_size}\"",
            f"set xlabel \"{_escape(style_cfg.axis_label_with_unit('x'))}\"",
            f"set ylabel \"{_escape(style_cfg.axis_label_with_unit('y'))}\"",
            f"set cblabel \"{_escape(style_cfg.axis_label_with_unit('z'))}\"",
            "set view map",
            "set pm3d map",
        ]
        if palette:
            lines.append(f"set palette {palette}")
        if opts.get("smooth", False):
            lines.append("set dgrid3d 100,100 splines")

        lines.append(
            f"splot \"{datafile}\" using {x_col}:{y_col}:{z_col} with pm3d title \"Heatmap\""
        )
        lines.append("unset output")
        return "\n".join(lines) + "\n"

    def asset_caption(self, plot_cfg: dict) -> str:
        return "Heatmap intensity plot"


GEOMETRY_REGISTRY = GeometryRegistry()
GEOMETRY_REGISTRY.register(CurveGeometry())
GEOMETRY_REGISTRY.register(HistogramGeometry())
GEOMETRY_REGISTRY.register(SurfaceGeometry())
GEOMETRY_REGISTRY.register(HeatmapGeometry())
