from __future__ import annotations

import copy
import json
import math
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

import ttkbootstrap as ttkb
from ttkbootstrap.constants import CENTER, LEFT, RIGHT, END, BOTH, X, Y, YES, NO, TOP, BOTTOM

from config import ConfigError, FitConfig, PlotinatorConfig, load_config, load_config_file
from engine import run_batch as engine_run_batch

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
        self.config_path = Path(CONFIG_PATH).resolve()
        self.job: PlotinatorConfig = PlotinatorConfig(base_path=self.config_path.parent, fits=[])
        self.runner_thread: threading.Thread | None = None
        self._stop_log = threading.Event()
        self._event_queue: queue.Queue[dict[str, Any]] | None = None
        self._progress_total = 0
        self._progress_completed = 0
        self.status_var = tk.StringVar(self, value="Idle")
        self._images: dict[str, tk.PhotoImage] = {}
        self._load_images()

        self._create_widgets()
        self.tree.bind("<Double-1>", self.on_double_click)
        self.load_config()

    # ------------------------------------------------------------------
    def _create_widgets(self) -> None:
        header = ttkb.Frame(self, padding=10)
        header.pack(fill="x")
        if (logo := self._images.get("icon_header")) is not None:
            ttkb.Label(header, image=logo).pack(side="left", padx=(0, 10))
        ttkb.Label(
            header,
            text="⚙️ Plotinator 100000",
            font=("Segoe UI", 22, "bold"),
        ).pack(side="left")
        ttkb.Button(header, text="🌓", width=3, command=self.toggle_theme).pack(side="right", padx=8)

        toolbar = ttkb.Frame(self, padding=10)
        toolbar.pack(fill="x")
        toolbar_logo = self._images.get("toolbar_button")
        button_plan = [
            ("Data Folder", self.select_folder, "info-outline", True),
            ("Add Fit", self.add_fit, "success-outline", False),
            ("Delete Fit", self.delete_fit, "danger-outline", True),
            ("Save Config", self.save_config, "secondary-outline", False),
            ("Run Batch", self.run_batch, "success", True),
            ("Open Report", self.open_latest_report, "primary-outline", False),
        ]
        for text, cmd, style, use_logo in button_plan:
            kwargs: dict[str, Any] = {"text": text, "command": cmd, "bootstyle": style}
            if use_logo and toolbar_logo is not None:
                kwargs.update({"image": toolbar_logo, "compound": "left", "padding": (6, 4)})
            ttkb.Button(toolbar, **kwargs).pack(side="left", padx=4)

        table_frame = ttkb.Frame(self, padding=10)
        table_frame.pack(fill="both", expand=True)
        columns = ("Title", "Formula", "Datasets", "Residuals")
        self.tree = ttkb.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            height=12,
            bootstyle="info",
        )
        for col, width in zip(columns, (200, 260, 220, 80), strict=False):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True)

        progress_frame = ttkb.Frame(self, padding=(10, 0))
        progress_frame.pack(fill="x")
        status_label = ttkb.Label(progress_frame, textvariable=self.status_var, anchor="w")
        if (status_icon := self._images.get("toolbar_status")) is not None:
            status_label.configure(image=status_icon, compound="left", padding=(4, 0))
        status_label.pack(fill="x", pady=(0, 6))
        self.progress = ttkb.Progressbar(
            progress_frame,
            mode="determinate",
            bootstyle="info-striped",
        )
        self.progress.pack(fill="x")

        log_frame = ttkb.Labelframe(self, padding=10)
        if (log_icon := self._images.get("toolbar_log")) is not None:
            log_label = ttkb.Label(log_frame, text="Batch log", image=log_icon, compound="left")
            log_label.configure(font=("Segoe UI", 11, "bold"), padding=(4, 0))
            log_frame.configure(labelwidget=log_label)
        else:
            log_frame.configure(text="Batch log")
        log_frame.pack(fill="both", expand=True, padx=10, pady=10)
        self.log_text = tk.Text(
            log_frame,
            height=10,
            bg="#101820",
            fg="#39FF14",
            insertbackground="#39FF14",
        )
        self.log_text.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    def _scale_image(self, image: tk.PhotoImage, target: int) -> tk.PhotoImage:
        width = image.width()
        height = image.height()
        scale = max(width / target, height / target)
        if scale <= 1:
            return image
        factor = int(math.ceil(scale))
        return image.subsample(factor, factor)

    # ------------------------------------------------------------------
    def _load_images(self) -> None:
        base_path = Path(__file__).resolve().parent
        assets = {
            "icon": base_path / "General-logo.png",
            "toolbar": base_path / "Toolbar-noText-Logo.png",
        }
        for key, path in assets.items():
            if not path.exists():
                continue
            try:
                self._images[key] = tk.PhotoImage(file=path.as_posix())
            except tk.TclError:
                continue

        icon = self._images.get("icon")
        if icon is not None:
            self.iconphoto(True, icon)
            self._images["icon_header"] = self._scale_image(icon, 64)
            self._images["icon_toast"] = self._scale_image(icon, 32)

        toolbar_icon = self._images.get("toolbar")
        if toolbar_icon is not None:
            self._images["toolbar_button"] = self._scale_image(toolbar_icon, 28)
            self._images["toolbar_status"] = self._scale_image(toolbar_icon, 22)
            self._images["toolbar_log"] = self._scale_image(toolbar_icon, 48)

    # ------------------------------------------------------------------
    def toggle_theme(self) -> None:
        current = self.style.theme.name
        new_theme = "flatly" if current == "superhero" else "superhero"
        self.style.theme_use(new_theme)
        self.show_toast(f"Theme switched to {new_theme.title()}")

    # ------------------------------------------------------------------
    def load_config(self) -> None:
        if not self.config_path.exists():
            self.job = PlotinatorConfig(base_path=self.config_path.parent, fits=[])
            self.save_config()
            self.refresh_table()
            return

        try:
            self.job = load_config_file(self.config_path)
        except ConfigError as exc:
            error_message = f"Failed to load config: {exc}"
            self._append_log(f"[CONFIG] {error_message}\n")
            self.show_toast(error_message, level="error")
            self.job = PlotinatorConfig(base_path=self.config_path.parent, fits=[])
            return
        self.refresh_table()

    # ------------------------------------------------------------------
    def save_config(self) -> None:
        payload = self.job.to_dict()
        with open(self.config_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        self.show_toast("Configuration saved", level="success")

    # ------------------------------------------------------------------
    def _reload_from_mapping(self, mapping: dict) -> bool:
        try:
            self.job = load_config(mapping, base_path=self.job.base_path)
        except ConfigError as exc:
            error_message = f"Invalid configuration change: {exc}"
            self._append_log(f"[CONFIG] {error_message}\n")
            self.show_toast(error_message, level="error")
            return False
        self.refresh_table()
        return True

    # ------------------------------------------------------------------
    def refresh_table(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for fit in self.job.fits:
            datasets = fit.datasets
            if datasets:
                summary = ", ".join(
                    Path(ds.data_source.original_path).name or ds.label for ds in datasets[:2]
                )
                if len(datasets) > 2:
                    summary += f" (+{len(datasets) - 2} more)"
            else:
                summary = ""
            residuals = "✅" if fit.residuals else "❌"
            self.tree.insert(
                "",
                "end",
                values=(fit.title, fit.fit_formula, summary, residuals),
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
        mapping = self.job.to_dict()
        try:
            mapping.setdefault("fits", []).pop(index)
        except IndexError:
            return
        if self._reload_from_mapping(mapping):
            self.show_toast("Fit removed", level="warning")

    # ------------------------------------------------------------------
    def on_double_click(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        index = self.tree.index(selection[0])
        try:
            fit = self.job.fits[index]
        except IndexError:
            return
        self._open_fit_editor(fit, index)

    # ------------------------------------------------------------------
    def _open_fit_editor(
        self,
        fit: FitConfig | dict | None = None,
        index: int | None = None,
    ) -> None:
        base = {
            "title": "",
            "formula": "",
            "datafile": "",
            "residuals": True,
            "color": "#1f77b4",
            "layout": {
                "rows": 1,
                "columns": 1,
                "shared_x": False,
                "shared_y": False,
                "show_legend": True,
            },
            "datasets": [],
        }
        if isinstance(fit, FitConfig):
            data = fit.to_dict(relative_to=self.job.base_path)
        else:
            data = copy.deepcopy(base)
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
        for col, width in zip(("Label", "File", "Pane"), (200, 220, 80), strict=False):
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
                    values=(
                        ds.get("label", f"Dataset {idx + 1}"),
                        Path(path).name,
                        _format_pane(ds),
                    ),
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
        ttkb.Button(
            button_frame,
            text="Add",
            command=add_dataset,
            bootstyle="success-outline",
        ).pack(side="left", padx=4)
        ttkb.Button(
            button_frame,
            text="Edit",
            command=edit_dataset,
            bootstyle="info-outline",
        ).pack(side="left", padx=4)
        ttkb.Button(
            button_frame,
            text="Remove",
            command=delete_dataset,
            bootstyle="danger-outline",
        ).pack(side="left", padx=4)
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
            if data.get("parameters"):
                payload["parameters"] = copy.deepcopy(data.get("parameters"))
            style_overrides = copy.deepcopy(data.get("style", {}))
            if payload["color"]:
                style_overrides.setdefault("line_color", payload["color"])
            if style_overrides:
                payload["style"] = style_overrides

            mapping = self.job.to_dict()
            fits = mapping.setdefault("fits", [])
            if index is None:
                fits.append(payload)
            else:
                try:
                    fits[index] = payload
                except IndexError:
                    fits.append(payload)
            if self._reload_from_mapping(mapping):
                editor.destroy()

        buttons = ttkb.Frame(editor)
        buttons.pack(fill="x", pady=10)
        ttkb.Button(buttons, text="Cancel", command=editor.destroy).pack(side="right", padx=5)
        ttkb.Button(
            buttons,
            text="Save",
            command=_save,
            bootstyle="success",
        ).pack(side="right", padx=5)

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
        pane_value = data.get("pane") or (
            ""
            if data.get("pane_index") is None
            else str(data.get("pane_index"))
        )
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

        ttkb.Label(self, text="Preprocessing (JSON list)").grid(
            row=6,
            column=0,
            sticky="nw",
            padx=10,
            pady=6,
        )
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
        ttkb.Button(
            button_frame,
            text="Save",
            command=self._on_save,
            bootstyle="success",
        ).pack(side="right", padx=5)

        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _on_save(self) -> None:
        def notify(
            message: str,
            level: str = "error",
            focus_widget: tk.Widget | None = None,
        ) -> None:
            target: tk.Misc | None = self
            while target is not None and not hasattr(target, "show_toast"):
                target = getattr(target, "master", None)
            if target is not None and hasattr(target, "show_toast"):
                target.show_toast(message, level=level)
            if focus_widget is not None:
                focus_widget.focus_set()

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
        x_value_raw = (self.x_spin.get() or "").strip()
        y_value_raw = (self.y_spin.get() or "").strip()
        try:
            x_col = int(x_value_raw or 1)
        except ValueError:
            notify("X column must be an integer.", focus_widget=self.x_spin)
            return
        try:
            y_col = int(y_value_raw or 2)
        except ValueError:
            notify("Y column must be an integer.", focus_widget=self.y_spin)
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
                notify(
                    "Preprocessing must be a JSON list (e.g., []).",
                    focus_widget=self.preprocess_text,
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
            info_message = "Batch already running."
            self._append_log(f"[WARN] {info_message}\n")
            self.show_toast(info_message, level="warning")
            return

        self.save_config()
        self.progress.configure(value=0)
        self.log_text.delete("1.0", tk.END)
        self._progress_total = 0
        self._progress_completed = 0
        self._stop_log.clear()
        self._event_queue = queue.Queue()
        self._set_status("Launching batch…")

        event_state = {"job_error": False}

        class _BatchCancelled(Exception):
            """Internal sentinel exception to abort the engine runner."""

            pass

        def _push_event(event: dict[str, Any]) -> None:
            if self._stop_log.is_set():
                raise _BatchCancelled
            if self._event_queue is not None:
                if event.get("type") == "job-error":
                    event_state["job_error"] = True
                self._event_queue.put(event)

        def _runner() -> None:
            try:
                engine_run_batch(str(self.config_path), on_event=_push_event)
            except _BatchCancelled:
                self._append_log("[CANCELLED] Batch cancelled by user.\n")
                self._set_status("Batch cancelled")
            except Exception as exc:  # noqa: BLE001 - surface via events only
                error_message = str(exc)
                if not event_state["job_error"]:
                    event_state["job_error"] = True
                    if self._event_queue is not None:
                        self._event_queue.put({"type": "job-error", "error": error_message})
                    else:
                        self._append_log(f"[X] {error_message}\n")
                        self._set_status("Batch failed")
            finally:
                self.runner_thread = None

        self.runner_thread = threading.Thread(target=_runner, daemon=True)
        self.runner_thread.start()
        self.after(100, self._poll_events)

    # ------------------------------------------------------------------
    def _poll_events(self) -> None:
        if self._event_queue is None:
            return

        try:
            event = self._event_queue.get_nowait()
        except queue.Empty:
            event = None
        else:
            self._handle_engine_event(event)

        if self._event_queue is None:
            return

        if event is not None and not self._event_queue.empty():
            self.after(0, self._poll_events)
            return

        runner = self.runner_thread
        if (runner is None or not runner.is_alive()) and self._event_queue.empty():
            self._event_queue = None
            return

        self.after(100, self._poll_events)

    # ------------------------------------------------------------------
    def _stop_runner_thread(self) -> None:
        """Request cancellation of the in-process engine runner and drain events."""

        self._stop_log.set()
        thread = self.runner_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join()
        self.runner_thread = None
        queued_events: queue.Queue[dict[str, Any]] | None = self._event_queue
        self._event_queue = None
        if queued_events is not None:
            try:
                while True:
                    event = queued_events.get_nowait()
                    self._handle_engine_event(event)
            except queue.Empty:
                pass
        self._stop_log.clear()

    # ------------------------------------------------------------------
    def stop_batch(self) -> None:
        """Public helper for stop controls to shut down the batch thread."""

        self._stop_runner_thread()

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
            self._set_status(f"Batch started • 0/{self._progress_total or 0} complete")
            return

        if etype == "plot-start":
            title = event.get("title", "Untitled")
            self._append_log(f"[RUN] Processing: {title}\n")
            self._set_status(f"Processing plot: {title}")
            return

        if etype == "plot-complete":
            self._progress_completed += 1
            self._update_progress_bar()
            title = event.get("title", "Untitled")
            self._append_log(f"[OK] Finished: {title}\n")
            total_display = self._progress_total if self._progress_total else "?"
            self._set_status(
                f"Completed {self._progress_completed}/{total_display}: {title}"
            )
            return

        if etype == "plot-error":
            self._progress_completed += 1
            self._update_progress_bar()
            title = event.get("title", "Untitled")
            error_msg = event.get("error", "Unknown error")
            self._append_log(f"[X] Error in {title}: {error_msg}\n")
            self.show_toast(f"Plot failed: {title}", level="error")
            self._set_status(f"Plot error: {title}")
            return

        if etype == "report-markdown-ready":
            md_path = event.get("markdown_path", "")
            if md_path:
                self._append_log(f"[REPORT] Markdown saved to: {md_path}\n")
            self._set_status("Report markdown generated")
            return

        if etype == "report-exported":
            pdf_path = event.get("pdf_path", "")
            if pdf_path:
                self._append_log(f"[REPORT] PDF exported to: {pdf_path}\n")
            self.show_toast("Report exported", level="success")
            self._set_status("Report exported")
            return

        if etype == "report-error":
            stage = event.get("stage", "report")
            error_msg = event.get("error", "Unknown error")
            self._append_log(f"[WARN] Report {stage} failed: {error_msg}\n")
            self.show_toast("Report generation issue", level="warning")
            self._set_status(f"Report {stage} failed")
            return

        if etype == "job-complete":
            self._progress_completed = self._progress_total or self._progress_completed
            self.progress.configure(value=100)
            results_path = event.get("results_path")
            if results_path:
                self._append_log(f"\n[COMPLETE] Results saved to: {results_path}\n")
            pdf_path = event.get("pdf_path")
            if pdf_path:
                self._append_log(f"[REPORT] Latest PDF: {pdf_path}\n")
            self.show_toast("Batch complete", level="success")
            self._set_status("Batch complete")
            self._event_queue = None
            return

        if etype == "job-error":
            error_msg = event.get("error", "Batch failed")
            self._append_log(f"[X] {error_msg}\n")
            self.show_toast(error_msg, level="error")
            messagebox.showerror("Plotinator", error_msg)
            self._set_status(f"Batch failed: {error_msg}")
            self._event_queue = None
            return

        if etype == "job-exception":
            error_msg = event.get("error", "Batch failed")
            self._append_log(f"[X] {error_msg}\n")
            self.show_toast(error_msg, level="error")
            messagebox.showerror("Plotinator", error_msg)
            self._set_status(f"Batch failed: {error_msg}")
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
    def _set_status(self, text: str) -> None:
        def _apply() -> None:
            self.status_var.set(text)

        self.after(0, _apply)

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
            info_message = "Outputs folder not found yet. Run a batch first."
            self._append_log(f"[REPORT] {info_message}\n")
            self.show_toast(info_message, level="info")
            return
        latest = max(
            outputs.glob("*/fit_results.json"),
            default=None,
            key=lambda p: p.stat().st_mtime,
        )
        if not latest:
            info_message = "No reports available yet. Generate a batch first."
            self._append_log(f"[REPORT] {info_message}\n")
            self.show_toast(info_message, level="info")
            return
        latest_dir = latest.parent
        pdf_report = latest_dir / "report.pdf"
        md_report = latest_dir / "report.md"
        webbrowser = __import__("webbrowser")
        if pdf_report.exists():
            webbrowser.open(pdf_report.as_uri())
        elif md_report.exists():
            webbrowser.open(md_report.as_uri())
        else:
            webbrowser.open(latest_dir.as_uri())

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

    # ------------------------------------------------------------------
    def destroy(self) -> None:  # type: ignore[override]
        self._stop_runner_thread()
        super().destroy()


def main() -> int:
    app = PlotinatorApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
