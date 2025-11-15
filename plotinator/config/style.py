"""Style configuration model for Plotinator plots."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar, Mapping, TypeAlias


TickEntry: TypeAlias = float | str | tuple[str, float]
TicksSpec: TypeAlias = tuple[TickEntry, ...] | float | str | None


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
    x_window: tuple[float | None, float | None] | None = None
    x_ticks: TicksSpec = None

    y_label: str = "Y"
    y_unit: str = ""
    y_scale: str = "linear"
    y_tick_format: str = ""
    y_window: tuple[float | None, float | None] | None = None
    y_ticks: TicksSpec = None

    grid: bool = True
    grid_layer: str = "back"

    legend_visible: bool = True
    legend_position: str = "top right"

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
        self.x_window = self._normalize_window(self.x_window)
        self.y_window = self._normalize_window(self.y_window)
        self.x_ticks = self._normalize_ticks(self.x_ticks)
        self.y_ticks = self._normalize_ticks(self.y_ticks)

    # ------------------------------------------------------------------
    @classmethod
    def from_dict(cls, raw: dict | None, *, fallback_color: str | None = None) -> "StyleConfig":
        if not isinstance(raw, dict):
            raw = {}
        data = {
            field.name: raw.get(field.name)
            for field in cls.__dataclass_fields__.values()
            if field.init
        }

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
            "x_window": self._window_to_serializable(self.x_window),
            "x_ticks": self._ticks_to_serializable(self.x_ticks),
            "y_label": self.y_label,
            "y_unit": self.y_unit,
            "y_scale": self.y_scale,
            "y_tick_format": self.y_tick_format,
            "y_window": self._window_to_serializable(self.y_window),
            "y_ticks": self._ticks_to_serializable(self.y_ticks),
            "grid": self.grid,
            "grid_layer": self.grid_layer,
            "legend_visible": self.legend_visible,
            "legend_position": self.legend_position,
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
        else:
            label, unit = self.y_label, self.y_unit
        label = label or ("X" if axis == "x" else "Y")
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

    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_window(
        value: tuple[float | None, float | None] | Sequence[float | None] | Mapping[str, float | None] | str | float | None,
    ) -> tuple[float | None, float | None] | None:
        if value in (None, ""):
            return None

        lo: float | None = None
        hi: float | None = None

        if isinstance(value, tuple) and len(value) == 2:
            lo, hi = value
        elif isinstance(value, Mapping):
            lo = StyleConfig._coerce_optional_float(value.get("min"))
            hi = StyleConfig._coerce_optional_float(value.get("max"))
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            seq = list(value)
            if len(seq) >= 1:
                lo = StyleConfig._coerce_optional_float(seq[0])
            if len(seq) >= 2:
                hi = StyleConfig._coerce_optional_float(seq[1])
        elif isinstance(value, str):
            parts = [part.strip() for part in value.replace("[", "").replace("]", "").split(",")]
            if len(parts) >= 1:
                lo = StyleConfig._coerce_optional_float(parts[0])
            if len(parts) >= 2:
                hi = StyleConfig._coerce_optional_float(parts[1])
        else:
            try:
                num = float(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None
            else:
                lo = num
        if lo is None and hi is None:
            return None
        return (lo, hi)

    @staticmethod
    def _coerce_optional_float(value: float | str | None) -> float | None:
        if value in (None, "", "*"):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _escape_tick_label(label: str) -> str:
        return label.replace("\\", "\\\\").replace('"', '\"')

    @staticmethod
    def _normalize_ticks(value: TicksSpec | Sequence | None) -> TicksSpec:  # type: ignore[type-var]
        if value in (None, ""):
            return None

        if isinstance(value, (int, float)):
            return float(value)

        if isinstance(value, str):
            text = value.strip()
            if not text or text.lower() in {"auto", "autofreq"}:
                return None
            try:
                return float(text)
            except ValueError:
                parts = [part.strip() for part in text.split(",") if part.strip()]
                if len(parts) > 1:
                    entries: list[TickEntry] = []
                    for part in parts:
                        try:
                            entries.append(float(part))
                        except ValueError:
                            entries.append(part)
                    return tuple(entries)
                return text

        if isinstance(value, Sequence):
            entries: list[TickEntry] = []
            for item in value:
                if isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
                    sub = list(item)
                    if not sub:
                        continue
                    label = str(sub[0])
                    position = StyleConfig._coerce_optional_float(sub[1] if len(sub) > 1 else None)
                    if position is None:
                        try:
                            position_val = float(sub[0])
                        except (TypeError, ValueError):
                            entries.append(label)
                        else:
                            entries.append(position_val)
                    else:
                        entries.append((label, position))
                else:
                    try:
                        entries.append(float(item))  # type: ignore[arg-type]
                    except (TypeError, ValueError):
                        entries.append(str(item))
            return tuple(entries)

        return None

    @staticmethod
    def _window_to_serializable(window: tuple[float | None, float | None] | None) -> list[float | None] | None:
        if window is None:
            return None
        return [window[0], window[1]]

    @staticmethod
    def _ticks_to_serializable(ticks: TicksSpec) -> list | float | str | None:
        if ticks is None:
            return None
        if isinstance(ticks, (int, float, str)):
            return ticks
        serialized: list = []
        for entry in ticks:
            if isinstance(entry, tuple) and len(entry) == 2:
                serialized.append([entry[0], entry[1]])
            else:
                serialized.append(entry)
        return serialized

    def axis_window(self, axis: str) -> tuple[float | None, float | None] | None:
        return self.x_window if axis == "x" else self.y_window

    def axis_range_clause(self, axis: str) -> str | None:
        window = self.axis_window(axis)
        if window is None:
            return None
        lo, hi = window
        lo_text = "*" if lo is None else f"{lo:g}"
        hi_text = "*" if hi is None else f"{hi:g}"
        return f"set {axis}range [{lo_text}:{hi_text}]"

    def axis_ticks_clause(self, axis: str) -> str:
        ticks = self.x_ticks if axis == "x" else self.y_ticks
        prefix = "set xtics" if axis == "x" else "set ytics"
        if ticks is None:
            return f"{prefix} autofreq"
        if isinstance(ticks, (int, float)):
            if float(ticks) == 0:
                return f"{prefix} autofreq"
            return f"{prefix} {float(ticks)}"
        if isinstance(ticks, str):
            return f"{prefix} {ticks}"
        parts: list[str] = []
        for entry in ticks:
            if isinstance(entry, tuple) and len(entry) == 2:
                label, position = entry
                escaped_label = self._escape_tick_label(str(label))
                if isinstance(position, (int, float)):
                    parts.append(f'"{escaped_label}" {position}')
                else:
                    parts.append(f'"{escaped_label}" {position}')
            elif isinstance(entry, (int, float)):
                parts.append(f"{entry}")
            else:
                parts.append(str(entry))
        return f"{prefix} ({', '.join(parts)})"

