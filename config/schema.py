"""Structured configuration models and helpers for Plotinator jobs."""

from __future__ import annotations

import copy
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping

from plotinator.config.style import StyleConfig

__all__ = [
    "ConfigError",
    "PreprocessingStep",
    "ColumnMapping",
    "LayoutConfig",
    "DataSourceConfig",
    "DatasetConfig",
    "FitConfig",
    "JobSettings",
    "PlotinatorConfig",
    "infer_parameters",
    "load_config",
    "load_config_file",
]

BLACKLIST = {"x", "sin", "cos", "tan", "exp", "log", "sqrt", "np", "math"}


class ConfigError(ValueError):
    """Raised when configuration validation fails."""


# ---------------------------------------------------------------------------
# Helpers

def infer_parameters(formula: str) -> list[str]:
    tokens = re.findall(r"[A-Za-zα-ωΑ-Ω_][A-Za-z0-9α-ωΑ-Ω_]*", formula or "")
    params: list[str] = []
    for token in tokens:
        if token in BLACKLIST:
            continue
        if token not in params:
            params.append(token)
    return params


def _coerce_bool(value: Any, default: bool = False) -> bool:
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


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _ensure_positive(value: int, *, field_name: str) -> int:
    if value <= 0:
        raise ConfigError(f"{field_name} must be a positive integer (got {value!r})")
    return value


def _load_mapping(value: Any, *, context: str) -> MutableMapping[str, Any]:
    if not isinstance(value, MutableMapping):
        raise ConfigError(f"{context} must be an object")
    return dict(value)


def _apply_style_overrides(model: StyleConfig, overrides: Mapping[str, Any]) -> None:
    for key, val in overrides.items():
        if not hasattr(model, key):
            raise ConfigError(f"Unknown style field '{key}'")
        setattr(model, key, val)
    # Re-run validation hooks
    model.__post_init__()


def _read_column_count(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = re.split(r"[,\s]+", line)
                if parts:
                    return len(parts)
    except OSError as exc:  # pragma: no cover - surfaced to user
        raise ConfigError(f"Unable to read data file '{path}': {exc}") from exc
    return 0


# ---------------------------------------------------------------------------
# Data classes


@dataclass(slots=True)
class PreprocessingStep:
    type: str
    expression: str
    target: str | None = None

    @classmethod
    def from_mapping(cls, value: Any, *, context: str) -> "PreprocessingStep":
        data = _load_mapping(value, context=context)
        step_type = data.get("type")
        if step_type not in {"filter", "transform"}:
            raise ConfigError(f"{context} type must be 'filter' or 'transform'")
        expr = data.get("expression")
        if not isinstance(expr, str) or not expr.strip():
            raise ConfigError(f"{context} requires a non-empty 'expression'")
        expr = expr.strip()
        target = data.get("target")
        if step_type == "transform" and not target:
            raise ConfigError(f"{context} requires a 'target' column for transform steps")
        if target is not None:
            target = str(target)
        return cls(type=step_type, expression=expr, target=target)

    def to_dict(self) -> dict[str, Any]:
        payload = {"type": self.type, "expression": self.expression}
        if self.target is not None:
            payload["target"] = self.target
        return payload


@dataclass(slots=True)
class ColumnMapping:
    x: int = 1
    y: int = 2
    error: int | None = None
    weight: int | None = None

    @classmethod
    def from_mapping(cls, value: Any, *, context: str) -> "ColumnMapping":
        if value is None:
            value = {}
        data = _load_mapping(value, context=context)
        x = _ensure_positive(_coerce_int(data.get("x", 1), 1), field_name=f"{context}.x")
        y = _ensure_positive(_coerce_int(data.get("y", 2), 2), field_name=f"{context}.y")
        error = data.get("error")
        weight = data.get("weight")
        error_int = None if error in (None, "") else _coerce_int(error, 0)
        weight_int = None if weight in (None, "") else _coerce_int(weight, 0)
        if error_int is not None:
            _ensure_positive(error_int, field_name=f"{context}.error")
        if weight_int is not None:
            _ensure_positive(weight_int, field_name=f"{context}.weight")
        return cls(x=x, y=y, error=error_int, weight=weight_int)

    def validate_against(self, path: Path, *, context: str) -> None:
        column_count = _read_column_count(path)
        if column_count <= 0:
            raise ConfigError(f"Data file '{path}' contains no data rows")
        for label, value in {
            "x": self.x,
            "y": self.y,
            "error": self.error,
            "weight": self.weight,
        }.items():
            if value is None:
                continue
            if value > column_count:
                raise ConfigError(
                    f"Data file '{path}' does not have column {value} required for '{context}.{label}'"
                )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"x": self.x, "y": self.y}
        if self.error is not None:
            payload["error"] = self.error
        if self.weight is not None:
            payload["weight"] = self.weight
        return payload


