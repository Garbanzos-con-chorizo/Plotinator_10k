"""Geometry registry and plotting strategies for Plotinator.

This module centralizes the definition of supported plot geometries.
Each geometry strategy is responsible for validating user options and
emitting gnuplot scripts (and optional auxiliary assets) tailored to the
geometry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

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
    max_value: Optional[float] = None
    choices: Optional[Iterable[Any]] = None
    help_text: str = ""


@dataclass
class GeometryScript:
    """Bundle of gnuplot commands for a geometry render."""

    main: str
    residuals: Optional[str] = None
    auxiliary: List[Tuple[str, str, str]] = field(default_factory=list)
    # (script, output_path, caption)


class GeometryStrategy:
    """Base class for geometry behaviours."""

    name: str = ""
    label: str = ""
    description: str = ""
    options: List[GeometryOption] = []
    supports_fit: bool = False
    supports_residuals: bool = False

    def validate(
        self,
        options: Optional[Mapping[str, Any]],
        *,
        data_columns: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Validate and sanitize a geometry options payload."""

        sanitized: Dict[str, Any] = {}
        payload = dict(options or {})

        for opt in self.options:
            raw = payload.get(opt.name, opt.default)
            if raw is None:
                if opt.required:
                    raise GeometryValidationError(
                        f"Missing required option '{opt.label}' for geometry '{self.label}'"
                    )
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
            except (TypeError, ValueError) as exc:
                raise GeometryValidationError(
                    f"Invalid value for option '{opt.label}': {raw!r}"
                ) from exc

            if opt.min_value is not None and value < opt.min_value:
                raise GeometryValidationError(
                    f"Option '{opt.label}' must be ≥ {opt.min_value}, got {value}"
                )
            if opt.max_value is not None and value > opt.max_value:
                raise GeometryValidationError(
                    f"Option '{opt.label}' must be ≤ {opt.max_value}, got {value}"
                )
            if opt.choices is not None and value not in opt.choices:
                raise GeometryValidationError(
                    f"Option '{opt.label}' must be one of {list(opt.choices)}, got {value}"
                )

            sanitized[opt.name] = value

        return self._post_validate(sanitized, data_columns=data_columns)

    # ------------------------------------------------------------------
    def _post_validate(
        self,
        options: Dict[str, Any],
        *,
        data_columns: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Hook for subclasses to implement extra validation rules."""

        return options

    # ------------------------------------------------------------------
    def generate_gnuplot(
        self,
        plot_cfg: Mapping[str, Any],
        out_plot: Optional[str],
        out_residuals: Optional[str] = None,
    ) -> GeometryScript:
        raise NotImplementedError

    # ------------------------------------------------------------------
    def generate_matplotlib(
        self,
        plot_cfg: Mapping[str, Any],
    ) -> Optional[str]:
        """Optional Matplotlib adapter (currently unused)."""

        return None


_REGISTRY: Dict[str, GeometryStrategy] = {}


def register_geometry(strategy: GeometryStrategy) -> None:
    key = strategy.name.lower()
    _REGISTRY[key] = strategy


def get_geometry(name: str) -> GeometryStrategy:
    try:
        return _REGISTRY[name.lower()]
    except KeyError as exc:
        raise KeyError(f"Unknown geometry '{name}'. Registered: {list(_REGISTRY)}") from exc


def list_geometries() -> List[GeometryStrategy]:
    return sorted(_REGISTRY.values(), key=lambda g: g.label.lower())


# ---------------------------------------------------------------------------
# Concrete strategies
# ---------------------------------------------------------------------------

class LineFitGeometry(GeometryStrategy):
    name = "line"
    label = "Line / Curve Fit"
    description = "Standard 2D fit with optional residuals."
    options: List[GeometryOption] = []
    supports_fit = True
    supports_residuals = True

    def generate_gnuplot(
        self,
        plot_cfg: Mapping[str, Any],
        out_plot: Optional[str],
        out_residuals: Optional[str] = None,
    ) -> GeometryScript:
        style = plot_cfg.get("style", {})
        pt = style.get("point_type", 7)
        lw = style.get("line_width", 2)
        col = style.get("line_color", "black")

        formula = plot_cfg["fit_formula"]
        params = plot_cfg["fit_params"]
        params_csv = ",".join(params)
        datafile = plot_cfg["datafile"].replace("\\", "/")
        use_err = plot_cfg.get("error_bars", False)

        overrides = plot_cfg.get("initial_params") or {}
        guesses = dict(plot_cfg.get("computed_initials", {}))
        for key, value in overrides.items():
            if key in guesses:
                guesses[key] = value

        init_lines = "\n".join([f"{p} = {guesses.get(p, 1.0)}" for p in params])
        prints = "\n".join([
            (
                f'if (exists("{p}_err")) {{ '
                f'print sprintf("PYFIT %s %0.16g %0.16g", "{p}", {p}, {p}_err) '
                f'}} else {{ '
                f'print sprintf("PYFIT %s %0.16g %0.16g", "{p}", {p}, 0.0) }}'
            )
            for p in params
        ])

        main_lines = [
            "set encoding utf8",
            "set terminal pngcairo size 800,600",
            f"set title \"{plot_cfg['title']}\"",
            "set xlabel \"X\"",
            "set ylabel \"Y\"",
            "",
            "set fit errorvariables",
            init_lines,
            "",
            f"f(x) = {formula}",
            f"fit f(x) \"{datafile}\" via {params_csv}",
            "",
            prints,
            "",
        ]

        if out_plot:
            main_lines.append(f"set output \"{out_plot}\"")
            if use_err:
                main_lines.append(
                    (
                        f"plot \"{datafile}\" using 1:2:3 with yerrorbars title \"Data ±σ\" pt {pt}, \\\n"
                        f"     f(x) title sprintf(\"{formula}\") with lines lw {lw} lc rgb \"{col}\""
                    )
                )
            else:
                main_lines.append(
                    (
                        f"plot \"{datafile}\" using 1:2 title \"Data\" with points pt {pt}, \\\n"
                        f"     f(x) title sprintf(\"{formula}\") with lines lw {lw} lc rgb \"{col}\""
                    )
                )
            main_lines.append("unset output")

        residual_script = None
        if out_residuals:
            residual_lines = [
                f"set output \"{out_residuals}\"",
                f"set title \"Residuals — {plot_cfg['title']}\"",
                "set xlabel \"X\"",
                "set ylabel \"Residual (y - f(x))\"",
                "set grid back",
                f"plot \"{datafile}\" using 1:($2 - f($1)) with points pt {pt} title \"Residuals\", \\",
                "     0 with lines notitle lc rgb \"gray\"",
                "unset output",
            ]
            residual_script = "\n".join(residual_lines)

        return GeometryScript(main="\n".join(main_lines), residuals=residual_script)


class HistogramGeometry(GeometryStrategy):
    name = "histogram"
    label = "Histogram"
    description = "1D histogram rendered with boxes."
    options = [
        GeometryOption("column", "Data column", "int", default=1, min_value=1),
        GeometryOption("bins", "Number of bins", "int", default=20, min_value=1),
    ]

    def _post_validate(
        self,
        options: Dict[str, Any],
        *,
        data_columns: Optional[int] = None,
    ) -> Dict[str, Any]:
        col = options.get("column", 1)
        if data_columns is not None and col > data_columns:
            raise GeometryValidationError(
                f"Histogram column index {col} exceeds available columns ({data_columns})"
            )
        return options

    def generate_gnuplot(
        self,
        plot_cfg: Mapping[str, Any],
        out_plot: Optional[str],
        out_residuals: Optional[str] = None,
    ) -> GeometryScript:
        if not out_plot:
            raise GeometryValidationError("Histogram geometry requires an output path")

        datafile = plot_cfg["datafile"].replace("\\", "/")
        style = plot_cfg.get("style", {})
        color = style.get("line_color", "#1f77b4")
        options = plot_cfg.get("geometry_options", {})
        column = options.get("column", 1)
        bins = options.get("bins", 20)

        main_lines = [
            "set encoding utf8",
            "set terminal pngcairo size 800,600",
            f"set title \"{plot_cfg['title']}\"",
            "set xlabel \"Value\"",
            "set ylabel \"Frequency\"",
            f"stats \"{datafile}\" using {column} name \"STATS\" nooutput",
            f"binwidth = (STATS_max - STATS_min) / {bins}",
            "if (binwidth <= 0) binwidth = 1",
            "set boxwidth binwidth",
            "set style fill solid 0.6 border -1",
            "set xtics binwidth",
            "set xrange [STATS_min:STATS_max]",
            f"set output \"{out_plot}\"",
            (
                f"plot \"{datafile}\" using (floor($${column}/binwidth)*binwidth + binwidth/2.0):(1.0) "
                f"smooth freq with boxes lc rgb \"{color}\" title \"{plot_cfg['title']}\""
            ),
            "unset output",
        ]

        return GeometryScript(main="\n".join(main_lines))


class HeatmapGeometry(GeometryStrategy):
    name = "heatmap"
    label = "Heatmap"
    description = "2D heatmap rendered with pm3d."
    options = [
        GeometryOption("x_column", "X column", "int", default=1, min_value=1),
        GeometryOption("y_column", "Y column", "int", default=2, min_value=1),
        GeometryOption("z_column", "Z column", "int", default=3, min_value=1),
    ]

    def _post_validate(
        self,
        options: Dict[str, Any],
        *,
        data_columns: Optional[int] = None,
    ) -> Dict[str, Any]:
        cols = [options.get("x_column", 1), options.get("y_column", 2), options.get("z_column", 3)]
        if data_columns is not None and any(col > data_columns for col in cols):
            raise GeometryValidationError(
                f"Heatmap columns {cols} exceed available columns ({data_columns})"
            )
        return options

    def generate_gnuplot(
        self,
        plot_cfg: Mapping[str, Any],
        out_plot: Optional[str],
        out_residuals: Optional[str] = None,
    ) -> GeometryScript:
        if not out_plot:
            raise GeometryValidationError("Heatmap geometry requires an output path")

        datafile = plot_cfg["datafile"].replace("\\", "/")
        options = plot_cfg.get("geometry_options", {})
        x_col = options.get("x_column", 1)
        y_col = options.get("y_column", 2)
        z_col = options.get("z_column", 3)

        lines = [
            "set encoding utf8",
            "set terminal pngcairo size 800,600",
            f"set title \"{plot_cfg['title']}\"",
            "set xlabel \"X\"",
            "set ylabel \"Y\"",
            "set view map",
            "set pm3d map",
            "set palette rgb 33,13,10",
            f"set output \"{out_plot}\"",
            (
                f"splot \"{datafile}\" using {x_col}:{y_col}:{z_col} with pm3d title \"{plot_cfg['title']}\""
            ),
            "unset output",
        ]

        return GeometryScript(main="\n".join(lines))


class SurfaceGeometry(GeometryStrategy):
    name = "surface"
    label = "3D Surface"
    description = "3D surface plot with auxiliary top-down heatmap."
    options = [
        GeometryOption("x_column", "X column", "int", default=1, min_value=1),
        GeometryOption("y_column", "Y column", "int", default=2, min_value=1),
        GeometryOption("z_column", "Z column", "int", default=3, min_value=1),
    ]

    def _post_validate(
        self,
        options: Dict[str, Any],
        *,
        data_columns: Optional[int] = None,
    ) -> Dict[str, Any]:
        cols = [options.get("x_column", 1), options.get("y_column", 2), options.get("z_column", 3)]
        if data_columns is not None and any(col > data_columns for col in cols):
            raise GeometryValidationError(
                f"Surface columns {cols} exceed available columns ({data_columns})"
            )
        return options

    def generate_gnuplot(
        self,
        plot_cfg: Mapping[str, Any],
        out_plot: Optional[str],
        out_residuals: Optional[str] = None,
    ) -> GeometryScript:
        if not out_plot:
            raise GeometryValidationError("Surface geometry requires an output path")

        datafile = plot_cfg["datafile"].replace("\\", "/")
        options = plot_cfg.get("geometry_options", {})
        x_col = options.get("x_column", 1)
        y_col = options.get("y_column", 2)
        z_col = options.get("z_column", 3)
        style = plot_cfg.get("style", {})
        color = style.get("line_color", "#1f77b4")

        main_lines = [
            "set encoding utf8",
            "set terminal pngcairo size 800,600",
            f"set title \"{plot_cfg['title']}\"",
            "set xlabel \"X\"",
            "set ylabel \"Y\"",
            "set zlabel \"Z\"",
            "set hidden3d",
            "set ticslevel 0",
            "set view 60, 135, 1, 1",
            f"set output \"{out_plot}\"",
            (
                f"splot \"{datafile}\" using {x_col}:{y_col}:{z_col} with lines lc rgb \"{color}\" "
                f"title \"{plot_cfg['title']}\""
            ),
            "unset output",
        ]

        base, ext = (out_plot.rsplit(".", 1) + [""])[0:2]
        aux_path = f"{base}_top.{ext or 'png'}"
        aux_lines = [
            "set encoding utf8",
            "set terminal pngcairo size 800,600",
            f"set title \"{plot_cfg['title']} — Top View\"",
            "set view map",
            "set pm3d map",
            "set palette rgb 33,13,10",
            f"set output \"{aux_path}\"",
            (
                f"splot \"{datafile}\" using {x_col}:{y_col}:{z_col} with pm3d notitle"
            ),
            "unset output",
        ]

        auxiliary = [("\n".join(aux_lines), aux_path, "Top-down heatmap projection")]
        return GeometryScript(main="\n".join(main_lines), auxiliary=auxiliary)


# Register built-in strategies
register_geometry(LineFitGeometry())
register_geometry(HistogramGeometry())
register_geometry(HeatmapGeometry())
register_geometry(SurfaceGeometry())
