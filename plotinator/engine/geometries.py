"""Geometry registry and plotting strategies for Plotinator.

This module centralizes the definition of supported plot geometries.
Each geometry strategy is responsible for validating user options and
emitting gnuplot scripts (and optional auxiliary assets) tailored to the
geometry.
"""

from __future__ import annotations

import os

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional

__all__ = [
    "GeometryOption",
    "GeometryScript",
    "GeometryStrategy",
    "GeometryValidationError",
    "register_geometry",
    "get_geometry",
    "list_geometries",
]


class GeometryValidationError(ValueError):
    """Raised when a geometry option payload is invalid."""


@dataclass(frozen=True)
class GeometryOption:
    """Metadata describing a geometry option exposed to the UI."""

    name: str
    label: str
    kind: str = "str"  # "str", "int", "float", "bool"
    default: Any = None
    required: bool = False
    min_value: Optional[float] = None
    description: str = ""


@dataclass
class GeometryScript:
    """Container for a gnuplot script emitted by a geometry strategy."""

    code: str
    output: Optional[str]
    kind: str = "primary"  # primary, residual, extra
    caption: Optional[str] = None
    asset_type: str = "plot"
    collect_parameters: bool = False


@dataclass
class GeometryStrategy:
    """Base class for geometry behaviours."""

    key: str
    label: str
    requires_fit: bool = True
    supports_residuals: bool = True
    options: Iterable[GeometryOption] = field(default_factory=list)

    def normalize_options(self, options: Mapping[str, Any] | None) -> Dict[str, Any]:
        """Validate and coerce option values."""

        payload: Dict[str, Any] = {}
        provided = dict(options or {})
        for opt in self.options:
            raw = provided.get(opt.name, opt.default)
            if raw is None:
                if opt.required:
                    raise GeometryValidationError(
                        f"Missing required option '{opt.name}' for geometry '{self.key}'"
                    )
                else:
                    continue

            try:
                if opt.kind == "int":
                    value = int(raw)
                elif opt.kind == "float":
                    value = float(raw)
                elif opt.kind == "bool":
                    if isinstance(raw, str):
                        value = raw.strip().lower() in {"1", "true", "yes", "on"}
                    else:
                        value = bool(raw)
                else:
                    value = str(raw)
            except (TypeError, ValueError):
                raise GeometryValidationError(
                    f"Option '{opt.name}' for geometry '{self.key}' must be a valid {opt.kind}"
                ) from None

            if opt.min_value is not None and isinstance(value, (int, float)):
                if value < opt.min_value:
                    raise GeometryValidationError(
                        f"Option '{opt.name}' for geometry '{self.key}' must be >= {opt.min_value}"
                    )

            payload[opt.name] = value

        # Carry over unknown options unchanged to allow forwards compatibility.
        for key, value in provided.items():
            if key not in payload:
                payload[key] = value

        return payload

    # --- gnuplot integration -------------------------------------------------
    def build_scripts(
        self,
        cfg: Mapping[str, Any],
        style: Mapping[str, Any],
        options: Mapping[str, Any],
        *,
        out_plot: Optional[str],
        out_residuals: Optional[str],
        plot_dir: str,
    ) -> List[GeometryScript]:
        raise NotImplementedError


# --- Registry ----------------------------------------------------------------

_GEOMETRY_REGISTRY: Dict[str, GeometryStrategy] = {}


def register_geometry(strategy: GeometryStrategy) -> None:
    key = strategy.key.lower()
    if key in _GEOMETRY_REGISTRY:
        raise ValueError(f"Geometry '{key}' is already registered")
    _GEOMETRY_REGISTRY[key] = strategy


def get_geometry(key: str) -> GeometryStrategy:
    try:
        return _GEOMETRY_REGISTRY[key.lower()]
    except KeyError:
        raise GeometryValidationError(f"Unknown geometry '{key}'") from None


