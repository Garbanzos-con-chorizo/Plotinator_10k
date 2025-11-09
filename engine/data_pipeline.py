from __future__ import annotations

import math
import os
from typing import Any, Sequence, Tuple

import numpy as np

__all__ = [
    "prepare_datafile",
    "apply_preprocessing",
]


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
                    f"Filter expression '{expr}' produced mask of length {mask.shape[0]}, expected {processed.shape[0]}"
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
                    f"Transform target column '{step['target']}' (index {target_idx+1}) is out of bounds"
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
                        f"Transform expression '{expr}' produced {values.shape[0]} rows, expected {processed.shape[0]}"
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
