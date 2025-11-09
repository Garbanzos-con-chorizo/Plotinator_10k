import subprocess
import datetime
import sys, os
import json
import re
import math
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


def _gnuplot_path(path: str | os.PathLike | None) -> str:
    """Return a gnuplot-safe path (forward slashes)."""
    if path is None:
        return ""
    return os.fspath(path).replace("\\", "/")


def _slugify(value: str, default: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value or "").strip("_")
    return cleaned.lower() or default


def generate_gnuplot_code(
    cfg: dict, out_plot: str | None, out_residuals: str | None = None
) -> str:
    style = cfg.get("style", {})
    formula = cfg["fit_formula"]
    params = cfg["fit_params"]
    params_csv = ",".join(params)
    datasets = cfg.get("datasets", [])
    if not datasets:
        raise ValueError("At least one dataset must be defined for each fit")

    dataset_lookup = {ds.get("id"): ds for ds in datasets}
    primary_dataset = dataset_lookup.get(cfg.get("fit_dataset")) or datasets[0]
    residual_dataset = dataset_lookup.get(cfg.get("residual_dataset")) or primary_dataset

    primary_path = primary_dataset["datafile"]
    primary_datafile = _gnuplot_path(primary_path)

    # Compute smart initial guesses
    guesses = estimate_initial_params(primary_path, formula, params)
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

    layout = cfg.get("layout", {})
    rows = max(1, int(layout.get("rows", 1)))
    cols = max(1, int(layout.get("columns", 1)))
    share_x = bool(layout.get("share_x", False))
    share_y = bool(layout.get("share_y", False))
    show_legend = bool(layout.get("show_legend", True))
    panes = layout.get("panes") or []
    if not panes:
        panes = [
            {
                "id": "main",
                "title": cfg["title"],
                "legend": True,
                "residuals": False,
                "show_fit": True,
            }
        ]

    pane_count = len(panes)
    max_slots = rows * cols
    if pane_count > max_slots:
        rows = math.ceil(pane_count / cols)
        max_slots = rows * cols

    width = 800 * cols
    height = 600 * rows

    code = f"""
set encoding utf8
set terminal pngcairo size {width},{height}
set fit errorvariables
{init_lines}

f(x) = {formula}
fit f(x) "{primary_datafile}" via {params_csv}

{prints}

"""

    if out_plot:
        plot_output_path = _gnuplot_path(out_plot)
        code += f"set output \"{plot_output_path}\"\n"
        code += f"set multiplot layout {rows},{cols} title \"{cfg['title']}\"\n"

        dataset_by_pane = {}
        for ds in datasets:
            pane_id = ds.get("pane")
            dataset_by_pane.setdefault(pane_id, []).append(ds)

        for idx, pane in enumerate(panes):
            pane_title = pane.get("title") or cfg["title"]
            legend_on = show_legend and pane.get("legend", True)
            show_fit_line = pane.get("show_fit", not pane.get("residuals", False))
            is_residual = pane.get("residuals", False)

            if legend_on:
                code += "set key inside\n"
            else:
                code += "unset key\n"

            if share_x and idx < (pane_count - cols):
                code += "set xlabel \"\"\nset format x \"\"\n"
            else:
                xlabel = pane.get("xlabel") or "X"
                code += f"set xlabel \"{xlabel}\"\nset format x default\n"

            if share_y and (idx % cols) != 0:
                code += "set ylabel \"\"\nset format y \"\"\n"
            else:
                ylabel = pane.get("ylabel") or "Y"
                code += f"set ylabel \"{ylabel}\"\nset format y default\n"

            code += f"set title \"{pane_title}\"\n"

            pane_id = pane.get("id")
            pane_datasets = dataset_by_pane.get(pane_id, [])
            plot_segments: list[str] = []

            if is_residual:
                if cfg.get("residuals", True):
                    res_style = residual_dataset.get("style", {})
                    pt = res_style.get("point_type", style.get("point_type", 7))
                    color = res_style.get("line_color", style.get("line_color", "black"))
                    residual_path = _gnuplot_path(residual_dataset["datafile"])
                    plot_segments.append(
                        f"\"{residual_path}\" using 1:($2 - f($1)) with points pt {pt} lc rgb \"{color}\" title \"Residuals\""
                    )
                    plot_segments.append("0 with lines notitle lc rgb \"gray\"")
                else:
                    plot_segments.append("NaN notitle")
            else:
                if not pane_datasets:
                    pane_datasets = [primary_dataset]
                for ds in pane_datasets:
                    ds_style = ds.get("style", {})
                    mode = ds_style.get("mode", "linespoints")
                    pt = ds_style.get("point_type")
                    lw = ds_style.get("line_width")
                    lc = ds_style.get("line_color", style.get("line_color", "black"))
                    ds_path = _gnuplot_path(ds["datafile"])
                    if ds.get("error_bars"):
                        segment = (
                            f"\"{ds_path}\" using 1:2:3 with yerrorbars title \"{ds.get('label', ds['id'])}\""
                        )
                    else:
                        segment = (
                            f"\"{ds_path}\" using 1:2 with {mode} title \"{ds.get('label', ds['id'])}\""
                        )
                    if lw is not None:
                        segment += f" lw {lw}"
                    if lc:
                        segment += f" lc rgb \"{lc}\""
                    if pt is not None and "points" in mode:
                        segment += f" pt {pt}"
                    plot_segments.append(segment)

                if show_fit_line:
                    lw = style.get("line_width", 2)
                    col = style.get("line_color", "black")
                    plot_segments.append(
                        f"f(x) title sprintf(\"{formula}\") with lines lw {lw} lc rgb \"{col}\""
                    )

            if plot_segments:
                code += "plot " + ", \\\n    ".join(plot_segments) + "\n"
            else:
                code += "plot NaN notitle\n"

        code += "unset multiplot\nunset output\n"

    if out_residuals:
        residual_output_path = _gnuplot_path(out_residuals)
        res_style = residual_dataset.get("style", {})
        pt = res_style.get("point_type", style.get("point_type", 7))
        code += f"""
set output "{residual_output_path}"
set title "Residuals — {cfg['title']}"
set xlabel "X"
set ylabel "Residual (y - f(x))"
set grid back
plot "{_gnuplot_path(residual_dataset['datafile'])}" using 1:($2 - f($1)) with points pt {pt} title "Residuals", \\
     0 with lines notitle lc rgb "gray"
unset output
"""

    return code