@dataclass(slots=True)
class LayoutConfig:
    rows: int = 1
    columns: int = 1
    shared_x: bool = False
    shared_y: bool = False
    show_legend: bool = True
    legend_position: str | None = None

    @classmethod
    def from_mapping(cls, value: Any, *, context: str = "layout") -> "LayoutConfig":
        if value is None:
            value = {}
        data = _load_mapping(value, context=context)
        rows = _ensure_positive(_coerce_int(data.get("rows", 1), 1), field_name=f"{context}.rows")
        cols = _ensure_positive(_coerce_int(data.get("columns", 1), 1), field_name=f"{context}.columns")
        legend_position = data.get("legend_position")
        if legend_position is not None:
            legend_position = str(legend_position).strip() or None
        return cls(
            rows=rows,
            columns=cols,
            shared_x=_coerce_bool(data.get("shared_x"), False),
            shared_y=_coerce_bool(data.get("shared_y"), False),
            show_legend=_coerce_bool(data.get("show_legend"), True),
            legend_position=legend_position,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "rows": self.rows,
            "columns": self.columns,
            "shared_x": self.shared_x,
            "shared_y": self.shared_y,
            "show_legend": self.show_legend,
        }
        if self.legend_position:
            payload["legend_position"] = self.legend_position
        return payload


@dataclass(slots=True)
class DataSourceConfig:
    path: Path
    original_path: str
    columns: ColumnMapping = field(default_factory=ColumnMapping)
    preprocessing: list[PreprocessingStep] = field(default_factory=list)

    @classmethod
    def from_mapping(
        cls,
        value: Any,
        *,
        base_dir: Path,
        context: str,
    ) -> "DataSourceConfig":
        data = _load_mapping(value, context=context)
        raw_path = data.get("path") or data.get("datafile")
        if not raw_path:
            raise ConfigError(f"{context} requires a 'path'")
        raw_path_str = str(raw_path)
        candidate = Path(raw_path_str)
        if not candidate.is_absolute():
            candidate = (base_dir / candidate).resolve()
        if not candidate.exists():
            raise ConfigError(f"Data file not found for {context}: {raw_path_str}")
        columns = ColumnMapping.from_mapping(data.get("columns"), context=f"{context}.columns")
        columns.validate_against(candidate, context=f"{context}.columns")
        preprocessing_raw = data.get("preprocessing")
        preprocessing: list[PreprocessingStep] = []
        if preprocessing_raw is not None:
            if not isinstance(preprocessing_raw, Iterable) or isinstance(preprocessing_raw, (str, bytes, Mapping)):
                raise ConfigError(f"{context}.preprocessing must be a list")
            for idx, step in enumerate(preprocessing_raw, start=1):
                preprocessing.append(
                    PreprocessingStep.from_mapping(step, context=f"{context}.preprocessing[{idx}]")
                )
        return cls(path=candidate, original_path=raw_path_str, columns=columns, preprocessing=preprocessing)

    def to_dict(self, *, relative_to: Path | None = None) -> dict[str, Any]:
        path_value: str
        if self.original_path and not Path(self.original_path).is_absolute() and relative_to is not None:
            try:
                path_value = os.path.relpath(self.path, relative_to)
            except ValueError:
                path_value = str(self.path)
        else:
            path_value = self.original_path or str(self.path)
        payload = {
            "path": path_value,
            "columns": self.columns.to_dict(),
        }
        if self.preprocessing:
            payload["preprocessing"] = [step.to_dict() for step in self.preprocessing]
        else:
            payload["preprocessing"] = []
        return payload


