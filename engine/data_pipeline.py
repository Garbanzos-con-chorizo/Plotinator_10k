from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence, Tuple

import numpy as np

__all__ = [
    "prepare_datafile",
    "apply_preprocessing",
]


def _resolve_dataset_path(
    path: str,
    *,
    plot_cfg: Mapping[str, Any],
    data_source: Mapping[str, Any] | None = None,
) -> str:
    if not path:
        return path

    path_obj = Path(path)
    if path_obj.is_absolute():
        return str(path_obj)

    data_source = data_source or {}
    project_data_root = data_source.get("project_data_root") or plot_cfg.get("project_data_root")
    project_root = data_source.get("project_root") or plot_cfg.get("project_root")
    config_base_dir = data_source.get("config_base_dir") or plot_cfg.get("config_base_dir")

    candidates: list[Path] = []

    def _add_candidate(base: Any, relative: Path) -> None:
        if not base:
            return
        try:
            base_path = Path(str(base))
        except Exception:
            return
        candidates.append(base_path / relative)

    _add_candidate(project_data_root, path_obj)
    _add_candidate(project_root, path_obj)
    _add_candidate(config_base_dir, path_obj)

    if project_root and project_data_root:
        try:
            data_root_name = Path(str(project_data_root)).name
        except Exception:
            data_root_name = None
        parts = path_obj.parts
        if data_root_name and parts and parts[0].lower() == data_root_name.lower():
            trimmed = Path(*parts[1:]) if len(parts) > 1 else None
            if trimmed and trimmed.parts:
                _add_candidate(project_root, trimmed)

    for candidate in candidates:
        if candidate.exists():
            return str(candidate.resolve())

    if candidates:
        return str(candidates[0])

    return os.path.abspath(path)


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


def _build_eval_context(data: np.ndarray) -> dict[str, np.ndarray]:
    ctx = {f"col{i+1}": data[:, i] for i in range(data.shape[1])}
    ctx.update({"np": np, "math": math})
    return ctx


def apply_preprocessing(
    data: np.ndarray, steps: Sequence[dict[str, Any]]
) -> Tuple[np.ndarray, list[dict]]:
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
            except Exception as exc:  # noqa: BLE001 - deliberate propagation with context
                raise ValueError(
                    f"Failed to evaluate filter expression '{expr}': {exc}"
                ) from exc
            mask = np.asarray(mask)
            if mask.dtype != bool:
                mask = mask.astype(bool)
            if mask.shape[0] != processed.shape[0]:
                raise ValueError(
                    "Filter expression "
                    f"'{expr}' produced mask of length {mask.shape[0]}, "
                    f"expected {processed.shape[0]}"
                )
            processed = processed[mask]
            applied.append(
                {
                    "type": "filter",
                    "expression": expr,
                    "retained_rows": int(processed.shape[0]),
                }
            )
        elif step["type"] == "transform":
            target_idx = _column_ref_to_index(step["target"])
            if target_idx >= processed.shape[1]:
                raise ValueError(
                    "Transform target column "
                    f"'{step['target']}' (index {target_idx+1}) is out of bounds"
                )
            try:
                values = eval(expr, {"np": np, "math": math}, ctx)
            except Exception as exc:  # noqa: BLE001 - deliberate propagation with context
                raise ValueError(
                    f"Failed to evaluate transform expression '{expr}': {exc}"
                ) from exc
            values = np.asarray(values)
            if values.ndim == 0:
                processed[:, target_idx] = values
            else:
                if values.shape[0] != processed.shape[0]:
                    raise ValueError(
                        "Transform expression "
                        f"'{expr}' produced {values.shape[0]} rows, "
                        f"expected {processed.shape[0]}"
                    )
                processed[:, target_idx] = values
            applied.append(
                {
                    "type": "transform",
                    "expression": expr,
                    "target": step["target"],
                }
            )
        else:
            raise ValueError(f"Unsupported preprocessing step type: {step['type']}")

        if processed.shape[0] == 0:
            raise ValueError("All rows were removed by preprocessing steps")

    return processed, applied


def prepare_datafile(plot_cfg: dict, plot_dir: str) -> dict:
    data_source = plot_cfg.get("data_source") or {}
    source_path = data_source.get("path") or plot_cfg.get("datafile")
    if source_path:
        source_path = _resolve_dataset_path(source_path, plot_cfg=plot_cfg, data_source=data_source)
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
    processed, applied = apply_preprocessing(raw_data.copy(), steps)

    os.makedirs(plot_dir, exist_ok=True)
    processed_path = os.path.join(plot_dir, "preprocessed.dat")
    np.savetxt(processed_path, processed, fmt="%.12g")

    return {
        "path": processed_path,
        "rows_before": int(raw_data.shape[0]),
        "rows_after": int(processed.shape[0]),
        "applied_steps": applied,
    }
