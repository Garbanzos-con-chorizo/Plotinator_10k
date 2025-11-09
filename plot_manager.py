import subprocess
import datetime
import sys, os
import json
import re
import math
import numpy as np

from plotinator.engine.geometries import (
    GeometryValidationError,
    GeometryScript,
    get_geometry,
)

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
) -> GeometryScript:
    geometry = get_geometry(cfg.get("geometry", "line"))
    sanitized_cfg = dict(cfg)

    if geometry.supports_fit:
        datafile = os.path.abspath(cfg["datafile"]).replace("\\", "/")
        guesses = estimate_initial_params(datafile, cfg["fit_formula"], cfg["fit_params"])
        sanitized_cfg["computed_initials"] = guesses

    residual_target = out_residuals if geometry.supports_residuals else None
    return geometry.generate_gnuplot(sanitized_cfg, out_plot, residual_target)


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


def detect_data_columns(path: str) -> int:
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            return len(line.split())
    raise ValueError(f"Data file '{path}' does not contain any data rows")


def normalize_plots(cfg: dict, config_path: str) -> list[dict]:
    if isinstance(cfg.get("plots"), list):
        return cfg["plots"]

    fits = cfg.get("fits") or []
    if not isinstance(fits, list):
        raise ValueError("Config must contain a 'fits' list")

    base_dir = os.path.dirname(os.path.abspath(config_path))
    normalized: list[dict] = []
    for fit in fits:
        datafile = fit.get("datafile") or ""
        if datafile and not os.path.isabs(datafile):
            datafile = os.path.abspath(os.path.join(base_dir, datafile))
        if not datafile or not os.path.exists(datafile):
            raise FileNotFoundError(
                f"Data file not found for fit '{fit.get('title', 'Untitled')}': {datafile}"
            )

        try:
            column_count = detect_data_columns(datafile)
        except OSError as exc:
            raise FileNotFoundError(
                f"Could not read data file for fit '{fit.get('title', 'Untitled')}': {exc}"
            ) from exc

        geometry_name = (fit.get("geometry") or "line").lower()
        try:
            geometry = get_geometry(geometry_name)
        except KeyError as exc:
            raise ValueError(str(exc)) from exc

        raw_options = fit.get("geometry_options") if isinstance(fit.get("geometry_options"), dict) else {}
        try:
            geometry_options = geometry.validate(raw_options, data_columns=column_count)
        except GeometryValidationError as exc:
            raise ValueError(f"{fit.get('title', 'Untitled')}: {exc}") from exc

        if geometry.supports_fit:
            formula = fit.get("formula") or fit.get("fit_formula") or "a*x + b"
            params_dict = fit.get("parameters") if isinstance(fit.get("parameters"), dict) else {}
            params = list(params_dict.keys()) if params_dict else infer_parameters(formula)
            if not params:
                raise ValueError(f"Cannot infer parameters for formula '{formula}'")
        else:
            formula = fit.get("formula") or fit.get("fit_formula") or ""
            params_dict = {}
            params = []

        style = fit.get("style", {}).copy()
        if "color" in fit and fit["color"]:
            style.setdefault("line_color", fit["color"])
        elif "line_color" not in style:
            style["line_color"] = "#1f77b4"

        initial_params = {}
        if geometry.supports_fit:
            for key in params:
                try:
                    initial_params[key] = float(params_dict.get(key, ""))
                except (TypeError, ValueError, AttributeError):
                    continue

        residuals_requested = bool(fit.get("residuals", geometry.supports_residuals))
        if not geometry.supports_residuals:
            residuals_requested = False

        normalized.append(
            {
                "title": fit.get("title", "Untitled"),
                "fit_formula": formula,
                "datafile": datafile,
                "residuals": residuals_requested,
                "style": style,
                "fit_params": params if geometry.supports_fit else [],
                "initial_params": initial_params if geometry.supports_fit else {},
                "error_bars": bool(fit.get("error_bars", False)) if geometry.supports_fit else False,
                "geometry": geometry.name,
                "geometry_options": geometry_options,
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

    out_plot = os.path.join(plot_dir, "plot.png").replace("\\", "/")

    geometry = get_geometry(plot_cfg.get("geometry", "line"))

    residuals_path = None
    if geometry.supports_residuals and plot_cfg.get("residuals", True):
        residuals_path = os.path.join(plot_dir, "residuals.png").replace("\\", "/")

    scripts = generate_gnuplot_code(plot_cfg, out_plot, residuals_path)

    # --- Main render / fit ---
    output_text = run_gnuplot_script(scripts.main, workdir=plot_dir)
    params = parse_fit_output(output_text) if geometry.supports_fit else {}

    metrics = None
    if residuals_path and scripts.residuals and params:
        metrics = compute_residual_metrics(plot_cfg["datafile"], params, plot_cfg["fit_formula"])
        run_gnuplot_script(scripts.residuals, workdir=plot_dir)
    elif not geometry.supports_residuals:
        residuals_path = None

    auxiliary_assets: list[dict] = []
    for script, asset_path, caption in scripts.auxiliary:
        run_gnuplot_script(script, workdir=plot_dir)
        auxiliary_assets.append(
            {
                "path": asset_path.replace("\\", "/"),
                "caption": caption,
            }
        )

    # --- Package result ---
    result = {
        "title": plot_cfg["title"],
        "formula": plot_cfg.get("fit_formula", ""),
        "parameters": params,
        "metrics": metrics,
        "datafile": plot_cfg["datafile"],
        "output_plot": out_plot,
        "residuals_plot": residuals_path,
        "geometry": plot_cfg.get("geometry", "line"),
        "geometry_options": plot_cfg.get("geometry_options", {}),
        "auxiliary_assets": auxiliary_assets,
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
