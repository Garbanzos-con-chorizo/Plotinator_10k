from __future__ import annotations

import copy
import datetime
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict

from reports.markdown_builder import write_markdown_report
from reports.pdf_exporter import export_pdf

from config import ConfigError, JobSettings, load_config_file
from .config import normalize_plots
from .data_pipeline import prepare_datafile
from .script_builder import (
    compute_residual_metrics,
    generate_gnuplot_code,
    parse_fit_output,
)

__all__ = [
    "run_gnuplot_script",
    "process_plot",
    "run_job",
    "run_batch",
]


class _EventDispatcher:
    """Dispatch structured events to an optional callback with CLI fallbacks."""

    def __init__(self, callback: Callable[[dict[str, Any]], None] | None = None) -> None:
        self._callback = callback

    def emit(self, event_type: str, **payload: Any) -> None:
        event: dict[str, Any] = {"type": event_type}
        event.update(payload)
        if self._callback:
            self._callback(event)
        else:
            self._default_handle(event)

    def log(self, message: str) -> None:
        self.emit("log", message=message)

    @staticmethod
    def _default_handle(event: Dict[str, Any]) -> None:
        etype = event.get("type")
        if etype == "log":
            message = event.get("message", "")
            if message:
                print(message)
        elif etype == "job-start":
            ts = event.get("timestamp") or ""
            total = event.get("total") or 0
            print(f"[RUN] Starting batch at {ts} ({total} plots)")
        elif etype == "plot-start":
            print(f"[RUN] Processing: {event.get('title', 'Unknown plot')}")
        elif etype == "plot-complete":
            print(f"[OK] Finished: {event.get('title', 'Unknown plot')}")
        elif etype == "plot-error":
            print(f"[X] Error in one plot: {event.get('error')}")
        elif etype == "report-markdown-ready":
            print(f"[REPORT] Markdown saved to: {event.get('markdown_path')}")
        elif etype == "report-exported":
            fmt = event.get("format", "pdf")
            print(f"[REPORT] {fmt.upper()} exported to: {event.get('pdf_path')}")
        elif etype == "report-error":
            stage = event.get("stage", "report")
            print(f"[WARN] Report {stage} failed: {event.get('error')}")
        elif etype == "job-complete":
            results_path = event.get("results_path", "")
            if results_path:
                print(f"\n[COMPLETE] All fits complete. Results saved to:\n{results_path}")
            pdf_path = event.get("pdf_path")
            if pdf_path:
                print(f"[REPORT] PDF exported to: {pdf_path}")
        elif etype == "job-error":
            print(f"[X] {event.get('error')}")