BLACKLIST = {"x", "sin", "cos", "tan", "exp", "log", "sqrt", "np", "math"}


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
    for idx, fit in enumerate(fits):
        formula = fit.get("formula") or fit.get("fit_formula") or "a*x + b"
        params_dict = fit.get("parameters") if isinstance(fit.get("parameters"), dict) else {}
        params = list(params_dict.keys()) if params_dict else infer_parameters(formula)
        if not params:
            raise ValueError(f"Cannot infer parameters for formula '{formula}'")

        style = fit.get("style", {}).copy()
        if "color" in fit and fit["color"]:
            style.setdefault("line_color", fit["color"])
        style.setdefault("line_color", "#1f77b4")
        style.setdefault("line_width", 2)
        style.setdefault("point_type", 7)

        initial_params = {}
        for key in params:
            try:
                initial_params[key] = float(params_dict.get(key, ""))
            except (TypeError, ValueError, AttributeError):
                continue

        layout_raw = fit.get("layout") if isinstance(fit.get("layout"), dict) else {}
        rows = max(1, int(layout_raw.get("rows", 1)))
        cols = max(1, int(layout_raw.get("columns", 1)))
        share_x = bool(layout_raw.get("share_x", False))
        share_y = bool(layout_raw.get("share_y", False))
        show_legend = bool(layout_raw.get("show_legend", True))
        panes_raw = layout_raw.get("panes") if isinstance(layout_raw.get("panes"), list) else []
        panes: list[dict] = []
        pane_ids: set[str] = set()
        for p_idx, pane in enumerate(panes_raw):
            if not isinstance(pane, dict):
                continue
            pane_id = _slugify(str(pane.get("id") or pane.get("name") or f"pane_{p_idx+1}"), f"pane_{p_idx+1}")
            if pane_id in pane_ids:
                pane_id = f"{pane_id}_{p_idx+1}"
            pane_ids.add(pane_id)
            panes.append(
                {
                    "id": pane_id,
                    "title": pane.get("title") or pane_id.replace("_", " ").title(),
                    "legend": bool(pane.get("legend", True)),
                    "residuals": bool(pane.get("residuals", False)),
                    "show_fit": pane.get("show_fit", not pane.get("residuals", False)),
                    "xlabel": pane.get("xlabel"),
                    "ylabel": pane.get("ylabel"),
                }
            )

        if not panes:
            panes.append(
                {
                    "id": "main",
                    "title": fit.get("title", "Untitled"),
                    "legend": True,
                    "residuals": False,
                    "show_fit": True,
                    "xlabel": "X",
                    "ylabel": "Y",
                }
            )
            pane_ids.add("main")

        if fit.get("residuals", True) and not any(p.get("residuals") for p in panes):
            panes.append(
                {
                    "id": "residuals",
                    "title": "Residuals",
                    "legend": False,
                    "residuals": True,
                    "show_fit": False,
                    "xlabel": "X",
                    "ylabel": "Residual",
                }
            )
            pane_ids.add("residuals")

        pane_slots = rows * cols
        if len(panes) > pane_slots:
            rows = math.ceil(len(panes) / cols)

        def resolve_data_path(path: str) -> str:
            if not path:
                return ""
            if not os.path.isabs(path):
                path = os.path.abspath(os.path.join(base_dir, path))
            return path

        datasets_raw = fit.get("datasets") if isinstance(fit.get("datasets"), list) else []
        datasets: list[dict] = []

        if not datasets_raw:
            single_path = resolve_data_path(fit.get("datafile", ""))
            if not single_path or not os.path.exists(single_path):
                raise FileNotFoundError(
                    f"Data file not found for fit '{fit.get('title', 'Untitled')}': {fit.get('datafile', single_path)}"
                )
            datasets_raw = [
                {
                    "id": "dataset_1",
                    "label": os.path.basename(single_path),
                    "datafile": single_path,
                    "pane": panes[0]["id"],
                    "style": {"line_color": style.get("line_color")},
                    "error_bars": bool(fit.get("error_bars", False)),
                }
            ]

        seen_dataset_ids: set[str] = set()
        missing_files: list[str] = []
        for d_idx, dataset in enumerate(datasets_raw):
            if not isinstance(dataset, dict):
                continue
            label = dataset.get("label") or dataset.get("id") or f"Dataset {d_idx+1}"
            ds_id = _slugify(str(dataset.get("id") or label or f"dataset_{d_idx+1}"), f"dataset_{d_idx+1}")
            if ds_id in seen_dataset_ids:
                ds_id = f"{ds_id}_{d_idx+1}"
            seen_dataset_ids.add(ds_id)

            raw_path = dataset.get("datafile", "")
            resolved_path = resolve_data_path(raw_path)
            if not resolved_path or not os.path.exists(resolved_path):
                missing_files.append(raw_path or resolved_path)
                continue

            pane_id = dataset.get("pane") or panes[0]["id"]
            if pane_id not in pane_ids:
                pane_id = panes[0]["id"]

            ds_style = dataset.get("style", {}) if isinstance(dataset.get("style"), dict) else {}
            ds_style = ds_style.copy()
            ds_style.setdefault("line_color", style.get("line_color", "#1f77b4"))

            datasets.append(
                {
                    "id": ds_id,
                    "label": label,
                    "datafile": resolved_path,
                    "pane": pane_id,
                    "style": ds_style,
                    "error_bars": bool(dataset.get("error_bars", False)),
                }
            )

        if missing_files:
            raise FileNotFoundError(
                f"Missing dataset files for fit '{fit.get('title', 'Untitled')}': {', '.join(missing_files)}"
            )

        if not datasets:
            raise ValueError(f"No valid datasets defined for fit '{fit.get('title', 'Untitled')}'")

        dataset_ids = {ds["id"] for ds in datasets}
        fit_dataset = fit.get("fit_dataset") or next(iter(dataset_ids))
        if fit_dataset not in dataset_ids:
            for ds in datasets:
                if ds.get("label") == fit_dataset:
                    fit_dataset = ds["id"]
                    break
            else:
                fit_dataset = next(iter(dataset_ids))

        residual_dataset = fit.get("residual_dataset") or fit_dataset
        if residual_dataset not in dataset_ids:
            for ds in datasets:
                if ds.get("label") == residual_dataset:
                    residual_dataset = ds["id"]
                    break
            else:
                residual_dataset = fit_dataset

        normalized.append(
            {
                "title": fit.get("title", f"Fit {idx+1}"),
                "fit_formula": formula,
                "residuals": bool(fit.get("residuals", True)),
                "style": style,
                "fit_params": params,
                "initial_params": initial_params,
                "datasets": datasets,
                "fit_dataset": fit_dataset,
                "residual_dataset": residual_dataset,
                "layout": {
                    "rows": rows,
                    "columns": cols,
                    "share_x": share_x,
                    "share_y": share_y,
                    "show_legend": show_legend,
                    "panes": panes,
                },
            }
        )

    return normalized


