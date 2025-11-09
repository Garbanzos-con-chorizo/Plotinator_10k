from __future__ import annotations

import copy
import json
import os
import queue
import threading
import tkinter as tk
from typing import Any
from pathlib import Path
from tkinter import filedialog, messagebox

import ttkbootstrap as ttkb
from ttkbootstrap.constants import *

from engine import run_job

CONFIG_PATH = "config.json"


class PlotinatorApp(ttkb.Window):
    """Simple desktop helper for editing Plotinator config files."""

    def __init__(self) -> None:
        super().__init__(themename="superhero")
        self.title("Plotinator 100000")
        self.geometry("1200x800")
        self.resizable(True, True)

        self.style = ttkb.Style()
        self.folder: Path | None = None
        self.config_data: dict = {"fits": []}
        self.runner_thread: threading.Thread | None = None
        self._event_queue: queue.Queue[dict[str, Any]] | None = None
        self._progress_total = 0
        self._progress_completed = 0

        self._create_widgets()
        self.tree.bind("<Double-1>", self.on_double_click)
        self.load_config()

    # ------------------------------------------------------------------
    def _create_widgets(self) -> None:
        header = ttkb.Frame(self, padding=10)
        header.pack(fill="x")
        ttkb.Label(header, text="⚙️ Plotinator 100000", font=("Segoe UI", 22, "bold")).pack(side="left")
        ttkb.Button(header, text="🌓", width=3, command=self.toggle_theme).pack(side="right", padx=8)

        toolbar = ttkb.Frame(self, padding=10)
        toolbar.pack(fill="x")
        for text, cmd, style in [
            ("📂 Data Folder", self.select_folder, "info-outline"),
            ("➕ Add Fit", self.add_fit, "success-outline"),
            ("🗑 Delete Fit", self.delete_fit, "danger-outline"),
            ("💾 Save Config", self.save_config, "secondary-outline"),
            ("🚀 Run Batch", self.run_batch, "success"),
            ("📘 Open Report", self.open_latest_report, "primary-outline"),
        ]:
            ttkb.Button(toolbar, text=text, command=cmd, bootstyle=style).pack(side="left", padx=4)

        table_frame = ttkb.Frame(self, padding=10)
        table_frame.pack(fill="both", expand=True)
        columns = ("Title", "Formula", "Datasets", "Residuals")
        self.tree = ttkb.Treeview(table_frame, columns=columns, show="headings", height=12, bootstyle="info")
        for col, width in zip(columns, (200, 260, 220, 80)):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True)

        progress_frame = ttkb.Frame(self, padding=(10, 0))
        progress_frame.pack(fill="x")
        self.progress = ttkb.Progressbar(progress_frame, mode="determinate", bootstyle="info-striped")
        self.progress.pack(fill="x")

        log_frame = ttkb.Labelframe(self, text="Batch log", padding=10)
        log_frame.pack(fill="both", expand=True, padx=10, pady=10)
        self.log_text = tk.Text(log_frame, height=10, bg="#101820", fg="#39FF14", insertbackground="#39FF14")
        self.log_text.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    def toggle_theme(self) -> None:
        current = self.style.theme.name
        new_theme = "flatly" if current == "superhero" else "superhero"
        self.style.theme_use(new_theme)
        self.show_toast(f"Theme switched to {new_theme.title()}")

    # ------------------------------------------------------------------
    def load_config(self) -> None:
        if not os.path.exists(CONFIG_PATH):
            self.config_data = {"fits": []}
            self.save_config()
            self.refresh_table()
            return

        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("Config error", f"Could not read config.json:\n{exc}")
            self.config_data = {"fits": []}
            return

        fits = raw.get("fits") if isinstance(raw, dict) else None
        if not isinstance(fits, list):
            messagebox.showwarning("Config warning", "config.json missing 'fits' list; starting empty")
            fits = []
        self.config_data = {"fits": fits}
        for fit in self.config_data["fits"]:
            self._ensure_fit_defaults(fit)
        self.refresh_table()

    # ------------------------------------------------------------------
    def save_config(self) -> None:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(self.config_data, fh, indent=2)
        self.show_toast("Configuration saved", level="success")

    # ------------------------------------------------------------------
    def refresh_table(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for fit in self.config_data.get("fits", []):
            datasets = fit.get("datasets") or []
            if datasets:
                summary = ", ".join(
                    Path(ds.get("data_source", {}).get("path", "")).name or ds.get("label", "")
                    for ds in datasets[:2]
                )
                if len(datasets) > 2:
                    summary += f" (+{len(datasets) - 2} more)"
            else:
                summary = Path(fit.get("data_source", {}).get("path") or fit.get("datafile", "")).name
            residuals = "✅" if fit.get("residuals", True) else "❌"
            self.tree.insert(
                "",
                "end",
                values=(fit.get("title", ""), fit.get("formula", ""), summary, residuals),
            )

    # ------------------------------------------------------------------
    def select_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select data folder")
        if folder:
            self.folder = Path(folder)
            self.show_toast(f"Folder set to {self.folder}")

    # ------------------------------------------------------------------
    def add_fit(self) -> None:
        self._open_fit_editor()

    # ------------------------------------------------------------------
    def delete_fit(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        index = self.tree.index(selection[0])
        try:
            self.config_data["fits"].pop(index)
        except IndexError:
            return
        self.refresh_table()
        self.show_toast("Fit removed", level="warning")

    # ------------------------------------------------------------------
    def on_double_click(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        index = self.tree.index(selection[0])
        fit = self.config_data["fits"][index]
        self._open_fit_editor(fit, index)

    # ------------------------------------------------------------------
    def _open_fit_editor(self, fit: dict | None = None, index: int | None = None) -> None:
        base = {
            "title": "",
            "formula": "",
            "datafile": "",
            "residuals": True,
            "color": "#1f77b4",
            "layout": {"rows": 1, "columns": 1, "shared_x": False, "shared_y": False, "show_legend": True},
            "datasets": [],
        }
        data = copy.deepcopy(base)
        if fit:
            data.update(copy.deepcopy(fit))
        self._ensure_fit_defaults(data)
        editor = ttkb.Toplevel(self)
        editor.title("Fit details")
        editor.geometry("620x520")
        editor.grab_set()

        notebook = ttkb.Notebook(editor)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        general_tab = ttkb.Frame(notebook, padding=10)
        layout_tab = ttkb.Frame(notebook, padding=10)
        datasets_tab = ttkb.Frame(notebook, padding=10)
        notebook.add(general_tab, text="General")
        notebook.add(layout_tab, text="Layout")
        notebook.add(datasets_tab, text="Datasets")

        # General tab --------------------------------------------------
        entries: dict[str, ttkb.Entry] = {}
        for i, (label, key) in enumerate([
            ("Title", "title"),
            ("Formula", "formula"),
            ("Color", "color"),
        ]):
            ttkb.Label(general_tab, text=label).grid(row=i, column=0, sticky="w", padx=5, pady=6)
            entry = ttkb.Entry(general_tab)
            entry.grid(row=i, column=1, sticky="ew", padx=5, pady=6)
            entry.insert(0, data.get(key, ""))
            entries[key] = entry
        general_tab.columnconfigure(1, weight=1)

        residual_var = tk.BooleanVar(value=data.get("residuals", True))
        ttkb.Checkbutton(
            general_tab,
            text="Generate residual plot",
            variable=residual_var,
        ).grid(row=len(entries), column=0, columnspan=2, sticky="w", padx=5, pady=6)

        # Layout tab ---------------------------------------------------
        ttkb.Label(layout_tab, text="Rows").grid(row=0, column=0, sticky="w", padx=5, pady=6)
        rows_spin = ttkb.Spinbox(layout_tab, from_=1, to=12, width=6)
        rows_spin.grid(row=0, column=1, sticky="w", padx=5, pady=6)
        rows_spin.set(str(data.get("layout", {}).get("rows", 1)))

        ttkb.Label(layout_tab, text="Columns").grid(row=1, column=0, sticky="w", padx=5, pady=6)
        cols_spin = ttkb.Spinbox(layout_tab, from_=1, to=12, width=6)
        cols_spin.grid(row=1, column=1, sticky="w", padx=5, pady=6)
        cols_spin.set(str(data.get("layout", {}).get("columns", 1)))

        shared_x = tk.BooleanVar(value=data.get("layout", {}).get("shared_x", False))
        shared_y = tk.BooleanVar(value=data.get("layout", {}).get("shared_y", False))
        show_legend = tk.BooleanVar(value=data.get("layout", {}).get("show_legend", True))

        ttkb.Checkbutton(layout_tab, text="Share X axis", variable=shared_x).grid(
            row=2, column=0, columnspan=2, sticky="w", padx=5, pady=6
        )
        ttkb.Checkbutton(layout_tab, text="Share Y axis", variable=shared_y).grid(
            row=3, column=0, columnspan=2, sticky="w", padx=5, pady=6
        )
        ttkb.Checkbutton(layout_tab, text="Show legend", variable=show_legend).grid(
            row=4, column=0, columnspan=2, sticky="w", padx=5, pady=6
        )

        # Datasets tab -------------------------------------------------
        dataset_frame = ttkb.Frame(datasets_tab)
        dataset_frame.pack(fill="both", expand=True)

        dataset_tree = ttkb.Treeview(
            dataset_frame,
            columns=("Label", "File", "Pane"),
            show="headings",
            height=6,
            bootstyle="info",
        )
        for col, width in zip(("Label", "File", "Pane"), (200, 220, 80)):
            dataset_tree.heading(col, text=col)
            dataset_tree.column(col, width=width, anchor="w")
        dataset_tree.pack(side="left", fill="both", expand=True, padx=(0, 6))

        scrollbar = ttkb.Scrollbar(dataset_frame, command=dataset_tree.yview)
        dataset_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")

        dataset_list = copy.deepcopy(data.get("datasets", []))

        def _format_pane(ds: dict) -> str:
            if "pane" in ds and ds.get("pane"):
                return str(ds.get("pane"))
            if "pane_index" in ds and ds.get("pane_index") is not None:
                return str(ds.get("pane_index"))
            return "1"

        def refresh_dataset_tree() -> None:
            for item in dataset_tree.get_children():
                dataset_tree.delete(item)
            for idx, ds in enumerate(dataset_list):
                path = ds.get("data_source", {}).get("path", "")
                dataset_tree.insert(
                    "",
                    "end",
                    iid=str(idx),
                    values=(ds.get("label", f"Dataset {idx + 1}"), Path(path).name, _format_pane(ds)),
                )

        refresh_dataset_tree()

        def add_dataset() -> None:
            dialog = DatasetDialog(editor)
            editor.wait_window(dialog)
            if dialog.result:
                dataset_list.append(dialog.result)
                refresh_dataset_tree()

        def edit_dataset() -> None:
            selection = dataset_tree.selection()
            if not selection:
                return
            idx = int(selection[0])
            try:
                current = dataset_list[idx]
            except IndexError:
                return
            dialog = DatasetDialog(editor, current)
            editor.wait_window(dialog)
            if dialog.result:
                dataset_list[idx] = dialog.result
                refresh_dataset_tree()

        def delete_dataset() -> None:
            selection = dataset_tree.selection()
            if not selection:
                return
            idx = int(selection[0])
            try:
                dataset_list.pop(idx)
            except IndexError:
                return
            refresh_dataset_tree()

        button_frame = ttkb.Frame(datasets_tab)
        button_frame.pack(fill="x", pady=8)
        ttkb.Button(button_frame, text="Add", command=add_dataset, bootstyle="success-outline").pack(side="left", padx=4)
        ttkb.Button(button_frame, text="Edit", command=edit_dataset, bootstyle="info-outline").pack(side="left", padx=4)
        ttkb.Button(button_frame, text="Remove", command=delete_dataset, bootstyle="danger-outline").pack(side="left", padx=4)
        dataset_tree.bind("<Double-1>", lambda _evt: edit_dataset())

        def _save() -> None:
            payload = {
                "title": entries["title"].get().strip() or "Untitled",
                "formula": entries["formula"].get().strip() or "a*x + b",
                "color": entries["color"].get().strip() or "#1f77b4",
                "residuals": residual_var.get(),
            }
            payload["layout"] = {
                "rows": max(1, int(rows_spin.get() or 1)),
                "columns": max(1, int(cols_spin.get() or 1)),
                "shared_x": shared_x.get(),
                "shared_y": shared_y.get(),
                "show_legend": show_legend.get(),
            }
            payload["datasets"] = copy.deepcopy(dataset_list)
            self._ensure_fit_defaults(payload)
            if index is None:
                self.config_data.setdefault("fits", []).append(payload)
            else:
                self.config_data["fits"][index] = payload
            self.refresh_table()
            editor.destroy()

        buttons = ttkb.Frame(editor)
        buttons.pack(fill="x", pady=10)
        ttkb.Button(buttons, text="Cancel", command=editor.destroy).pack(side="right", padx=5)
        ttkb.Button(buttons, text="Save", command=_save, bootstyle="success").pack(side="right", padx=5)

    # ------------------------------------------------------------------
    def _ensure_fit_defaults(self, fit: dict) -> None:
        fit.setdefault("title", "Untitled")
        fit.setdefault("formula", "a*x + b")
        fit.setdefault("residuals", True)
        fit.setdefault("color", "#1f77b4")
        layout = fit.setdefault("layout", {})
        layout.setdefault("rows", 1)
        layout.setdefault("columns", 1)
        layout.setdefault("shared_x", False)
        layout.setdefault("shared_y", False)
        layout.setdefault("show_legend", True)

        datasets = fit.setdefault("datasets", [])
        # Migrate single data_source definitions into datasets list
        if not datasets and fit.get("data_source"):
            migrated = copy.deepcopy(fit["data_source"])
            datasets.append(
                {
                    "label": fit.get("title", "Dataset"),
                    "pane_index": 1,
                    "data_source": migrated,
                }
            )
        for dataset in datasets:
            self._ensure_dataset_defaults(dataset, fallback_path=fit.get("datafile", ""))

        # Retain compatibility if legacy keys exist but ensure structure
        if "data_source" in fit:
            fit.pop("data_source", None)

    def _ensure_dataset_defaults(self, dataset: dict, fallback_path: str = "") -> None:
        dataset.setdefault("label", "Dataset")
        if "pane" not in dataset and "pane_index" not in dataset:
            dataset["pane_index"] = 1
        data_source = dataset.setdefault("data_source", {})
        data_source.setdefault("path", fallback_path)
        columns = data_source.get("columns")
        if not isinstance(columns, dict):
            columns = {}
        cleaned_columns: dict[str, int | str | None] = {
            "x": int(columns.get("x", 1) or 1),
            "y": int(columns.get("y", 2) or 2),
        }
        if columns.get("error") not in (None, ""):
            try:
                cleaned_columns["error"] = int(columns.get("error"))
            except (TypeError, ValueError):
                cleaned_columns["error"] = columns.get("error")
        if columns.get("weight") not in (None, ""):
            try:
                cleaned_columns["weight"] = int(columns.get("weight"))
            except (TypeError, ValueError):
                cleaned_columns["weight"] = columns.get("weight")
        data_source["columns"] = cleaned_columns
        preprocessing = data_source.get("preprocessing")
        if not isinstance(preprocessing, list):
            preprocessing = []
        data_source["preprocessing"] = preprocessing
        style = dataset.get("style")
        if style is not None and not isinstance(style, dict):
            dataset["style"] = {}
        dataset.setdefault("style", {})


class DatasetDialog(ttkb.Toplevel):
    def __init__(self, master: tk.Misc, dataset: dict | None = None) -> None:
        super().__init__(master)
        self.title("Dataset settings")
        self.result: dict | None = None
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        data = copy.deepcopy(dataset) if dataset else {}
        columns = (data.get("data_source", {}) or {}).get("columns", {})
        style = data.get("style", {}) if isinstance(data.get("style"), dict) else {}

        ttkb.Label(self, text="Label").grid(row=0, column=0, sticky="w", padx=10, pady=6)
        self.label_entry = ttkb.Entry(self, width=40)
        self.label_entry.grid(row=0, column=1, columnspan=2, sticky="ew", padx=10, pady=6)
        self.label_entry.insert(0, data.get("label", ""))

        ttkb.Label(self, text="Pane (name or #)").grid(row=1, column=0, sticky="w", padx=10, pady=6)
        self.pane_entry = ttkb.Entry(self)
        pane_value = data.get("pane") or ("" if data.get("pane_index") is None else str(data.get("pane_index")))
        self.pane_entry.insert(0, pane_value)
        self.pane_entry.grid(row=1, column=1, columnspan=2, sticky="ew", padx=10, pady=6)

        ttkb.Label(self, text="Data file").grid(row=2, column=0, sticky="w", padx=10, pady=6)
        self.path_entry = ttkb.Entry(self, width=40)
        self.path_entry.grid(row=2, column=1, sticky="ew", padx=10, pady=6)
        self.path_entry.insert(0, (data.get("data_source") or {}).get("path", ""))

        def browse() -> None:
            chosen = filedialog.askopenfilename(title="Select data file")
            if chosen:
                self.path_entry.delete(0, tk.END)
                self.path_entry.insert(0, chosen)

        ttkb.Button(self, text="Browse", command=browse, bootstyle="secondary-outline").grid(
            row=2, column=2, padx=10, pady=6
        )

        ttkb.Label(self, text="X column").grid(row=3, column=0, sticky="w", padx=10, pady=6)
        self.x_spin = ttkb.Spinbox(self, from_=1, to=128, width=6)
        self.x_spin.grid(row=3, column=1, sticky="w", padx=10, pady=6)
        self.x_spin.set(str(columns.get("x", 1)))

        ttkb.Label(self, text="Y column").grid(row=4, column=0, sticky="w", padx=10, pady=6)
        self.y_spin = ttkb.Spinbox(self, from_=1, to=128, width=6)
        self.y_spin.grid(row=4, column=1, sticky="w", padx=10, pady=6)
        self.y_spin.set(str(columns.get("y", 2)))

        ttkb.Label(self, text="Error column").grid(row=3, column=2, sticky="w", padx=10, pady=6)
        self.error_entry = ttkb.Entry(self, width=6)
        if columns.get("error") not in (None, ""):
            self.error_entry.insert(0, str(columns.get("error")))
        self.error_entry.grid(row=3, column=3, sticky="w", padx=10, pady=6)

        ttkb.Label(self, text="Weight column").grid(row=4, column=2, sticky="w", padx=10, pady=6)
        self.weight_entry = ttkb.Entry(self, width=6)
        if columns.get("weight") not in (None, ""):
            self.weight_entry.insert(0, str(columns.get("weight")))
        self.weight_entry.grid(row=4, column=3, sticky="w", padx=10, pady=6)

        ttkb.Label(self, text="Line color").grid(row=5, column=0, sticky="w", padx=10, pady=6)
        self.color_entry = ttkb.Entry(self)
        self.color_entry.grid(row=5, column=1, columnspan=2, sticky="ew", padx=10, pady=6)
        self.color_entry.insert(0, style.get("line_color", ""))

        ttkb.Label(self, text="Preprocessing (JSON list)").grid(row=6, column=0, sticky="nw", padx=10, pady=6)
        self.preprocess_text = tk.Text(self, height=4, width=40)
        preprocessing = (data.get("data_source") or {}).get("preprocessing", [])
        try:
            text_value = json.dumps(preprocessing, indent=2)
        except TypeError:
            text_value = "[]"
        self.preprocess_text.insert("1.0", text_value)
        self.preprocess_text.grid(row=6, column=1, columnspan=3, sticky="nsew", padx=10, pady=6)

        self.columnconfigure(1, weight=1)
        self.columnconfigure(2, weight=0)
        self.rowconfigure(6, weight=1)

        button_frame = ttkb.Frame(self)
        button_frame.grid(row=7, column=0, columnspan=4, sticky="e", padx=10, pady=10)
        ttkb.Button(button_frame, text="Cancel", command=self.destroy).pack(side="right", padx=5)
        ttkb.Button(button_frame, text="Save", command=self._on_save, bootstyle="success").pack(side="right", padx=5)

        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _on_save(self) -> None:
        label = self.label_entry.get().strip() or "Dataset"
        pane_value = self.pane_entry.get().strip()
        pane_payload: dict[str, int | str] = {}
        if pane_value:
            if pane_value.isdigit():
                pane_payload["pane_index"] = int(pane_value)
            else:
                pane_payload["pane"] = pane_value
        else:
            pane_payload["pane_index"] = 1

        path = self.path_entry.get().strip()
        try:
            x_col = int(self.x_spin.get() or 1)
            y_col = int(self.y_spin.get() or 2)
        except ValueError:
            messagebox.showerror("Invalid input", "X and Y columns must be integers.")
            return

        error_col = self.error_entry.get().strip()
        weight_col = self.weight_entry.get().strip()

        columns: dict[str, int | str] = {"x": x_col, "y": y_col}
        if error_col:
            try:
                columns["error"] = int(error_col)
            except ValueError:
                columns["error"] = error_col
        if weight_col:
            try:
                columns["weight"] = int(weight_col)
            except ValueError:
                columns["weight"] = weight_col

        preprocess_raw = self.preprocess_text.get("1.0", tk.END).strip()
        if preprocess_raw:
            try:
                preprocessing = json.loads(preprocess_raw)
                if not isinstance(preprocessing, list):
                    raise ValueError
            except (json.JSONDecodeError, ValueError):
                messagebox.showerror(
                    "Invalid preprocessing",
                    "Preprocessing must be a JSON list (e.g., []).",
                )
                return
        else:
            preprocessing = []

        data_source = {"path": path, "columns": columns, "preprocessing": preprocessing}

        color_value = self.color_entry.get().strip()
        style: dict[str, str] = {}
        if color_value:
            style["line_color"] = color_value

        payload: dict[str, object] = {"label": label, "data_source": data_source}
        payload.update(pane_payload)
        if style:
            payload["style"] = style

        self.result = payload
        self.destroy()

    # ------------------------------------------------------------------
    def run_batch(self) -> None:
        if self.runner_thread and self.runner_thread.is_alive():
            messagebox.showinfo("Batch running", "A batch is already running")
            return

        self.save_config()
        self.progress.configure(value=0)
        self.log_text.delete("1.0", tk.END)
        self._progress_total = 0
        self._progress_completed = 0
        self._event_queue = queue.Queue()

        def _push_event(event: dict[str, Any]) -> None:
            if self._event_queue is not None:
                self._event_queue.put(event)

        def _runner() -> None:
            try:
                run_job(
                    copy.deepcopy(self.config_data),
                    config_path=CONFIG_PATH,
                    on_event=_push_event,
                )
            except Exception:  # noqa: BLE001 - run_job already reports via events
                pass
            finally:
                if self._event_queue is not None:
                    self._event_queue.put({"type": "job-thread-exit"})

        self.runner_thread = threading.Thread(target=_runner, daemon=True)
        self.runner_thread.start()
        self.after(100, self._poll_events)

    # ------------------------------------------------------------------
    def _poll_events(self) -> None:
        if self._event_queue is None:
            return
        try:
            while True:
                event = self._event_queue.get_nowait()
                self._handle_engine_event(event)
        except queue.Empty:
            pass

        if self._event_queue is not None:
            self.after(100, self._poll_events)

    # ------------------------------------------------------------------
    def _handle_engine_event(self, event: dict[str, Any]) -> None:
        etype = event.get("type")
        if etype == "log":
            message = event.get("message", "")
            if message and not message.endswith("\n"):
                message += "\n"
            if message:
                self._append_log(message)
            return

        if etype == "job-start":
            total = int(event.get("total") or 0)
            self._progress_total = max(total, 0)
            self._progress_completed = 0
            self.progress.configure(value=0)
            ts = event.get("timestamp", "")
            self._append_log(f"[RUN] Starting batch at {ts} ({total} plots)\n")
            return

        if etype == "plot-start":
            title = event.get("title", "Untitled")
            self._append_log(f"[RUN] Processing: {title}\n")
            return

        if etype == "plot-complete":
            self._progress_completed += 1
            self._update_progress_bar()
            title = event.get("title", "Untitled")
            self._append_log(f"[OK] Finished: {title}\n")
            return

        if etype == "plot-error":
            self._progress_completed += 1
            self._update_progress_bar()
            title = event.get("title", "Untitled")
            error_msg = event.get("error", "Unknown error")
            self._append_log(f"[X] Error in {title}: {error_msg}\n")
            self.show_toast(f"Plot failed: {title}", level="error")
            return

        if etype == "job-complete":
            self.progress.configure(value=100)
            results_path = event.get("results_path")
            if results_path:
                self._append_log(f"\n[COMPLETE] Results saved to: {results_path}\n")
            self.show_toast("Batch complete", level="success")
            return

        if etype == "job-error":
            error_msg = event.get("error", "Batch failed")
            self._append_log(f"[X] {error_msg}\n")
            messagebox.showerror("Batch failed", error_msg)
            self.show_toast("Batch failed", level="error")
            return

        if etype == "job-thread-exit":
            self.runner_thread = None
            self._event_queue = None
            return

    # ------------------------------------------------------------------
    def _update_progress_bar(self) -> None:
        if self._progress_total:
            percent = (self._progress_completed / self._progress_total) * 100
        else:
            percent = 0.0
        self.progress.configure(value=min(percent, 100))

    # ------------------------------------------------------------------
    def _append_log(self, text: str) -> None:
        def _write() -> None:
            self.log_text.insert(tk.END, text)
            self.log_text.see(tk.END)

        self.after(0, _write)

    # ------------------------------------------------------------------
    def open_latest_report(self) -> None:
        outputs = Path("outputs")
        if not outputs.exists():
            messagebox.showinfo("No outputs", "No outputs folder found yet.")
            return
        latest = max(outputs.glob("*/fit_results.json"), default=None, key=lambda p: p.stat().st_mtime)
        if not latest:
            messagebox.showinfo("No report", "Generate a batch before opening a report.")
            return
        webbrowser = __import__("webbrowser")
        webbrowser.open(latest.parent.as_uri())

    # ------------------------------------------------------------------
    def show_toast(self, message: str, level: str = "info") -> None:
        colors = {
            "info": "#2E86C1",
            "success": "#27AE60",
            "warning": "#F39C12",
            "error": "#C0392B",
        }
        toast = tk.Toplevel(self)
        toast.overrideredirect(True)
        toast.configure(bg=colors.get(level, "#2E86C1"))
        ttkb.Label(toast, text=message, bootstyle="inverse", padding=10).pack()
        self.update_idletasks()
        x = self.winfo_rootx() + self.winfo_width() - 260
        y = self.winfo_rooty() + self.winfo_height() - 100
        toast.geometry(f"240x60+{x}+{y}")
        toast.after(2500, toast.destroy)


if __name__ == "__main__":
    app = PlotinatorApp()
    app.mainloop()