@dataclass(slots=True)
class DatasetConfig:
    label: str
    data_source: DataSourceConfig
    style: StyleConfig
    style_overrides: dict[str, Any] = field(default_factory=dict)
    pane: str | None = None
    pane_index: int | None = None

    @classmethod
    def from_mapping(
        cls,
        value: Any,
        *,
        base_dir: Path,
        index: int,
        fit_title: str,
        base_style: StyleConfig,
    ) -> "DatasetConfig":
        data = _load_mapping(value, context=f"dataset #{index} for fit '{fit_title}'")
        label = str(data.get("label") or f"Dataset {index}")
        pane = data.get("pane")
        if pane is not None:
            pane = str(pane)
        pane_index_raw = data.get("pane_index")
        pane_index: int | None = None
        if pane_index_raw not in (None, ""):
            pane_index = _coerce_int(pane_index_raw, 0)
            pane_index = _ensure_positive(pane_index, field_name=f"dataset #{index}.pane_index")
        data_source_mapping = data.get("data_source") or {}
        if not isinstance(data_source_mapping, Mapping):
            raise ConfigError(
                f"dataset #{index} for fit '{fit_title}' requires a data_source object"
            )
        source = DataSourceConfig.from_mapping(
            data_source_mapping,
            base_dir=base_dir,
            context=f"dataset #{index} for fit '{fit_title}'.data_source",
        )
        overrides = data.get("style") if isinstance(data.get("style"), Mapping) else {}
        overrides = dict(overrides)
        color_override = data.get("color")
        if color_override:
            overrides.setdefault("line_color", color_override)
        style_model = copy.deepcopy(base_style)
        if overrides:
            _apply_style_overrides(style_model, overrides)
        return cls(
            label=label,
            data_source=source,
            style=style_model,
            style_overrides={k: v for k, v in overrides.items() if v is not None},
            pane=pane,
            pane_index=pane_index,
        )

    def to_dict(self, *, relative_to: Path | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "label": self.label,
            "data_source": self.data_source.to_dict(relative_to=relative_to),
        }
        if self.pane:
            payload["pane"] = self.pane
        if self.pane_index is not None:
            payload["pane_index"] = self.pane_index
        if self.style_overrides:
            payload["style"] = dict(self.style_overrides)
        return payload

    def to_engine_payload(self) -> dict[str, Any]:
        data_source_dict = {
            "path": str(self.data_source.path),
            "columns": self.data_source.columns.to_dict(),
            "preprocessing": [step.to_dict() for step in self.data_source.preprocessing],
        }
        payload: dict[str, Any] = {
            "label": self.label,
            "datafile": str(self.data_source.path),
            "column_map": self.data_source.columns.to_dict(),
            "error_bars": self.data_source.columns.error is not None,
            "style": self.style.to_dict(),
            "style_model": self.style,
            "data_source": data_source_dict,
        }
        if self.pane:
            payload["pane"] = self.pane
        if self.pane_index is not None:
            payload["pane_index"] = self.pane_index
        return payload


