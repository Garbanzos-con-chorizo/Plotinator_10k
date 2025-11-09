"""Style configuration model for Plotinator plots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _coerce_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _coerce_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


@dataclass(slots=True)
class StyleConfig:
    """Normalized plot styling configuration with sensible defaults."""

    VALID_SCALES: ClassVar[tuple[str, ...]] = ("linear", "log")
    VALID_GRID_LAYERS: ClassVar[tuple[str, ...]] = ("front", "back")
    VALID_LEGEND_POSITIONS: ClassVar[dict[str, str]] = {
        "best": "default",
        "top left": "top left",
        "top right": "top right",
        "bottom left": "bottom left",
        "bottom right": "bottom right",
        "center": "center",
        "outside right": "right outside",
        "outside left": "left outside",
    }

    x_label: str = "X"
    x_unit: str = ""
    x_scale: str = "linear"
    x_tick_format: str = ""

    y_label: str = "Y"
    y_unit: str = ""
    y_scale: str = "linear"
    y_tick_format: str = ""

    grid: bool = True
    grid_layer: str = "back"

    legend_visible: bool = True
    legend_position: str = "top right"

    z_label: str = "Z"
    z_unit: str = ""

    font_family: str = "Segoe UI"
    font_size: int = 11
    title_font_size: int = 16
    axis_label_font_size: int = 13
    tick_font_size: int = 11

    line_color: str = "#1f77b4"
    line_width: float = 2.0
    point_type: int = 7

    def __post_init__(self) -> None:
        self.x_scale = self._validate_scale(self.x_scale)
        self.y_scale = self._validate_scale(self.y_scale)
        self.grid_layer = self._validate_grid_layer(self.grid_layer)
        self.legend_position = self._validate_legend_position(self.legend_position)
        self.font_size = _coerce_int(self.font_size, 11)
        self.title_font_size = _coerce_int(self.title_font_size, 16)
        self.axis_label_font_size = _coerce_int(self.axis_label_font_size, 13)
        self.tick_font_size = _coerce_int(self.tick_font_size, 11)
        self.line_width = _coerce_float(self.line_width, 2.0)
        self.point_type = _coerce_int(self.point_type, 7)
        self.grid = _coerce_bool(self.grid)
        self.legend_visible = _coerce_bool(self.legend_visible)

    # ------------------------------------------------------------------
    @classmethod
    def from_dict(cls, raw: dict | None, *, fallback_color: str | None = None) -> "StyleConfig":
        if not isinstance(raw, dict):
            raw = {}
        data = {field.name: raw.get(field.name) for field in cls.__dataclass_fields__.values() if field.init}

        if fallback_color and not data.get("line_color"):
            data["line_color"] = fallback_color

        clean = {k: v for k, v in data.items() if v is not None}
        return cls(**clean)

    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "x_label": self.x_label,
            "x_unit": self.x_unit,
            "x_scale": self.x_scale,
            "x_tick_format": self.x_tick_format,
            "y_label": self.y_label,
            "y_unit": self.y_unit,
            "y_scale": self.y_scale,
            "y_tick_format": self.y_tick_format,
            "grid": self.grid,
            "grid_layer": self.grid_layer,
            "legend_visible": self.legend_visible,
            "legend_position": self.legend_position,
            "z_label": self.z_label,
            "z_unit": self.z_unit,
            "font_family": self.font_family,
            "font_size": self.font_size,
            "title_font_size": self.title_font_size,
            "axis_label_font_size": self.axis_label_font_size,
            "tick_font_size": self.tick_font_size,
            "line_color": self.line_color,
            "line_width": self.line_width,
            "point_type": self.point_type,
        }

    # ------------------------------------------------------------------
    def axis_label_with_unit(self, axis: str) -> str:
        if axis == "x":
            label, unit = self.x_label, self.x_unit
            fallback = "X"
        elif axis == "y":
            label, unit = self.y_label, self.y_unit
            fallback = "Y"
        else:
            label, unit = self.z_label, self.z_unit
            fallback = "Z"
        label = label or fallback
        if unit:
            return f"{label} [{unit}]"
        return label

    # ------------------------------------------------------------------
    @classmethod
    def _validate_scale(cls, value: str | None) -> str:
        if isinstance(value, str) and value.lower() in cls.VALID_SCALES:
            return value.lower()
        return "linear"

    @classmethod
    def _validate_grid_layer(cls, value: str | None) -> str:
        if isinstance(value, str) and value.lower() in cls.VALID_GRID_LAYERS:
            return value.lower()
        return "back"

    @classmethod
    def _validate_legend_position(cls, value: str | None) -> str:
        if isinstance(value, str):
            key = value.strip().lower()
            for option in cls.VALID_LEGEND_POSITIONS:
                if key == option:
                    return option
        return "top right"

    def legend_gnuplot_clause(self) -> str:
        mapped = self.VALID_LEGEND_POSITIONS.get(self.legend_position, "top right")
        if mapped == "default":
            return "set key"
        return f"set key {mapped}"

