import subprocess
import datetime
import sys, os
import json
import re
import math
import copy
import numpy as np

PYFIT_RE = re.compile(r"^PYFIT\s+([A-Za-z_]\w*)\s+([-+]?[\d\.]+(?:[eE][-+]?\d+)?)\s+([-+]?[\d\.]+(?:[eE][-+]?\d+)?)$",
                      re.MULTILINE)


# ---------- helpers ----------

def run_gnuplot_script(gnuplot_code: str, workdir: str) -> str:
    """
    Write a temp gnuplot file into workdir (UTF-8), run it there, and
    return combined stdout+stderr. Also write full output to log.txt.
    """
    script_path = os.path.join(workdir, "temp_plot.plt")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(gnuplot_code)

    result = subprocess.run(
        ["gnuplot", script_path],
        cwd=workdir,
        capture_output=True,
        text=True,
        encoding="utf-8"
    )
    output = (result.stdout or "") + (result.stderr or "")

    # keep a log for debugging
    with open(os.path.join(workdir, "log.txt"), "w", encoding="utf-8") as lf:
        lf.write(output)

    return output

def parse_fit_output(output_text: str) -> dict:
    params = {}
    for name, val, err in PYFIT_RE.findall(output_text):
        params[name] = {"value": float(val), "error": float(err)}
    return params

def compute_residual_metrics(
    datafile: str, column_map: dict, params: dict, formula: str
) -> dict:
    """
    Compute residual statistics (mean, std, RMSE) directly from data and fit parameters.
    """
    import re
    import numpy as np

    # Build f(x) safely
    # Replace parameter names with their fitted values
    expr = formula
    for name, values in params.items():
        expr = re.sub(rf'\b{name}\b', str(values["value"]), expr)

    # Load data (x, y[, dy])
    x_idx = column_map.get("x", 1) - 1
    y_idx = column_map.get("y", 2) - 1
    data = np.loadtxt(datafile, usecols=(x_idx, y_idx))
    if data.ndim == 1:
        data = data.reshape(-1, 2)
    x, y = data[:, 0], data[:, 1]

    # Evaluate fitted curve
    f = np.vectorize(lambda xx: eval(expr, {"x": xx, "math": math, "np": np}))
    yfit = f(x)
    residuals = y - yfit

    mean = float(np.mean(residuals))
    std = float(np.std(residuals))
    rmse = float(np.sqrt(np.mean(residuals**2)))

    return {"mean": mean, "std": std, "rmse": rmse}

def estimate_initial_params(datafile: str, formula: str, params: list[str]) -> dict:
    """
    Generic, model-agnostic initializer.
    Uses data magnitude and parameter index to pick stable, nonzero guesses.
    Compatible with NumPy ≥2.0 (uses np.ptp instead of ndarray.ptp).
    """
    import numpy as np

    arr = np.loadtxt(datafile, usecols=(0, 1))
    if arr.ndim == 1:
        arr = arr.reshape(-1, 2)
    x, y = arr[:, 0], arr[:, 1]

    # Magnitude scale (fallback to 1.0)
    y_abs = np.abs(y)
    scale = float(max(
        y_abs.mean() if y_abs.size else 0.0,
        np.ptp(y_abs) if y_abs.size else 0.0,
        1.0
    ))

    # Absolute floor to avoid zeros / tiny values
    floor_eps = max(1e-3, scale * 1e-6)

    guesses = {}
    # Distinct, nonzero guesses spaced across a reasonable range
    for i, p in enumerate(params, start=1):
        val = 0.5 * i * scale
        if abs(val) < floor_eps:
            val = floor_eps
        guesses[p] = float(val)

    # Final pass: ensure nothing zero/NaN/inf and no two identical guesses
    seen = set()
    bump = floor_eps
    for k in list(guesses.keys()):
        v = guesses[k]
        if not (np.isfinite(v) and abs(v) >= floor_eps):
            v = floor_eps
        while v in seen:
            v += bump
        seen.add(v)
        guesses[k] = v

    return guesses