@dataclass(slots=True)
class JobSettings:
    output_dir: Path | None = None
    max_workers: int | None = None

    @classmethod
    def from_mapping(cls, value: Any, *, base_dir: Path) -> "JobSettings":
        if value is None:
            return cls()
        data = _load_mapping(value, context="settings")
        output_dir = data.get("output_dir")
        output_path: Path | None = None
        if output_dir:
            output_path = Path(str(output_dir))
            if not output_path.is_absolute():
                output_path = (base_dir / output_path).resolve()
        max_workers = data.get("max_workers")
        if max_workers is not None:
            max_workers = _ensure_positive(_coerce_int(max_workers, 1), field_name="settings.max_workers")
        return cls(output_dir=output_path, max_workers=max_workers)

    def to_dict(self, *, relative_to: Path | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.output_dir is not None:
            if relative_to and not self.output_dir.is_absolute():
                payload["output_dir"] = os.path.relpath(self.output_dir, relative_to)
            else:
                payload["output_dir"] = str(self.output_dir)
        if self.max_workers is not None:
            payload["max_workers"] = self.max_workers
        return payload


@dataclass(slots=True)
class FitConfig:
    title: str
    fit_formula: str
    residuals: bool
    layout: LayoutConfig
    datasets: list[DatasetConfig]
    style: StyleConfig
    style_overrides: dict[str, Any] = field(default_factory=dict)
    initial_parameters: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Any, *, base_dir: Path, base_style: StyleConfig | None = None) -> "FitConfig":
        data = _load_mapping(value, context="fit")
        title = str(data.get("title") or "Untitled")
        formula = str(data.get("formula") or data.get("fit_formula") or "a*x + b")
        residuals = _coerce_bool(data.get("residuals"), True)
        layout = LayoutConfig.from_mapping(data.get("layout"), context=f"fit '{title}'.layout")
        style_overrides = data.get("style") if isinstance(data.get("style"), Mapping) else {}
        color = data.get("color")
        overrides = dict(style_overrides)
        if color:
            overrides.setdefault("line_color", color)
        if base_style is None:
            style_model = StyleConfig.from_dict(overrides or None)
        else:
            style_model = copy.deepcopy(base_style)
            if overrides:
                _apply_style_overrides(style_model, overrides)
        datasets_raw = data.get("datasets")
        datasets: list[DatasetConfig] = []
        if isinstance(datasets_raw, Iterable) and not isinstance(datasets_raw, (str, bytes, Mapping)):
            for idx, ds_raw in enumerate(datasets_raw, start=1):
                datasets.append(
                    DatasetConfig.from_mapping(
                        ds_raw,
                        base_dir=base_dir,
                        index=idx,
                        fit_title=title,
                        base_style=style_model,
                    )
                )
        fallback_source_raw = data.get("data_source")
        if not datasets:
            if fallback_source_raw:
                source = DataSourceConfig.from_mapping(
                    fallback_source_raw,
                    base_dir=base_dir,
                    context=f"fit '{title}'.data_source",
                )
                datasets = [
                    DatasetConfig(
                        label=title or "Dataset",
                        data_source=source,
                        style=copy.deepcopy(style_model),
                        style_overrides={},
                        pane_index=1,
                    )
                ]
            else:
                raise ConfigError(f"fit '{title}' must define at least one dataset or data_source")
        params_raw = data.get("parameters")
        parameters: dict[str, float] = {}
        if isinstance(params_raw, Mapping):
            for key, value in params_raw.items():
                try:
                    parameters[str(key)] = float(value)
                except (TypeError, ValueError):
                    raise ConfigError(
                        f"Invalid numeric value for parameter '{key}' in fit '{title}'"
                    ) from None
        return cls(
            title=title,
            fit_formula=formula,
            residuals=residuals,
            layout=layout,
            datasets=datasets,
            style=style_model,
            style_overrides={k: v for k, v in overrides.items() if v is not None},
            initial_parameters=parameters,
        )

    def to_engine_payload(self) -> dict[str, Any]:
        datasets_payload = [dataset.to_engine_payload() for dataset in self.datasets]
        primary_dataset = datasets_payload[0]
        plot_payload = {
            "title": self.title,
            "fit_formula": self.fit_formula,
            "residuals": self.residuals,
            "style": self.style.to_dict(),
            "style_model": self.style,
            "layout": self.layout.to_dict(),
            "datasets": datasets_payload,
            "datafile": primary_dataset["datafile"],
            "data_source": primary_dataset.get("data_source", {}),
            "column_map": primary_dataset.get("column_map", {}),
            "error_bars": primary_dataset.get("error_bars", False),
            "fit_params": infer_parameters(self.fit_formula),
            "initial_params": dict(self.initial_parameters),
        }
        return plot_payload

    def to_dict(self, *, relative_to: Path | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "title": self.title,
            "formula": self.fit_formula,
            "residuals": self.residuals,
            "layout": self.layout.to_dict(),
            "datasets": [ds.to_dict(relative_to=relative_to) for ds in self.datasets],
        }
        if self.style_overrides:
            payload["style"] = dict(self.style_overrides)
        if "line_color" in self.style_overrides:
            payload["color"] = self.style_overrides.get("line_color")
        if self.initial_parameters:
            payload["parameters"] = dict(self.initial_parameters)
        return payload