# ---------- main ----------

from concurrent.futures import ThreadPoolExecutor, as_completed

def process_plot(plot_cfg: dict, base_output: str) -> dict:
    """Handle a single plot end-to-end: create folder, run fit, residuals, and metrics."""
    import os

    safe_title = plot_cfg["title"].replace(" ", "_")
    plot_dir = os.path.join(base_output, f"plot_{safe_title}")
    os.makedirs(plot_dir, exist_ok=True)

    plot_png_path = os.path.join(plot_dir, "plot.png")
    residual_png_path = os.path.join(plot_dir, "residuals.png")

    layout = plot_cfg.get("layout", {})
    panes = layout.get("panes") or []
    has_residual_pane = any(pane.get("residuals") for pane in panes)
    residuals_requested = bool(plot_cfg.get("residuals", True))

    gnuplot_output = _gnuplot_path(plot_png_path)
    gnuplot_residual_output = (
        _gnuplot_path(residual_png_path) if residuals_requested else None
    )

    # --- Main fit ---
    main_code = generate_gnuplot_code(
        plot_cfg,
        gnuplot_output,
        gnuplot_residual_output,
    )
    output_text = run_gnuplot_script(main_code, workdir=plot_dir)
    params = parse_fit_output(output_text)

    datasets = plot_cfg.get("datasets", [])
    dataset_lookup = {ds.get("id"): ds for ds in datasets}
    fit_dataset = dataset_lookup.get(plot_cfg.get("fit_dataset")) or (datasets[0] if datasets else None)
    residual_dataset = dataset_lookup.get(plot_cfg.get("residual_dataset")) or fit_dataset

    residuals_embedded = has_residual_pane and residuals_requested
    residuals_path = residual_png_path if residuals_requested else None
    metrics = None

    if params and plot_cfg.get("residuals", True) and residual_dataset:
        metrics = compute_residual_metrics(residual_dataset["datafile"], params, plot_cfg["fit_formula"])
        residuals_embedded = True

    # --- Package result ---
    result = {
        "title": plot_cfg["title"],
        "formula": plot_cfg["fit_formula"],
        "parameters": params,
        "metrics": metrics,
        "datasets": [
            {
                "id": ds.get("id"),
                "label": ds.get("label"),
                "datafile": ds.get("datafile"),
                "pane": ds.get("pane"),
            }
            for ds in datasets
        ],
        "layout": plot_cfg.get("layout", {}),
        "fit_dataset": plot_cfg.get("fit_dataset"),
        "residual_dataset": plot_cfg.get("residual_dataset"),
        "output_plot": plot_png_path,
        "residuals_plot": residuals_path,
        "residuals_embedded": residuals_embedded,
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