def generate_gnuplot_code(
    cfg: dict, out_plot: str | None, out_residuals: str | None = None
) -> str:
    style = cfg.get("style", {})
    pt  = style.get("point_type", 7)
    lw  = style.get("line_width", 2)
    col = style.get("line_color", "black")

    formula  = cfg["fit_formula"]
    params   = cfg["fit_params"]
    params_csv = ",".join(params)
    datafile = os.path.abspath(cfg["datafile"]).replace("\\", "/")
    column_map = cfg.get("column_map", {})
    x_col = column_map.get("x", 1)
    y_col = column_map.get("y", 2)
    err_col = column_map.get("error")
    weight_col = column_map.get("weight")
    use_err = bool(err_col)
import numpy as np

from plotinator.config.style import StyleConfig

PYFIT_RE = re.compile(r"^PYFIT\s+([A-Za-z_]\w*)\s+([-+]?[\d\.]+(?:[eE][-+]?\d+)?)\s+([-+]?[\d\.]+(?:[eE][-+]?\d+)?)$",
                      re.MULTILINE)


# ---------- helpers ----------

def run_gnuplot_script(gnuplot_code: str, workdir: str) -> str:
    """
    Write a temp gnuplot file into workdir (UTF-8), run it there, and
    return combined stdout+stderr. Also write full output to log.txt.
    """
    script_path = os.path.join(workdir, "temp_plot.plt")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(gnuplot_code)

    result = subprocess.run(
        ["gnuplot", script_path],
        cwd=workdir,
        capture_output=True,
        text=True,
        encoding="utf-8"
    )
    output = (result.stdout or "") + (result.stderr or "")

    # keep a log for debugging
    with open(os.path.join(workdir, "log.txt"), "w", encoding="utf-8") as lf:
        lf.write(output)

    return output

def parse_fit_output(output_text: str) -> dict:
    params = {}
    for name, val, err in PYFIT_RE.findall(output_text):
        params[name] = {"value": float(val), "error": float(err)}
    return params

def compute_residual_metrics(datafile: str, params: dict, formula: str) -> dict:
    """
    Compute residual statistics (mean, std, RMSE) directly from data and fit parameters.
    """
    import re
    import numpy as np

    # Build f(x) safely
    # Replace parameter names with their fitted values
    expr = formula
    for name, values in params.items():
        expr = re.sub(rf'\b{name}\b', str(values["value"]), expr)

    # Load data (x, y[, dy])
    data = np.loadtxt(datafile, usecols=(0, 1))
    x, y = data[:, 0], data[:, 1]

    # Evaluate fitted curve
    f = np.vectorize(lambda xx: eval(expr, {"x": xx, "math": math, "np": np}))
    yfit = f(x)
    residuals = y - yfit

    mean = float(np.mean(residuals))
    std = float(np.std(residuals))
    rmse = float(np.sqrt(np.mean(residuals**2)))

    return {"mean": mean, "std": std, "rmse": rmse}