@dataclass(slots=True)
class PlotinatorConfig:
    fits: list[FitConfig] = field(default_factory=list)
    settings: JobSettings = field(default_factory=JobSettings)
    base_path: Path = field(default_factory=lambda: Path.cwd())

    @classmethod
    def from_mapping(cls, value: Any, *, base_path: Path) -> "PlotinatorConfig":
        data = _load_mapping(value, context="config")
        settings = JobSettings.from_mapping(data.get("settings"), base_dir=base_path)
        fits_raw = data.get("fits")
        if fits_raw is None:
            raise ConfigError("Config missing required 'fits' list")
        if not isinstance(fits_raw, Iterable) or isinstance(fits_raw, (str, bytes, Mapping)):
            raise ConfigError("Config 'fits' must be a list of fit objects")
        fits: list[FitConfig] = []
        base_style = StyleConfig()
        for idx, fit_raw in enumerate(fits_raw, start=1):
            try:
                fit = FitConfig.from_mapping(fit_raw, base_dir=base_path, base_style=base_style)
            except ConfigError as exc:
                raise ConfigError(f"Error in fit #{idx}: {exc}") from exc
            fits.append(fit)
        return cls(fits=fits, settings=settings, base_path=base_path)

    def to_engine_payload(self) -> list[dict[str, Any]]:
        return [fit.to_engine_payload() for fit in self.fits]

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.settings.output_dir or self.settings.max_workers:
            payload["settings"] = self.settings.to_dict(relative_to=self.base_path)
        payload["fits"] = [fit.to_dict(relative_to=self.base_path) for fit in self.fits]
        return payload


def load_config(data: Any, *, base_path: Path) -> PlotinatorConfig:
    return PlotinatorConfig.from_mapping(data, base_path=base_path)


def _load_file(path: Path) -> Any:
    suffix = path.suffix.lower()
    try:
        with path.open("r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:  # pragma: no cover - surfaced to user
        raise ConfigError(f"Failed to read {path}: {exc}") from exc
    try:
        if suffix in {".yaml", ".yml"}:
            try:
                import yaml  # type: ignore
            except ImportError as exc:  # pragma: no cover - optional dependency
                raise ConfigError(
                    "PyYAML is required to load YAML configuration files. Install 'pyyaml' first."
                ) from exc
            return yaml.safe_load(text)  # type: ignore[no-any-return]
        return json.loads(text)
    except Exception as exc:  # noqa: BLE001 - convert to ConfigError
        raise ConfigError(f"Failed to parse configuration file {path}: {exc}") from exc


def load_config_file(path: str | os.PathLike[str]) -> PlotinatorConfig:
    file_path = Path(path)
    data = _load_file(file_path)
    base_path = file_path.parent.resolve()
    return load_config(data, base_path=base_path)
