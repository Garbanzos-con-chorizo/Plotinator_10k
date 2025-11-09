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


def generate_gnuplot_code(cfg: dict, out_plot: str, out_residuals: str | None = None) -> str:
    style = cfg.get("style", {})
    pt  = style.get("point_type", 7)
    lw  = style.get("line_width", 2)
    col = style.get("line_color", "black")

    formula  = cfg["fit_formula"]
    params   = cfg["fit_params"]
    params_csv = ",".join(params)
    datafile = os.path.abspath(cfg["datafile"]).replace("\\", "/")
    use_err  = cfg.get("error_bars", False)

    # Compute smart initial guesses
    guesses = estimate_initial_params(datafile, formula, params)
    init_lines = "\n".join([f"{p} = {guesses.get(p, 1.0)}" for p in params])
    prints = "\n".join([
       f'if (exists("{p}_err")) {{ '
       f'print sprintf("PYFIT %s %0.16g %0.16g", "{p}", {p}, {p}_err) '
       f'}} else {{ '
       f'print sprintf("PYFIT %s %0.16g %0.16g", "{p}", {p}, 0.0) }}'
       for p in params
    ])


    code = f"""
set encoding utf8
set terminal pngcairo size 800,600
set title "{cfg['title']}"
set xlabel "X"
set ylabel "Y"

set fit errorvariables
{init_lines}

f(x) = {formula}
fit f(x) "{datafile}" via {params_csv}

{prints}

set output "{out_plot}"
"""
    if use_err:
        code += (
            f"plot \"{datafile}\" using 1:2:3 with yerrorbars title \"Data ±σ\" pt {pt}, \\\n"
            f"     f(x) title sprintf(\"{formula}\") with lines lw {lw} lc rgb \"{col}\"\n"
        )
    else:
        code += (
            f"plot \"{datafile}\" using 1:2 title \"Data\" with points pt {pt}, \\\n"
            f"     f(x) title sprintf(\"{formula}\") with lines lw {lw} lc rgb \"{col}\"\n"
        )

    code += "unset output\n"

    # Optional residuals
    if out_residuals:
        code += f"""
set output "{out_residuals}"
set title "Residuals — {cfg['title']}"
set xlabel "X"
set ylabel "Residual (y - f(x))"
set grid back
plot "{datafile}" using 1:($2 - f($1)) with points pt {pt} title "Residuals", \\
     0 with lines notitle lc rgb "gray"
unset output
"""
    return code


# ---------- main ----------

from concurrent.futures import ThreadPoolExecutor, as_completed

def process_plot(plot_cfg: dict, base_output: str) -> dict:
    """Handle a single plot end-to-end: create folder, run fit, residuals, and metrics."""
    import os

    safe_title = plot_cfg["title"].replace(" ", "_")
    plot_dir = os.path.join(base_output, f"plot_{safe_title}")
    os.makedirs(plot_dir, exist_ok=True)

    out_plot = os.path.join(plot_dir, "plot.png").replace("\\", "/")

    # --- Main fit ---
    main_code = generate_gnuplot_code(plot_cfg, out_plot)
    output_text = run_gnuplot_script(main_code, workdir=plot_dir)
    params = parse_fit_output(output_text)

    # --- Optional residuals ---
    if params and plot_cfg.get("residuals", True):
        residuals_path = os.path.join(plot_dir, "residuals.png").replace("\\", "/")
        metrics = compute_residual_metrics(plot_cfg["datafile"], params, plot_cfg["fit_formula"])
        resid_code = generate_gnuplot_code(plot_cfg, out_plot=None, out_residuals=residuals_path)
        run_gnuplot_script(resid_code, workdir=plot_dir)
    else:
        residuals_path = None
        metrics = None

    # --- Package result ---
    result = {
        "title": plot_cfg["title"],
        "formula": plot_cfg["fit_formula"],
        "parameters": params,
        "metrics": metrics,
        "datafile": plot_cfg["datafile"],
        "output_plot": out_plot,
        "residuals_plot": residuals_path,
    }

    print(f"[OK] Finished: {plot_cfg['title']}")
    return result


def main():
    import json, datetime, os

    # Load config
    with open("config.json", "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # Base output folder
    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    base_output = os.path.abspath(os.path.join("outputs", ts))
    os.makedirs(base_output, exist_ok=True)

    print(f"[RUN] Starting batch at {ts} ({len(cfg['plots'])} plots)")

    # Run in parallel
    results = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(process_plot, plot_cfg, base_output) for plot_cfg in cfg["plots"]]
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

if __name__ == "__main__":
    main()