def estimate_initial_params(datafile: str, formula: str, params: list[str]) -> dict:
    """
    Generic, model-agnostic initializer.
    Uses data magnitude and parameter index to pick stable, nonzero guesses.
    Compatible with NumPy ≥2.0 (uses np.ptp instead of ndarray.ptp).
    """
    import numpy as np

    arr = np.loadtxt(datafile, usecols=(0, 1))
    if arr.ndim == 1:
        arr = arr.reshape(-1, 2)
    x, y = arr[:, 0], arr[:, 1]

    # Magnitude scale (fallback to 1.0)
    y_abs = np.abs(y)
    scale = float(max(
        y_abs.mean() if y_abs.size else 0.0,
        np.ptp(y_abs) if y_abs.size else 0.0,
        1.0
    ))

    # Absolute floor to avoid zeros / tiny values
    floor_eps = max(1e-3, scale * 1e-6)

    guesses = {}
    # Distinct, nonzero guesses spaced across a reasonable range
    for i, p in enumerate(params, start=1):
        val = 0.5 * i * scale
        if abs(val) < floor_eps:
            val = floor_eps
        guesses[p] = float(val)

    # Final pass: ensure nothing zero/NaN/inf and no two identical guesses
    seen = set()
    bump = floor_eps
    for k in list(guesses.keys()):
        v = guesses[k]
        if not (np.isfinite(v) and abs(v) >= floor_eps):
            v = floor_eps
        while v in seen:
            v += bump
        seen.add(v)
        guesses[k] = v

    return guesses


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
    use_err = cfg.get("error_bars", False)

    def _escape(text: str) -> str:
        return (text or "").replace("\\", "\\\\").replace('"', '\"')

    def _style_commands(title: str, x_label: str, y_label: str, *, force_linear_y: bool = False) -> str:
        lines: list[str] = [
            "set encoding utf8",
            f"set terminal pngcairo size 800,600 font \"{_escape(style_cfg.font_family)},{style_cfg.font_size}\"",
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

    # Compute smart initial guesses
    guesses = estimate_initial_params(datafile, formula, params)
    overrides = cfg.get("initial_params") or {}
    for key, value in overrides.items():
        if key in guesses:
            guesses[key] = value
    init_lines = "\n".join([f"{p} = {guesses.get(p, 1.0)}" for p in params])
    prints = "\n".join([
       f'if (exists("{p}_err")) {{ '
       f'print sprintf("PYFIT %s %0.16g %0.16g", "{p}", {p}, {p}_err) '
       f'}} else {{ '
       f'print sprintf("PYFIT %s %0.16g %0.16g", "{p}", {p}, 0.0) }}'
       for p in params
    ])


    code = f"""
{_style_commands(cfg['title'], style_cfg.axis_label_with_unit('x'), style_cfg.axis_label_with_unit('y'))}

set fit errorvariables
{init_lines}

f(x) = {formula}
fit f(x) "{datafile}" via {params_csv}

{prints}

"""
    if out_plot:
        code += f"set output \"{out_plot}\"\n"
        data_using = ":".join([str(x_col), str(y_col)] + ([str(err_col)] if err_col else []))
        if use_err:
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

    # Optional residuals
    if out_residuals:
        code += f"""
set output "{out_residuals}"
{_style_commands(f"Residuals — {cfg['title']}", style_cfg.axis_label_with_unit('x'), "Residual (y - f(x))", force_linear_y=True)}
plot "{datafile}" using 1:($2 - f($1)) with points pt {pt} title "Residuals", \\
     0 with lines notitle lc rgb "gray"
unset output
"""
    return code


BLACKLIST = {"x", "sin", "cos", "tan", "exp", "log", "sqrt", "np", "math"}


def _ensure_columns_dict(columns: dict | None) -> dict:
    base = {"x": 1, "y": 2, "error": None, "weight": None}
    if not isinstance(columns, dict):
        return base
    result = base.copy()
    for key in ("x", "y", "error", "weight"):
        val = columns.get(key)
        if val is None or val == "":
            result[key] = None if key in {"error", "weight"} else base[key]
            continue
        try:
            ival = int(val)
        except (TypeError, ValueError):
            raise ValueError(f"Column '{key}' must be an integer (1-based index)")
        if ival <= 0:
            raise ValueError(f"Column '{key}' must be positive (1-based index)")
        result[key] = ival
    return result


def _validate_columns_exist(path: str, column_map: dict):
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = re.split(r"[,\s]+", line.strip())
                if parts:
                    col_count = len(parts)
                    break
            else:
                col_count = 0
    except OSError as exc:
        raise FileNotFoundError(f"Unable to read data file '{path}': {exc}") from exc

    if col_count == 0:
        raise ValueError(f"Data file '{path}' contains no data rows")

    for label, col in column_map.items():
        if col is None:
            continue
        if col > col_count:
            raise ValueError(
                f"Data file '{path}' does not have column {col} required for '{label}'"
            )


def _normalize_preprocessing(raw_steps) -> list:
    if not raw_steps:
        return []
    if not isinstance(raw_steps, list):
        raise ValueError("Preprocessing steps must be a list of objects")
    normalized = []
    for step in raw_steps:
        if not isinstance(step, dict):
            raise ValueError("Each preprocessing step must be an object")
        step_type = step.get("type")
        if step_type not in {"filter", "transform"}:
            raise ValueError("Preprocessing step type must be 'filter' or 'transform'")
        expr = step.get("expression")
        if not isinstance(expr, str) or not expr.strip():
            raise ValueError("Preprocessing steps require a non-empty 'expression'")
        normalized_step = {"type": step_type, "expression": expr.strip()}
        if step_type == "transform":
            target = step.get("target")
            if target is None:
                raise ValueError("Transform steps require a 'target' column (e.g., 'col2')")
            normalized_step["target"] = str(target)
        normalized.append(normalized_step)
    return normalized


def infer_parameters(formula: str) -> list[str]:
    tokens = re.findall(r"[A-Za-zα-ωΑ-Ω_][A-Za-z0-9α-ωΑ-Ω_]*", formula or "")
    params: list[str] = []
    for token in tokens:
        if token in BLACKLIST:
            continue
        if token not in params:
            params.append(token)
    return params


def normalize_plots(cfg: dict, config_path: str) -> list[dict]:
    if isinstance(cfg.get("plots"), list):
        return cfg["plots"]

    fits = cfg.get("fits") or []
    if not isinstance(fits, list):
        raise ValueError("Config must contain a 'fits' list")

    base_dir = os.path.dirname(os.path.abspath(config_path))
    normalized: list[dict] = []
    for fit in fits:
        formula = fit.get("formula") or fit.get("fit_formula") or "a*x + b"
        params_dict = fit.get("parameters") if isinstance(fit.get("parameters"), dict) else {}
        params = list(params_dict.keys()) if params_dict else infer_parameters(formula)
        if not params:
            raise ValueError(f"Cannot infer parameters for formula '{formula}'")

        data_source = fit.get("data_source") if isinstance(fit.get("data_source"), dict) else {}
        data_path = data_source.get("path") or fit.get("datafile") or ""
        if not data_path:
            raise FileNotFoundError(
                f"Data file not specified for fit '{fit.get('title', 'Untitled')}'"
            )
        if not os.path.isabs(data_path):
            data_path = os.path.abspath(os.path.join(base_dir, data_path))
        if not os.path.exists(data_path):
            raise FileNotFoundError(
                f"Data file not found for fit '{fit.get('title', 'Untitled')}': {data_path}"
            )

        columns = _ensure_columns_dict(data_source.get("columns"))
        _validate_columns_exist(data_path, columns)

        preprocessing = _normalize_preprocessing(data_source.get("preprocessing"))

        style_cfg = StyleConfig.from_dict(fit.get("style"), fallback_color=fit.get("color"))
        if fit.get("color"):
            style_cfg.line_color = fit["color"]
        else:
            fit["color"] = style_cfg.line_color
        style = style_cfg.to_dict()

        initial_params = {}
        for key in params:
            try:
                initial_params[key] = float(params_dict.get(key, ""))
            except (TypeError, ValueError, AttributeError):
                continue

        normalized.append(
            {
                "title": fit.get("title", "Untitled"),
                "fit_formula": formula,
                "datafile": data_path,
                "residuals": bool(fit.get("residuals", True)),
                "style": style,
                "style_model": style_cfg,
                "fit_params": params,
                "initial_params": initial_params,
                "column_map": columns,
                "error_bars": bool(columns.get("error")),
                "data_source": {
                    "path": data_path,
                    "columns": columns,
                    "preprocessing": preprocessing,
                },
            }
        )

    return normalized


# ---------- main ----------

from concurrent.futures import ThreadPoolExecutor, as_completed


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


def _build_eval_context(data: np.ndarray) -> dict:
    ctx = {f"col{i+1}": data[:, i] for i in range(data.shape[1])}
    ctx.update({"np": np, "math": math})
    return ctx


def _apply_preprocessing(data: np.ndarray, steps: list[dict]) -> tuple[np.ndarray, list[dict]]:
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
            except Exception as exc:
                raise ValueError(f"Failed to evaluate filter expression '{expr}': {exc}") from exc
            mask = np.asarray(mask)
            if mask.dtype != bool:
                mask = mask.astype(bool)
            if mask.shape[0] != processed.shape[0]:
                raise ValueError(
                    f"Filter expression '{expr}' produced mask of length {mask.shape[0]}, expected {processed.shape[0]}"
                )
            processed = processed[mask]
            applied.append({"type": "filter", "expression": expr, "retained_rows": int(processed.shape[0])})
        elif step["type"] == "transform":
            target_idx = _column_ref_to_index(step["target"])
            if target_idx >= processed.shape[1]:
                raise ValueError(
                    f"Transform target column '{step['target']}' (index {target_idx+1}) is out of bounds"
                )
            try:
                values = eval(expr, {"np": np, "math": math}, ctx)
            except Exception as exc:
                raise ValueError(f"Failed to evaluate transform expression '{expr}': {exc}") from exc
            values = np.asarray(values)
            if values.ndim == 0:
                processed[:, target_idx] = values
            else:
                if values.shape[0] != processed.shape[0]:
                    raise ValueError(
                        f"Transform expression '{expr}' produced {values.shape[0]} rows, expected {processed.shape[0]}"
                    )
                processed[:, target_idx] = values
            applied.append({"type": "transform", "expression": expr, "target": step["target"]})
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
    processed, applied = _apply_preprocessing(raw_data.copy(), steps)

    processed_path = os.path.join(plot_dir, "preprocessed.dat")
    np.savetxt(processed_path, processed, fmt="%.12g")

    return {
        "path": processed_path,
        "rows_before": int(raw_data.shape[0]),
        "rows_after": int(processed.shape[0]),
        "applied_steps": applied,
    }

def process_plot(plot_cfg: dict, base_output: str) -> dict:
    """Handle a single plot end-to-end: create folder, run fit, residuals, and metrics."""
    import os

    plot_cfg = copy.deepcopy(plot_cfg)
    safe_title = plot_cfg["title"].replace(" ", "_")
    plot_dir = os.path.join(base_output, f"plot_{safe_title}")
    os.makedirs(plot_dir, exist_ok=True)

    out_plot = os.path.join(plot_dir, "plot.png").replace("\\", "/")

    data_prep = prepare_datafile(plot_cfg, plot_dir)
    plot_cfg["datafile"] = data_prep["path"]

    # --- Main fit ---
    main_code = generate_gnuplot_code(plot_cfg, out_plot)
    output_text = run_gnuplot_script(main_code, workdir=plot_dir)
    params = parse_fit_output(output_text)

    # --- Optional residuals ---
    if params and plot_cfg.get("residuals", True):
        residuals_path = os.path.join(plot_dir, "residuals.png").replace("\\", "/")
        metrics = compute_residual_metrics(
            plot_cfg["datafile"], plot_cfg.get("column_map", {}), params, plot_cfg["fit_formula"]
        )
        resid_code = generate_gnuplot_code(plot_cfg, out_plot=None, out_residuals=residuals_path)
        run_gnuplot_script(resid_code, workdir=plot_dir)
    else:
        residuals_path = None
        metrics = None

    column_map = plot_cfg.get("column_map", {})
    confidence_notes = None
    if column_map.get("error"):
        confidence_notes = f"Fit weighted by error column {column_map['error']}"
    elif column_map.get("weight"):
        confidence_notes = f"Fit weighted by column {column_map['weight']}"

    # --- Package result ---
    result = {
        "title": plot_cfg["title"],
        "formula": plot_cfg["fit_formula"],
        "parameters": params,
        "metrics": metrics,
        "datafile": plot_cfg["datafile"],
        "output_plot": out_plot,
        "residuals_plot": residuals_path,
        "data_source": {
            "path": plot_cfg.get("data_source", {}).get("path", plot_cfg["datafile"]),
            "columns": column_map,
            "rows_before": data_prep.get("rows_before"),
            "rows_after": data_prep.get("rows_after"),
            "preprocessing": data_prep.get("applied_steps", []),
        },
        "confidence_notes": confidence_notes,
    }

    print(f"[OK] Finished: {plot_cfg['title']}")
    return result


def main():
    import json, datetime, os

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.json"

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    try:
        plots = normalize_plots(cfg, config_path)
    except Exception as exc:
        print(f"[X] {exc}")
        return 1

    # Base output folder
    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    base_output = os.path.abspath(os.path.join("outputs", ts))
    os.makedirs(base_output, exist_ok=True)

    print(f"[RUN] Starting batch at {ts} ({len(plots)} plots)")

    # Run in parallel
    results = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(process_plot, plot_cfg, base_output) for plot_cfg in plots]
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                print(f"[X] Error in one plot: {e}")

    # Consolidate and save
    all_results = {"timestamp": ts, "results": results}
    json_path = os.path.join(base_output, "fit_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    print(f"\n[COMPLETE] All fits complete. Results saved to:\n{json_path}")
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