def run_gnuplot_script(gnuplot_code: str, workdir: str) -> str:
    """Run a gnuplot script inside *workdir* and return combined stdout/stderr."""

    os.makedirs(workdir, exist_ok=True)
    script_path = os.path.join(workdir, "temp_plot.plt")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(gnuplot_code)

    result = subprocess.run(
        ["gnuplot", script_path],
        cwd=workdir,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    output = (result.stdout or "") + (result.stderr or "")

    with open(os.path.join(workdir, "log.txt"), "w", encoding="utf-8") as lf:
        lf.write(output)

    return output


def _normalize_dataset_for_processing(dataset: dict, base_plot_dir: str, index: int) -> dict:
    ds_copy = copy.deepcopy(dataset)
    dataset_dir = os.path.join(base_plot_dir, f"dataset_{index}")
    os.makedirs(dataset_dir, exist_ok=True)

    prep_cfg = {
        "data_source": ds_copy.get("data_source"),
        "datafile": ds_copy.get("datafile"),
    }
    prep_info = dict(prepare_datafile(prep_cfg, dataset_dir))
    prep_info["path"] = os.path.abspath(prep_info["path"]).replace("\\", "/")

    ds_copy["datafile"] = prep_info["path"]
    ds_copy["prepared_data"] = prep_info

    ds_data_source = copy.deepcopy(ds_copy.get("data_source", {}))
    if ds_data_source.get("path"):
        ds_data_source["path"] = os.path.abspath(ds_data_source["path"]).replace("\\", "/")
    ds_copy["data_source"] = ds_data_source

    return ds_copy


def _dataset_report_entry(dataset: dict) -> dict[str, Any]:
    prep_info = dataset.get("prepared_data", {})
    ds_data_source = dataset.get("data_source", {})
    return {
        "label": dataset.get("label"),
        "pane": dataset.get("pane"),
        "pane_index": dataset.get("pane_index"),
        "columns": dataset.get("column_map", {}),
        "style": dataset.get("style", {}),
        "data_source": ds_data_source,
        "prepared_data": prep_info,
    }


def process_plot(
    plot_cfg: dict,
    base_output: str,
    dispatcher: _EventDispatcher | None = None,
) -> dict:
    """Handle a single plot end-to-end: create folder, run fit, residuals, and metrics."""

    plot_cfg = copy.deepcopy(plot_cfg)
    if dispatcher:
        dispatcher.emit("plot-start", title=plot_cfg.get("title", "Untitled"))
    safe_title = plot_cfg["title"].replace(" ", "_")
    plot_dir = os.path.join(base_output, f"plot_{safe_title}")
    os.makedirs(plot_dir, exist_ok=True)

    out_plot = os.path.join(plot_dir, "plot.png").replace("\\", "/")

    datasets_cfg = list(plot_cfg.get("datasets") or [])
    if not datasets_cfg:
        datasets_cfg = [
            {
                "label": plot_cfg.get("title", "Dataset"),
                "datafile": plot_cfg.get("datafile"),
                "column_map": plot_cfg.get("column_map", {}),
                "error_bars": plot_cfg.get("error_bars"),
                "style_model": plot_cfg.get("style_model"),
                "style": plot_cfg.get("style"),
                "data_source": plot_cfg.get("data_source", {}),
            }
        ]

    prepared_datasets: list[dict] = []
    datasets_report: list[dict[str, Any]] = []

    for idx, dataset in enumerate(datasets_cfg, start=1):
        prepared = _normalize_dataset_for_processing(dataset, plot_dir, idx)
        prepared_datasets.append(prepared)
        datasets_report.append(_dataset_report_entry(prepared))

    plot_cfg["datasets"] = prepared_datasets
    primary_dataset = prepared_datasets[0]
    data_prep = primary_dataset.get("prepared_data", {})
    plot_cfg["datafile"] = primary_dataset["datafile"]
    plot_cfg["data_source"] = primary_dataset.get(
        "data_source", plot_cfg.get("data_source", {})
    )
    plot_cfg["column_map"] = primary_dataset.get(
        "column_map", plot_cfg.get("column_map", {})
    )

    main_code = generate_gnuplot_code(plot_cfg, out_plot)
    output_text = run_gnuplot_script(main_code, workdir=plot_dir)
    params = parse_fit_output(output_text)

    residuals_path: str | None
    metrics: dict | None
    if params and plot_cfg.get("residuals", True):
        residuals_path = os.path.join(plot_dir, "residuals.png").replace("\\", "/")
        metrics = compute_residual_metrics(
            plot_cfg["datafile"], plot_cfg.get("column_map", {}), params, plot_cfg["fit_formula"]
        )
        resid_code = generate_gnuplot_code(
            plot_cfg, out_plot=None, out_residuals=residuals_path
        )
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

    result = {
        "title": plot_cfg["title"],
        "formula": plot_cfg["fit_formula"],
        "parameters": params,
        "metrics": metrics,
        "datafile": plot_cfg["datafile"],
        "output_plot": out_plot,
        "residuals_plot": residuals_path,
        "data_source": {
            "path": os.path.abspath(
                plot_cfg.get("data_source", {}).get("path", plot_cfg["datafile"])
            ).replace("\\", "/"),
            "columns": column_map,
            "rows_before": data_prep.get("rows_before"),
            "rows_after": data_prep.get("rows_after"),
            "preprocessing": data_prep.get("applied_steps", []),
        },
        "layout": plot_cfg.get("layout", {}),
        "datasets": datasets_report,
        "canvases": {
            "combined": out_plot,
            "residuals": residuals_path,
        },
        "confidence_notes": confidence_notes,
    }

    print(f"[OK] Finished: {plot_cfg['title']}")
    return result


def run_job(
    config: dict,
    *,
    config_path: str = "config.json",
    settings: JobSettings | None = None,
    max_workers: int | None = None,
    output_dir: str | os.PathLike[str] | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Execute a batch fit job from an in-memory config definition."""

    dispatcher = _EventDispatcher(on_event)
    try:
        plots = normalize_plots(config, config_path)

        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        job_settings = settings
        if output_dir is not None:
            base_output = os.fspath(output_dir)
        elif job_settings and job_settings.output_dir is not None:
            base_output = os.fspath(job_settings.output_dir)
        else:
            base_output = os.path.abspath(os.path.join("outputs", ts))
        os.makedirs(base_output, exist_ok=True)

        worker_count: int
        if max_workers is not None:
            worker_count = int(max_workers)
        elif job_settings and job_settings.max_workers is not None:
            worker_count = int(job_settings.max_workers)
        else:
            worker_count = 4

        dispatcher.emit("job-start", timestamp=ts, total=len(plots), output_dir=base_output)

        results: list[dict[str, Any]] = []
        futures: dict[Any, dict] = {}

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            for plot_cfg in plots:
                futures[executor.submit(process_plot, plot_cfg, base_output, dispatcher)] = plot_cfg

            for future in as_completed(futures):
                plot_cfg = futures[future]
                title = plot_cfg.get("title", "Unnamed plot")
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001 - propagate with logging
                    dispatcher.emit("plot-error", title=title, error=str(exc))
                    continue
                results.append(result)

        all_results = {"timestamp": ts, "results": results}
        json_path = os.path.join(base_output, "fit_results.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(all_results, f, indent=2, ensure_ascii=False)

        markdown_path: str | None = None
        pdf_path: str | None = None

        try:
            markdown_path = str(write_markdown_report(json_path))
            dispatcher.emit(
                "report-markdown-ready",
                markdown_path=markdown_path,
            )
        except Exception as exc:  # noqa: BLE001 - surface via events only
            dispatcher.emit(
                "report-error",
                stage="markdown",
                error=str(exc),
            )
        else:
            try:
                pdf_path = str(export_pdf(markdown_path))
                dispatcher.emit(
                    "report-exported",
                    pdf_path=pdf_path,
                    format="pdf",
                )
            except Exception as exc:  # noqa: BLE001 - surface via events only
                dispatcher.emit(
                    "report-error",
                    stage="pdf",
                    error=str(exc),
                )

        dispatcher.emit(
            "job-complete",
            timestamp=ts,
            results=results,
            output_dir=base_output,
            results_path=json_path,
            markdown_path=markdown_path,
            pdf_path=pdf_path,
        )

        return {
            "timestamp": ts,
            "results": results,
            "output_dir": base_output,
            "results_path": json_path,
            "markdown_path": markdown_path,
            "pdf_path": pdf_path,
        }
    except Exception as exc:
        dispatcher.emit("job-error", error=str(exc))
        raise


def run_batch(
    config_path: str,
    *,
    max_workers: int | None = None,
    output_dir: str | os.PathLike[str] | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    try:
        job = load_config_file(config_path)
    except ConfigError as exc:
        raise RuntimeError(str(exc)) from exc

    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            config_payload = json.load(handle)
    except json.JSONDecodeError:
        config_payload = job.to_dict()

    return run_job(
        config_payload,
        config_path=config_path,
        settings=job.settings,
        max_workers=max_workers,
        output_dir=output_dir,
        on_event=on_event,
    )