def list_geometries() -> List[GeometryStrategy]:
    return list(_GEOMETRY_REGISTRY.values())


# --- Strategy implementations -------------------------------------------------

from math import ceil


def _sanitize_path(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    return path.replace("\\", "/")


class LineGeometry(GeometryStrategy):
    def __init__(self) -> None:
        super().__init__(
            key="line",
            label="Line Fit",
            requires_fit=True,
            supports_residuals=True,
            options=[
                GeometryOption(
                    name="error_bars",
                    label="Error bars",
                    kind="bool",
                    default=False,
                    description="Use column 3 of the dataset as ±σ values.",
                )
            ],
        )

    def build_scripts(
        self,
        cfg: Mapping[str, Any],
        style: Mapping[str, Any],
        options: Mapping[str, Any],
        *,
        out_plot: Optional[str],
        out_residuals: Optional[str],
        plot_dir: str,
    ) -> List[GeometryScript]:
        pt = style.get("point_type", 7)
        lw = style.get("line_width", 2)
        col = style.get("line_color", "black")

        formula = cfg["fit_formula"]
        params = cfg.get("fit_params", [])
        params_csv = ",".join(params)
        datafile = _sanitize_path(cfg["datafile"])
        use_err = bool(options.get("error_bars"))

        guesses = dict(cfg.get("initial_guesses") or {})
        if not guesses:
            guesses = {p: 1.0 for p in params}
        overrides = cfg.get("initial_params") or {}
        for key, value in overrides.items():
            if key in guesses:
                guesses[key] = value

        init_lines = "\n".join([f"{p} = {guesses.get(p, 1.0)}" for p in params])
        prints = "\n".join(
            [
                (
                    "if (exists(\"{0}_err\")) {{ "
                    "print sprintf(\"PYFIT %s %0.16g %0.16g\", \"{0}\", {0}, {0}_err) "
                    "}} else {{ "
                    "print sprintf(\"PYFIT %s %0.16g %0.16g\", \"{0}\", {0}, 0.0) }}"
                ).format(p)
                for p in params
            ]
        )

        base_header = (
            "set encoding utf8\n"
            "set terminal pngcairo size 800,600\n"
            f"set title \"{cfg['title']}\"\n"
            "set xlabel \"X\"\n"
            "set ylabel \"Y\"\n"
            "set fit errorvariables\n"
            f"{init_lines}\n\n"
            f"f(x) = {formula}\n"
            f"fit f(x) \"{datafile}\" via {params_csv}\n\n"
            f"{prints}\n\n"
        )

        scripts: List[GeometryScript] = []
        if out_plot:
            if use_err:
                plot_cmd = (
                    f"plot \"{datafile}\" using 1:2:3 with yerrorbars title \"Data ±σ\" pt {pt}, \\\n"
                    f"     f(x) title sprintf(\"{formula}\") with lines lw {lw} lc rgb \"{col}\"\n"
                )
            else:
                plot_cmd = (
                    f"plot \"{datafile}\" using 1:2 title \"Data\" with points pt {pt}, \\\n"
                    f"     f(x) title sprintf(\"{formula}\") with lines lw {lw} lc rgb \"{col}\"\n"
                )

            scripts.append(
                GeometryScript(
                    code=base_header
                    + f"set output \"{_sanitize_path(out_plot)}\"\n"
                    + plot_cmd
                    + "unset output\n",
                    output=_sanitize_path(out_plot),
                    kind="primary",
                    caption="Best-fit curve",
                    collect_parameters=True,
                )
            )

        if out_residuals and cfg.get("residuals", True):
            residual_code = (
                base_header
                + f"set output \"{_sanitize_path(out_residuals)}\"\n"
                + f"set title \"Residuals — {cfg['title']}\"\n"
                + "set xlabel \"X\"\n"
                + "set ylabel \"Residual (y - f(x))\"\n"
                + "set grid back\n"
                + (
                    f"plot \"{datafile}\" using 1:($2 - f($1)) with points pt {pt} title \"Residuals\", \\\n"
                    "     0 with lines notitle lc rgb \"gray\"\n"
                )
                + "unset output\n"
            )
            scripts.append(
                GeometryScript(
                    code=residual_code,
                    output=_sanitize_path(out_residuals),
                    kind="residual",
                    caption="Residuals",
                    asset_type="residuals",
                )
            )

        return scripts


class HistogramGeometry(GeometryStrategy):
    def __init__(self) -> None:
        super().__init__(
            key="histogram",
            label="Histogram",
            requires_fit=False,
            supports_residuals=False,
            options=[
                GeometryOption(
                    name="column",
                    label="Data column",
                    kind="int",
                    default=1,
                    min_value=1,
                ),
                GeometryOption(
                    name="bin_count",
                    label="Number of bins",
                    kind="int",
                    default=20,
                    min_value=1,
                ),
            ],
        )

    def build_scripts(
        self,
        cfg: Mapping[str, Any],
        style: Mapping[str, Any],
        options: Mapping[str, Any],
        *,
        out_plot: Optional[str],
        out_residuals: Optional[str],
        plot_dir: str,
    ) -> List[GeometryScript]:
        if not out_plot:
            return []

        col = style.get("line_color", "#1f77b4")
        column = int(options.get("column", 1))
        bin_count = int(options.get("bin_count", 20))

        datafile = _sanitize_path(cfg["datafile"])
        code = (
            "set encoding utf8\n"
            "set terminal pngcairo size 800,600\n"
            f"set title \"{cfg['title']}\"\n"
            "set xlabel \"Value\"\n"
            "set ylabel \"Frequency\"\n"
            "set style fill solid 0.6 border -1\n"
            "set boxwidth 1.0\n"
            f"bin_count = {bin_count}\n"
            f"stats \"{datafile}\" using {column} name \"S\" nooutput\n"
            "if (S_max - S_min <= 0) binwidth = 1.0\n"
            "else binwidth = (S_max - S_min) / bin_count\n"
            "if (binwidth <= 0) binwidth = 1.0\n"
            "set boxwidth binwidth\n"
            "bin(x) = binwidth * floor(x/binwidth) + binwidth/2.0\n"
            f"set output \"{_sanitize_path(out_plot)}\"\n"
            f"plot \"{datafile}\" using (bin(${column})):(1.0) smooth freq with boxes lc rgb \"{col}\" title \"Histogram\"\n"
            "unset output\n"
        )
        return [
            GeometryScript(
                code=code,
                output=_sanitize_path(out_plot),
                kind="primary",
                caption="Histogram",
                asset_type="histogram",
            )
        ]


class SurfaceGeometry(GeometryStrategy):
    def __init__(self) -> None:
        super().__init__(
            key="surface",
            label="3D Surface",
            requires_fit=False,
            supports_residuals=False,
            options=[
                GeometryOption("x_column", "X column", "int", 1, min_value=1),
                GeometryOption("y_column", "Y column", "int", 2, min_value=1),
                GeometryOption("z_column", "Z column", "int", 3, min_value=1, required=True),
                GeometryOption("grid_size", "Grid density", "int", 40, min_value=5),
                GeometryOption(
                    "produce_heatmap",
                    "Generate heatmap",
                    "bool",
                    True,
                    description="Create a top-down heatmap companion render.",
                ),
            ],
        )

    def build_scripts(
        self,
        cfg: Mapping[str, Any],
        style: Mapping[str, Any],
        options: Mapping[str, Any],
        *,
        out_plot: Optional[str],
        out_residuals: Optional[str],
        plot_dir: str,
    ) -> List[GeometryScript]:
        scripts: List[GeometryScript] = []
        datafile = _sanitize_path(cfg["datafile"])
        x_col = int(options.get("x_column", 1))
        y_col = int(options.get("y_column", 2))
        z_col = int(options.get("z_column", 3))
        grid = int(options.get("grid_size", 40))

        palette_cmd = "set palette rgb 7,5,15\n"

        if out_plot:
            code = (
                "set encoding utf8\n"
                "set terminal pngcairo size 900,700 enhanced\n"
                f"set title \"{cfg['title']} — Surface\"\n"
                "set xlabel \"X\"\n"
                "set ylabel \"Y\"\n"
                "set zlabel \"Z\"\n"
                "set pm3d depthorder\n"
                "set hidden3d\n"
                f"set dgrid3d {grid}, {grid}\n"
                + palette_cmd
                + f"set output \"{_sanitize_path(out_plot)}\"\n"
                + f"splot \"{datafile}\" using {x_col}:{y_col}:{z_col} with pm3d title \"Surface\"\n"
                + "unset output\n"
            )
            scripts.append(
                GeometryScript(
                    code=code,
                    output=_sanitize_path(out_plot),
                    kind="primary",
                    caption="3D surface render",
                    asset_type="surface",
                )
            )

        if bool(options.get("produce_heatmap", True)):
            heatmap_path = _sanitize_path(
                os.path.join(plot_dir, "surface_heatmap.png")
            )
            heatmap_code = (
                "set encoding utf8\n"
                "set terminal pngcairo size 800,600 enhanced\n"
                f"set title \"{cfg['title']} — Heatmap\"\n"
                "set view map\n"
                "set pm3d map\n"
                "set xlabel \"X\"\n"
                "set ylabel \"Y\"\n"
                + palette_cmd
                + f"set output \"{heatmap_path}\"\n"
                + f"splot \"{datafile}\" using {x_col}:{y_col}:{z_col} with pm3d notitle\n"
                + "unset output\n"
            )
            scripts.append(
                GeometryScript(
                    code=heatmap_code,
                    output=heatmap_path,
                    kind="extra",
                    caption="Surface heatmap",
                    asset_type="heatmap",
                )
            )

        return scripts


class HeatmapGeometry(GeometryStrategy):
    def __init__(self) -> None:
        super().__init__(
            key="heatmap",
            label="Heatmap",
            requires_fit=False,
            supports_residuals=False,
            options=[
                GeometryOption("x_column", "X column", "int", 1, min_value=1),
                GeometryOption("y_column", "Y column", "int", 2, min_value=1),
                GeometryOption("z_column", "Intensity column", "int", 3, min_value=1, required=True),
            ],
        )

    def build_scripts(
        self,
        cfg: Mapping[str, Any],
        style: Mapping[str, Any],
        options: Mapping[str, Any],
        *,
        out_plot: Optional[str],
        out_residuals: Optional[str],
        plot_dir: str,
    ) -> List[GeometryScript]:
        if not out_plot:
            return []

        datafile = _sanitize_path(cfg["datafile"])
        x_col = int(options.get("x_column", 1))
        y_col = int(options.get("y_column", 2))
        z_col = int(options.get("z_column", 3))

        code = (
            "set encoding utf8\n"
            "set terminal pngcairo size 800,600 enhanced\n"
            f"set title \"{cfg['title']} — Heatmap\"\n"
            "set view map\n"
            "set pm3d map\n"
            "set xlabel \"X\"\n"
            "set ylabel \"Y\"\n"
            "set cblabel \"Intensity\"\n"
            "set palette rgb 7,5,15\n"
            f"set output \"{_sanitize_path(out_plot)}\"\n"
            f"splot \"{datafile}\" using {x_col}:{y_col}:{z_col} with pm3d notitle\n"
            "unset output\n"
        )
        return [
            GeometryScript(
                code=code,
                output=_sanitize_path(out_plot),
                kind="primary",
                caption="Heatmap",
                asset_type="heatmap",
            )
        ]


# Register built-in geometries
register_geometry(LineGeometry())
register_geometry(HistogramGeometry())
register_geometry(SurfaceGeometry())
register_geometry(HeatmapGeometry())
