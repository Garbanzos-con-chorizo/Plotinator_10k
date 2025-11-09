"""Geometry strategy registry for Plotinator.

This module centralises geometry-specific behaviour (validation rules,
GNUplot script generation, auxiliary asset descriptors) in a way that is
extensible without touching the rest of the application.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, MutableMapping


@dataclass(frozen=True)
class GeometryOptionSpec:
    """Describe a geometry-specific option for UI and validation."""

    name: str
    label: str
    option_type: str
    default: Any
    description: str = ""
    min_value: float | None = None
    max_value: float | None = None
    choices: tuple[str, ...] | None = None


@dataclass
class AuxiliaryScript:
    """Definition of an auxiliary render to be generated for a plot."""

    output: str
    caption: str
    script: str
    kind: str = "image"
    cleanup: List[str] = field(default_factory=list)


class GeometryStrategy:
    """Base class for plot geometry strategies."""

    key: str = ""
    label: str = ""
    option_specs: tuple[GeometryOptionSpec, ...] = ()
    supports_residuals: bool = True
    uses_fit: bool = True

    def normalize_options(self, options: MutableMapping[str, Any] | None) -> Dict[str, Any]:
        opts: Dict[str, Any] = {}
        provided = options or {}
        for spec in self.option_specs:
            value = provided.get(spec.name, spec.default)
            if spec.option_type in {"int", "column"}:
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    raise ValueError(f"Option '{spec.label}' must be an integer") from None
                if spec.min_value is not None and value < spec.min_value:
                    raise ValueError(
                        f"Option '{spec.label}' must be ≥ {spec.min_value}"
                    )
                if spec.max_value is not None and value > spec.max_value:
                    raise ValueError(
                        f"Option '{spec.label}' must be ≤ {spec.max_value}"
                    )
            elif spec.option_type == "float":
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    raise ValueError(f"Option '{spec.label}' must be a number") from None
                if spec.min_value is not None and value < spec.min_value:
                    raise ValueError(
                        f"Option '{spec.label}' must be ≥ {spec.min_value}"
                    )
                if spec.max_value is not None and value > spec.max_value:
                    raise ValueError(
                        f"Option '{spec.label}' must be ≤ {spec.max_value}"
                    )
            elif spec.option_type == "bool":
                value = bool(value)
            elif spec.option_type == "choice":
                if spec.choices and str(value) not in spec.choices:
                    allowed = ", ".join(spec.choices)
                    raise ValueError(
                        f"Option '{spec.label}' must be one of: {allowed}"
                    )
                value = str(value)
            else:
                value = str(value) if value is not None else ""
            opts[spec.name] = value
        return opts

    # pylint: disable=unused-argument
    def build_primary_script(
        self,
        cfg: Dict[str, Any],
        helpers: Dict[str, Callable[..., Any]],
        *,
        out_plot: str | None,
        out_residuals: str | None,
    ) -> str:
        raise NotImplementedError

    def build_auxiliary_scripts(
        self,
        cfg: Dict[str, Any],
        helpers: Dict[str, Callable[..., Any]],
        *,
        plot_dir: str,
    ) -> List[AuxiliaryScript]:
        return []


class GeometryRegistry:
    """Simple registry to manage available geometry strategies."""

    def __init__(self) -> None:
        self._strategies: Dict[str, GeometryStrategy] = {}

    def register(self, strategy: GeometryStrategy) -> None:
        key = (strategy.key or "").lower()
        self._strategies[key] = strategy

    def get(self, key: str, *, default: str | None = None) -> GeometryStrategy:
        lookup = (key or "").lower()
        if lookup in self._strategies:
            return self._strategies[lookup]
        if default is not None:
            return self.get(default)
        raise KeyError(f"Unknown geometry '{key}'")

    def all(self) -> Iterable[GeometryStrategy]:
        return self._strategies.values()

    def choices(self) -> List[tuple[str, str]]:
        return [(strategy.key, strategy.label) for strategy in self._strategies.values()]


geometry_registry = GeometryRegistry()


# ---------------------------------------------------------------------------
# Concrete geometries


class LineGeometry(GeometryStrategy):
    key = "line"
    label = "Curve Fit"
    option_specs: tuple[GeometryOptionSpec, ...] = ()
    supports_residuals = True
    uses_fit = True

    def build_primary_script(
        self,
        cfg: Dict[str, Any],
        helpers: Dict[str, Callable[..., Any]],
        *,
        out_plot: str | None,
        out_residuals: str | None,
    ) -> str:
        datafile = helpers["abspath"](cfg["datafile"])
        params = cfg["fit_params"]
        formula = cfg["fit_formula"]
        guesses = helpers["estimate_initial_params"](datafile, formula, params)
        overrides = cfg.get("initial_params") or {}
        for key, value in overrides.items():
            if key in guesses:
                guesses[key] = value
        init_lines = "\n".join([f"{p} = {guesses.get(p, 1.0)}" for p in params])
        prints = "\n".join([
            (
                "if (exists(\"{p}_err\")) {{ "
                "print sprintf(\"PYFIT %s %0.16g %0.16g\", \"{p}\", {p}, {p}_err) "
                "}} else { print sprintf(\"PYFIT %s %0.16g %0.16g\", \"{p}\", {p}, 0.0) }"
            )
            for p in params
        ])

        style = cfg.get("style", {})
        pt = style.get("point_type", 7)
        lw = style.get("line_width", 2)
        col = style.get("line_color", "black")
        use_err = cfg.get("error_bars", False)

        code = [
            "set encoding utf8",
            "set terminal pngcairo size 800,600",
            f"set title \"{cfg['title']}\"",
            "set xlabel \"X\"",
            "set ylabel \"Y\"",
            "set fit errorvariables",
            init_lines,
            f"f(x) = {formula}",
            f"fit f(x) \"{datafile}\" via {','.join(params)}",
            prints,
        ]

        if out_plot:
            code.append(f"set output \"{out_plot}\"")
            if use_err:
                code.append(
                    (
                        f"plot \"{datafile}\" using 1:2:3 with yerrorbars title \"Data ±σ\" pt {pt}, \\",
                        f"     f(x) title sprintf(\"{formula}\") with lines lw {lw} lc rgb \"{col}\"",
                    )
                )
            else:
                code.append(
                    (
                        f"plot \"{datafile}\" using 1:2 title \"Data\" with points pt {pt}, \\",
                        f"     f(x) title sprintf(\"{formula}\") with lines lw {lw} lc rgb \"{col}\"",
                    )
                )
            code.append("unset output")

        if out_residuals:
            code.extend(
                [
                    f"set output \"{out_residuals}\"",
                    f"set title \"Residuals — {cfg['title']}\"",
                    "set xlabel \"X\"",
                    "set ylabel \"Residual (y - f(x))\"",
                    "set grid back",
                    (
                        f"plot \"{datafile}\" using 1:($2 - f($1)) with points pt {pt} title \"Residuals\", \\",
                        "     0 with lines notitle lc rgb \"gray\"",
                    ),
                    "unset output",
                ]
            )

        return "\n".join(
            part if isinstance(part, str) else "\n".join(part) for part in code
        )


class HistogramGeometry(GeometryStrategy):
    key = "histogram"
    label = "Histogram"
    option_specs = (
        GeometryOptionSpec(
            name="column",
            label="Data column",
            option_type="column",
            default=2,
            min_value=1,
            description="Column index to build histogram from (1-indexed).",
        ),
        GeometryOptionSpec(
            name="bins",
            label="Bin count",
            option_type="int",
            default=20,
            min_value=1,
            max_value=500,
            description="Number of histogram bins.",
        ),
    )
    supports_residuals = False
    uses_fit = False

    def build_primary_script(
        self,
        cfg: Dict[str, Any],
        helpers: Dict[str, Callable[..., Any]],
        *,
        out_plot: str | None,
        out_residuals: str | None,
    ) -> str:
        datafile = helpers["abspath"](cfg["datafile"])
        opts = cfg.get("geometry_options", {})
        column = opts.get("column", 2)
        bins = opts.get("bins", 20)
        style = cfg.get("style", {})
        fill = style.get("fill_color") or style.get("line_color", "#1f77b4")
        edge = style.get("line_color", "black")
        code = [
            "set encoding utf8",
            "set terminal pngcairo size 800,600",
            f"set title \"{cfg['title']} — Histogram\"",
            "set xlabel \"Value\"",
            "set ylabel \"Frequency\"",
            "set style fill solid 0.7 border line",
            "set boxwidth 0.95 relative",
            f"stats \"{datafile}\" using {column} name 'ST' nooutput",
            f"bin_width = (ST_max - ST_min) / {float(bins)}",
            "if (bin_width <= 0) bin_width = 1",
            "bin(x,width) = width * floor(x/width) + width/2.0",
        ]
        if out_plot:
            code.extend(
                [
                    f"set output \"{out_plot}\"",
                    (
                        f"plot \"{datafile}\" using (bin($${column}, bin_width)):(1.0) ",
                        "smooth freq with boxes",
                        f" lc rgb \"{fill}\"",
                        f" border lc rgb \"{edge}\"",
                        f" title \"{cfg['title']}\"",
                    ),
                    "unset output",
                ]
            )
        return "\n".join(
            part if isinstance(part, str) else "".join(part) for part in code
        )

    def build_auxiliary_scripts(
        self,
        cfg: Dict[str, Any],
        helpers: Dict[str, Callable[..., Any]],
        *,
        plot_dir: str,
    ) -> List[AuxiliaryScript]:
        datafile = helpers["abspath"](cfg["datafile"])
        opts = cfg.get("geometry_options", {})
        column = opts.get("column", 2)
        style = cfg.get("style", {})
        color = style.get("line_color", "#1f77b4")
        output = helpers["join"](plot_dir, "hist_density.png")
        script_lines = [
            "set encoding utf8",
            "set terminal pngcairo size 800,600",
            f"set output \"{output}\"",
            f"set title \"{cfg['title']} — Kernel Density\"",
            "set xlabel \"Value\"",
            "set ylabel \"Density\"",
            "set grid back",
            f"plot \"{datafile}\" using {column}:(1.0) smooth kdensity lw 2 lc rgb \"{color}\" title \"Density\"",
            "unset output",
        ]
        return [
            AuxiliaryScript(
                output=output,
                caption="Kernel density estimate",
                script="\n".join(script_lines),
            )
        ]


class HeatmapGeometry(GeometryStrategy):
    key = "heatmap"
    label = "Heatmap"
    option_specs = (
        GeometryOptionSpec(
            name="x_column",
            label="X column",
            option_type="column",
            default=1,
            min_value=1,
        ),
        GeometryOptionSpec(
            name="y_column",
            label="Y column",
            option_type="column",
            default=2,
            min_value=1,
        ),
        GeometryOptionSpec(
            name="z_column",
            label="Z column",
            option_type="column",
            default=3,
            min_value=1,
        ),
    )
    supports_residuals = False
    uses_fit = False

    def build_primary_script(
        self,
        cfg: Dict[str, Any],
        helpers: Dict[str, Callable[..., Any]],
        *,
        out_plot: str | None,
        out_residuals: str | None,
    ) -> str:
        datafile = helpers["abspath"](cfg["datafile"])
        opts = cfg.get("geometry_options", {})
        x_col = opts.get("x_column", 1)
        y_col = opts.get("y_column", 2)
        z_col = opts.get("z_column", 3)
        code = [
            "set encoding utf8",
            "set terminal pngcairo size 800,600",
            f"set title \"{cfg['title']} — Heatmap\"",
            "set view map",
            "set pm3d map",
            "set xlabel \"X\"",
            "set ylabel \"Y\"",
            "set cblabel \"Intensity\"",
        ]
        if out_plot:
            code.extend(
                [
                    f"set output \"{out_plot}\"",
                    f"splot \"{datafile}\" using {x_col}:{y_col}:{z_col} with pm3d notitle",
                    "unset output",
                ]
            )
        return "\n".join(filter(None, code))

    def build_auxiliary_scripts(
        self,
        cfg: Dict[str, Any],
        helpers: Dict[str, Callable[..., Any]],
        *,
        plot_dir: str,
    ) -> List[AuxiliaryScript]:
        datafile = helpers["abspath"](cfg["datafile"])
        opts = cfg.get("geometry_options", {})
        x_col = opts.get("x_column", 1)
        y_col = opts.get("y_column", 2)
        z_col = opts.get("z_column", 3)
        contour_output = helpers["join"](plot_dir, "heatmap_contours.png")
        contour_table = helpers["join"](plot_dir, "heatmap_contours_tmp.dat")
        script = "\n".join(
            [
                "set encoding utf8",
                "set terminal pngcairo size 800,600",
                f"set output \"{contour_output}\"",
                f"set title \"{cfg['title']} — Contours\"",
                "set view map",
                "set contour base",
                "set cntrparam levels incremental 10",
                f"set table '{contour_table}'",
                f"splot \"{datafile}\" using {x_col}:{y_col}:{z_col}",
                "unset table",
                "set nocontour",
                "set surface",
                "set pm3d map",
                f"splot \"{datafile}\" using {x_col}:{y_col}:{z_col} with pm3d notitle, \\",
                f"     '{contour_table}' with lines lc rgb 'black' notitle",
                "unset output",
            ]
        )
        return [
            AuxiliaryScript(
                output=contour_output,
                caption="Heatmap with contour overlay",
                script=script,
                cleanup=[contour_table],
            )
        ]


class SurfaceGeometry(GeometryStrategy):
    key = "surface"
    label = "3D Surface"
    option_specs = (
        GeometryOptionSpec(
            name="x_column",
            label="X column",
            option_type="column",
            default=1,
            min_value=1,
        ),
        GeometryOptionSpec(
            name="y_column",
            label="Y column",
            option_type="column",
            default=2,
            min_value=1,
        ),
        GeometryOptionSpec(
            name="z_column",
            label="Z column",
            option_type="column",
            default=3,
            min_value=1,
        ),
        GeometryOptionSpec(
            name="elevation",
            label="Elevation",
            option_type="float",
            default=55.0,
            min_value=0.0,
            max_value=90.0,
            description="3D view elevation (degrees).",
        ),
        GeometryOptionSpec(
            name="azimuth",
            label="Azimuth",
            option_type="float",
            default=120.0,
            min_value=0.0,
            max_value=360.0,
            description="3D view azimuth (degrees).",
        ),
    )
    supports_residuals = False
    uses_fit = False

    def build_primary_script(
        self,
        cfg: Dict[str, Any],
        helpers: Dict[str, Callable[..., Any]],
        *,
        out_plot: str | None,
        out_residuals: str | None,
    ) -> str:
        datafile = helpers["abspath"](cfg["datafile"])
        opts = cfg.get("geometry_options", {})
        x_col = opts.get("x_column", 1)
        y_col = opts.get("y_column", 2)
        z_col = opts.get("z_column", 3)
        elev = opts.get("elevation", 55.0)
        azim = opts.get("azimuth", 120.0)
        code = [
            "set encoding utf8",
            "set terminal pngcairo size 900,700",
            f"set title \"{cfg['title']} — Surface\"",
            f"set view {float(elev)},{float(azim)}",
            "set pm3d at s",
            "set hidden3d",
            "set xlabel \"X\"",
            "set ylabel \"Y\"",
            "set zlabel \"Z\"",
        ]
        if out_plot:
            code.extend(
                [
                    f"set output \"{out_plot}\"",
                    f"splot \"{datafile}\" using {x_col}:{y_col}:{z_col} with pm3d notitle",
                    "unset output",
                ]
            )
        return "\n".join(filter(None, code))

    def build_auxiliary_scripts(
        self,
        cfg: Dict[str, Any],
        helpers: Dict[str, Callable[..., Any]],
        *,
        plot_dir: str,
    ) -> List[AuxiliaryScript]:
        datafile = helpers["abspath"](cfg["datafile"])
        opts = cfg.get("geometry_options", {})
        x_col = opts.get("x_column", 1)
        y_col = opts.get("y_column", 2)
        z_col = opts.get("z_column", 3)
        top_output = helpers["join"](plot_dir, "surface_topdown.png")
        script = "\n".join(
            filter(
                None,
                [
                    "set encoding utf8",
                    "set terminal pngcairo size 900,700",
                    f"set output \"{top_output}\"",
                    f"set title \"{cfg['title']} — Top-down Map\"",
                    "set view map",
                    "set pm3d map",
                    "set xlabel \"X\"",
                    "set ylabel \"Y\"",
                    f"splot \"{datafile}\" using {x_col}:{y_col}:{z_col} with pm3d notitle",
                    "unset output",
                ],
            )
        )
        return [
            AuxiliaryScript(
                output=top_output,
                caption="Surface top-down heatmap",
                script=script,
            )
        ]


for strategy_cls in (LineGeometry, HistogramGeometry, HeatmapGeometry, SurfaceGeometry):
    geometry_registry.register(strategy_cls())


__all__ = [
    "geometry_registry",
    "GeometryOptionSpec",
    "AuxiliaryScript",
    "GeometryStrategy",
]
