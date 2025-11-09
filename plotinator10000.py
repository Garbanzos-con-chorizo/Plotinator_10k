import tkinter as tk
from tkinter import ttk, messagebox, filedialog, colorchooser, simpledialog
import subprocess, os, json, threading, platform, webbrowser
import ttkbootstrap as ttkb  # pip install ttkbootstrap
import shutil
import re
from ttkbootstrap.constants import *


CONFIG_PATH = "config.json"

class PlotinatorApp(ttkb.Window):
    def __init__(self):
        super().__init__(themename="superhero")
        self.title("Plotinator 100000")
        self.geometry("1500x900")
        self.resizable(True, True)

        self.folder = None
        self.config_data = {}

        self.create_widgets()  # creates self.tree
        self.tree.bind("<Double-1>", self.on_double_click)  # bind AFTER creation
        self.load_config()


    # --- UI Layout ---------------------------------------------------------
    def create_widgets(self):
        # --- Sidebar Accent (optional) ---
        accent = ttkb.Frame(self, width=8, bootstyle="info")
        accent.pack(side="left", fill="y")

        # --- Header ---
        header = ttkb.Frame(self, bootstyle="dark", padding=10)
        header.pack(fill="x")

        ttkb.Label(header, text="⚙️ Plotinator 100000",
                   font=("Segoe UI", 24, "bold"),
                   bootstyle="light").pack(side="left", padx=10)

        ttkb.Button(header, text="🌓", bootstyle="info", width=3, command=self.toggle_theme).pack(side="right", padx=10)

        # --- Toolbar ---
        toolbar = ttkb.Frame(self, padding=10)
        toolbar.pack(fill="x")

        buttons = [
            ("📂 Data Folder", self.select_folder, "info-outline"),
            ("💾 Save Config", self.save_config, "secondary-outline"),
            ("🚀 Run Batch", self.run_batch, "success"),
            ("📘 Open Report", self.open_latest_report, "primary-outline"),
            ("➕ Add Fit", self.add_fit, "success-outline"),
            ("🗑 Delete Fit", self.delete_fit, "danger-outline")
        ]
        for i, (txt, cmd, style) in enumerate(buttons):
            ttkb.Button(toolbar, text=txt, command=cmd, bootstyle=style).grid(row=0, column=i, padx=6)

        # --- Table ---
        table_frame = ttkb.Frame(self, padding=10)
        table_frame.pack(fill="both", expand=True)

        self.tree = ttkb.Treeview(
            table_frame,
            columns=("Title", "Formula", "Datasets", "Layout", "Residuals"),
            show="headings",
            height=15,
            bootstyle="info"
        )
        for col, width in [
            ("Title", 200),
            ("Formula", 260),
            ("Datasets", 100),
            ("Layout", 100),
            ("Residuals", 80),
        ]:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)

        # Zebra stripes
        self.style.configure("Treeview", rowheight=30)
        self.tree.tag_configure("odd", background="#222831")
        self.tree.tag_configure("even", background="#1c1f26")

        # --- Progress + Log Console ---
        self.progress = ttkb.Progressbar(self, mode="determinate", bootstyle="info-striped")
        self.progress.pack(fill="x", padx=15, pady=10)

        self.log_text = tk.Text(self, height=10, bg="#101820", fg="#39FF14", insertbackground="#39FF14",
                                font=("Consolas", 10), relief="flat", borderwidth=6,
                                highlightthickness=1, highlightbackground="#3fa9f5")
        self.log_text.pack(fill="both", expand=True, padx=15, pady=5)

    def toggle_theme(self):
        current = self.style.theme.name
        new_theme = "flatly" if current == "superhero" else "superhero"
        self.style.theme_use(new_theme)
        icon = "🌞" if new_theme == "flatly" else "🌙"
        self.show_toast("🎨 Theme Switched", f"{icon}  Now using {new_theme.title()} mode")


    
    # --- Config management -------------------------------------------------
    def load_config(self):
    # Always start with a sane default
        self.config_data = {"fits": []}

        if not os.path.exists(CONFIG_PATH):
            # Create a minimal starter config
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.config_data, f, indent=4)
            self.refresh_table()
            return

        # Read file and normalize schema
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as e:
            self.show_toast("Config error", f"Could not read config.json:\n{e}", level="error")
            return

        # If it already has 'fits', use it
        if isinstance(raw, dict) and isinstance(raw.get("fits"), list):
            self.config_data = {"fits": raw["fits"]}

        # Backwards compatibility: migrate 'plots' -> 'fits'
        elif isinstance(raw, dict) and isinstance(raw.get("plots"), list):
            migrated = []
            for p in raw["plots"]:
                # Map old keys to new schema gracefully
                migrated.append({
                    "title":     p.get("title", "Untitled"),
                    "formula":   p.get("fit_formula") or p.get("formula", "a*x + b"),
                    "datafile":  p.get("datafile", ""),
                    "residuals": bool(p.get("residuals", True)),
                    "color":     (p.get("style", {}) or {}).get("line_color", "#1f77b4"),
                })
            self.config_data = {"fits": migrated}

            # (Optional) write back the migrated file so future loads are clean
            try:
                with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                    json.dump(self.config_data, f, indent=4)
            except Exception as e:
                self.show_toast("Config warning", f"Loaded migrated config but couldn't save it:\n{e}", level="warning")

        else:
            # Unknown schema; keep default empty fits and warn
            self.show_toast(
                "Config warning",
                "config.json has no 'fits' or 'plots'. Starting with an empty list.",
                level="warning",
            )

        for fit in self.config_data.get("fits", []):
            self.ensure_fit_defaults(fit)

        self.refresh_table()

    def save_config(self):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self.config_data, f, indent=4)
        self.show_toast("💾 Configuration saved successfully", level="success")

    def refresh_table(self):
        for i in self.tree.get_children():
            self.tree.delete(i)

        fits = self.config_data.get("fits", [])
        for fit in fits:
            self.ensure_fit_defaults(fit)
            title = fit.get("title", "")
            formula = fit.get("formula", "")
            datasets = fit.get("datasets", [])
            layout = fit.get("layout", {})
            ds_count = len(datasets)
            layout_desc = f"{layout.get('rows', 1)}x{layout.get('columns', 1)}"
            residuals = "✅" if fit.get("residuals", False) else "❌"
            self.tree.insert("", "end", values=(title, formula, ds_count, layout_desc, residuals))


    #-------- Utilities ------------------

    def _on_mousewheel(self, event, canvas):
        """Handle scroll safely across Windows/macOS/Linux."""
        try:
            # Windows scroll
            if event.delta:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            else:
                # Linux (event.num == 4 or 5)
                if event.num == 4:
                    canvas.yview_scroll(-1, "units")
                elif event.num == 5:
                    canvas.yview_scroll(1, "units")
        except tk.TclError:
            pass  # ignore scrolls after window is closed

    def show_toast(self, message, detail=None, level="info"):
        """Display a floating toast message with optional detail text."""
        # Reuse or create toast window
        if hasattr(self, "_toast") and self._toast.winfo_exists():
            toast = self._toast
            for widget in toast.winfo_children():
                widget.destroy()
        else:
            toast = tk.Toplevel(self)
            toast.overrideredirect(True)
            toast.attributes("-topmost", True)
            toast.configure(bg="#222")
            self._toast = toast

        # Pick color based on level
        colors = {
            "info": "#2E86C1",
            "success": "#27AE60",
            "warning": "#F39C12",
            "error": "#C0392B"
        }
        color = colors.get(level, "#2E86C1")

        text = message if detail is None else f"{message}\n{detail}"

        label = tk.Label(
            toast,
            text=text,
            bg=color,
            fg="white",
            font=("Segoe UI", 10, "bold"),
            padx=15,
            pady=8
        )
        label.pack(fill="x")

        # Place in bottom-right corner relative to main window
        self.update_idletasks()
        x = self.winfo_rootx() + self.winfo_width() - 320
        y = self.winfo_rooty() + self.winfo_height() - 80
        toast.geometry(f"300x40+{x}+{y}")

        toast.after(2500, toast.destroy)



    #sorting by columns
    def treeview_sort_column(self, col, reverse):
        data = [(self.tree.set(k, col), k) for k in self.tree.get_children("")]
        data.sort(reverse=reverse)
        for index, (_, k) in enumerate(data):
            self.tree.move(k, "", index)
        self.tree.heading(col, command=lambda: self.treeview_sort_column(col, not reverse))


    #-------- Interactive Stuff ----------

    def _slugify(self, value: str, default: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value or "").strip("_")
        return cleaned.lower() or default

    def make_dataset_id(self, fit: dict) -> str:
        existing = {ds.get("id") for ds in fit.get("datasets", []) if isinstance(ds, dict)}
        counter = len(existing) + 1
        while True:
            candidate = f"dataset_{counter}"
            if candidate not in existing:
                return candidate
            counter += 1

    def ensure_fit_defaults(self, fit: dict) -> dict:
        fit.setdefault("title", "New Fit")
        fit.setdefault("formula", "a*x + b")
        fit.setdefault("residuals", True)

        layout = fit.get("layout") if isinstance(fit.get("layout"), dict) else {}
        layout = layout.copy()
        layout.setdefault("rows", 1)
        layout.setdefault("columns", 1)
        layout.setdefault("share_x", False)
        layout.setdefault("share_y", False)
        layout.setdefault("show_legend", True)

        panes_raw = layout.get("panes") if isinstance(layout.get("panes"), list) else []
        panes: list[dict] = []
        seen = set()
        for idx, pane in enumerate(panes_raw):
            if not isinstance(pane, dict):
                continue
            pane_id = self._slugify(str(pane.get("id") or pane.get("name") or f"pane_{idx+1}"), f"pane_{idx+1}")
            if pane_id in seen:
                pane_id = f"{pane_id}_{idx+1}"
            seen.add(pane_id)
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
                    "title": fit.get("title", "New Fit"),
                    "legend": True,
                    "residuals": False,
                    "show_fit": True,
                    "xlabel": "X",
                    "ylabel": "Y",
                }
            )

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

        layout["panes"] = panes
        fit["layout"] = layout

        datasets_raw = fit.get("datasets") if isinstance(fit.get("datasets"), list) else []
        datasets: list[dict] = []
        pane_ids = {p["id"] for p in panes}
        if not datasets_raw:
            default_color = fit.get("color", "#1f77b4")
            datasets_raw = [
                {
                    "id": self.make_dataset_id(fit),
                    "label": "Dataset 1",
                    "datafile": fit.get("datafile", ""),
                    "pane": panes[0]["id"],
                    "style": {"mode": "linespoints", "line_color": default_color},
                    "error_bars": bool(fit.get("error_bars", False)),
                }
            ]

        seen_dataset_ids: set[str] = set()
        for idx, dataset in enumerate(datasets_raw):
            if not isinstance(dataset, dict):
                continue
            ds_id = self._slugify(str(dataset.get("id") or f"dataset_{idx+1}"), f"dataset_{idx+1}")
            if ds_id in seen_dataset_ids:
                ds_id = f"{ds_id}_{idx+1}"
            seen_dataset_ids.add(ds_id)
            style = dataset.get("style") if isinstance(dataset.get("style"), dict) else {}
            style = style.copy()
            style.setdefault("mode", "linespoints")
            if fit.get("color") and "line_color" not in style:
                style["line_color"] = fit["color"]
            style.setdefault("line_color", style.get("line_color", "#1f77b4"))
            pane = dataset.get("pane") if dataset.get("pane") in pane_ids else list(pane_ids)[0]
            datasets.append(
                {
                    "id": ds_id,
                    "label": dataset.get("label") or ds_id.title(),
                    "datafile": dataset.get("datafile", ""),
                    "pane": pane,
                    "style": style,
                    "error_bars": bool(dataset.get("error_bars", False)),
                }
            )

        fit["datasets"] = datasets

        if datasets:
            dataset_ids = {d["id"] for d in datasets}
            fit_dataset = fit.get("fit_dataset") or next(iter(dataset_ids))
            if fit_dataset not in dataset_ids:
                fit_dataset = next(iter(dataset_ids))
            residual_dataset = fit.get("residual_dataset") or fit_dataset
            if residual_dataset not in dataset_ids:
                residual_dataset = fit_dataset
            fit["fit_dataset"] = fit_dataset
            fit["residual_dataset"] = residual_dataset

        return fit

    def on_double_click(self, event):
        item_id = self.tree.focus()
        if not item_id:
            return
        index = self.tree.index(item_id)
        self.edit_fit(index)

    def add_fit(self):
        default_dataset_id = "dataset_1"
        new_fit = {
            "title": "New Fit",
            "formula": "a*x + b",
            "residuals": True,
            "color": "#1f77b4",
            "parameters": {"a": 1.0, "b": 1.0},
            "layout": {
                "rows": 2,
                "columns": 1,
                "share_x": True,
                "share_y": False,
                "show_legend": True,
                "panes": [
                    {"id": "main", "title": "Fit", "legend": True, "residuals": False, "show_fit": True},
                    {"id": "residuals", "title": "Residuals", "legend": False, "residuals": True, "show_fit": False},
                ],
            },
            "datasets": [
                {
                    "id": default_dataset_id,
                    "label": "Dataset 1",
                    "datafile": "",
                    "pane": "main",
                    "style": {"mode": "linespoints", "line_color": "#1f77b4", "line_width": 2, "point_type": 7},
                    "error_bars": False,
                }
            ],
            "fit_dataset": default_dataset_id,
            "residual_dataset": default_dataset_id,
        }
        self.config_data.setdefault("fits", []).append(new_fit)
        index = len(self.config_data["fits"]) - 1
        self.save_config()
        self.refresh_table()
        self.edit_fit(index)
        self.show_toast("➕ New fit added", level="info")

    def delete_fit(self):
        """Delete the currently selected fit from the list."""
        item_id = self.tree.focus()
        if not item_id:
            self.show_toast("⚠️ No fit selected", level="warning")
            return

        index = self.tree.index(item_id)
        fit = self.config_data["fits"][index]

        # direct deletion, no popup confirm
        del self.config_data["fits"][index]
        self.save_config()
        self.refresh_table()
        self.show_toast(f"🗑 Deleted '{fit.get('title', 'Unnamed Fit')}'", level="info")


    def edit_fit(self, index):
        """Open the edit window for a specific fit index."""
        fit = self.ensure_fit_defaults(self.config_data["fits"][index])
        edit_win = tk.Toplevel(self)
        edit_win.title(f"Edit Fit #{index + 1}")
        edit_win.geometry("760x760")
        edit_win.resizable(False, False)

        canvas = tk.Canvas(edit_win, width=720)
        scrollbar = tk.Scrollbar(edit_win, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw", width=700)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        canvas.bind_all("<MouseWheel>", lambda e: self._on_mousewheel(e, canvas))
        canvas.bind_all("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
        canvas.bind_all("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))

        # --- Basic settings
        tk.Label(scrollable_frame, text="Title:").pack(anchor="w", padx=10, pady=2)
        title_var = tk.StringVar(value=fit.get("title", ""))
        tk.Entry(scrollable_frame, textvariable=title_var).pack(fill="x", padx=10)

        tk.Label(scrollable_frame, text="Formula:").pack(anchor="w", padx=10, pady=2)
        formula_var = tk.StringVar(value=fit.get("formula", "a*x + b"))
        tk.Entry(scrollable_frame, textvariable=formula_var).pack(fill="x", padx=10)

        residuals_var = tk.BooleanVar(value=fit.get("residuals", True))
        tk.Checkbutton(scrollable_frame, text="Generate residual analysis", variable=residuals_var).pack(anchor="w", padx=10, pady=5)

        tk.Label(scrollable_frame, text="Fit line color:").pack(anchor="w", padx=10, pady=(5, 2))
        color_var = tk.StringVar(value=fit.get("color", "#1f77b4"))

        def choose_fit_color():
            color = colorchooser.askcolor(color_var.get())[1]
            if color:
                color_var.set(color)

        color_frame = tk.Frame(scrollable_frame)
        color_frame.pack(fill="x", padx=10)
        tk.Entry(color_frame, textvariable=color_var, width=12).pack(side="left")
        tk.Button(color_frame, text="🎨", command=choose_fit_color).pack(side="left", padx=5)

        # --- Layout controls
        layout = fit.get("layout", {})
        panes = layout.get("panes", [])
        layout_frame = tk.LabelFrame(scrollable_frame, text="Layout", padx=10, pady=10)
        layout_frame.pack(fill="x", padx=10, pady=10)

        rows_var = tk.IntVar(value=layout.get("rows", 1))
        cols_var = tk.IntVar(value=layout.get("columns", 1))
        share_x_var = tk.BooleanVar(value=layout.get("share_x", False))
        share_y_var = tk.BooleanVar(value=layout.get("share_y", False))
        legend_var = tk.BooleanVar(value=layout.get("show_legend", True))

        row_layout = tk.Frame(layout_frame)
        row_layout.pack(fill="x", pady=2)
        tk.Label(row_layout, text="Rows:").pack(side="left")
        tk.Spinbox(row_layout, from_=1, to=6, textvariable=rows_var, width=5).pack(side="left", padx=5)
        tk.Label(row_layout, text="Columns:").pack(side="left", padx=(15, 0))
        tk.Spinbox(row_layout, from_=1, to=6, textvariable=cols_var, width=5).pack(side="left", padx=5)

        tk.Checkbutton(layout_frame, text="Share X axis", variable=share_x_var).pack(anchor="w")
        tk.Checkbutton(layout_frame, text="Share Y axis", variable=share_y_var).pack(anchor="w")
        tk.Checkbutton(layout_frame, text="Show legends by default", variable=legend_var).pack(anchor="w")

        # --- Pane manager
        panes_frame = tk.LabelFrame(scrollable_frame, text="Panes", padx=10, pady=10)
        panes_frame.pack(fill="x", padx=10, pady=10)

        pane_vars: dict[str, dict[str, tk.Variable]] = {}
        current_pane_id = tk.StringVar(value=panes[0]["id"] if panes else "")

        pane_list = tk.Listbox(panes_frame, height=5)
        pane_list.grid(row=0, column=0, rowspan=6, sticky="nsew", padx=(0, 10))
        panes_frame.grid_columnconfigure(0, weight=1)

        pane_detail = tk.Frame(panes_frame)
        pane_detail.grid(row=0, column=1, sticky="nsew")

        tk.Label(pane_detail, text="Title:").grid(row=0, column=0, sticky="w")
        pane_title_var = tk.StringVar()
        tk.Entry(pane_detail, textvariable=pane_title_var).grid(row=0, column=1, sticky="ew", padx=5)

        pane_legend_var = tk.BooleanVar()
        pane_residual_var = tk.BooleanVar()
        pane_show_fit_var = tk.BooleanVar()
        pane_xlabel_var = tk.StringVar()
        pane_ylabel_var = tk.StringVar()

        tk.Checkbutton(pane_detail, text="Show legend", variable=pane_legend_var).grid(row=1, column=0, columnspan=2, sticky="w")
        tk.Checkbutton(pane_detail, text="Residual pane", variable=pane_residual_var).grid(row=2, column=0, columnspan=2, sticky="w")
        tk.Checkbutton(pane_detail, text="Draw fitted curve", variable=pane_show_fit_var).grid(row=3, column=0, columnspan=2, sticky="w")

        tk.Label(pane_detail, text="X label:").grid(row=4, column=0, sticky="w")
        tk.Entry(pane_detail, textvariable=pane_xlabel_var).grid(row=4, column=1, sticky="ew", padx=5)
        tk.Label(pane_detail, text="Y label:").grid(row=5, column=0, sticky="w")
        tk.Entry(pane_detail, textvariable=pane_ylabel_var).grid(row=5, column=1, sticky="ew", padx=5)

        pane_detail.grid_columnconfigure(1, weight=1)

        def build_pane_vars(pane_dict):
            pane_vars[pane_dict["id"]] = {
                "title": tk.StringVar(value=pane_dict.get("title", pane_dict["id"].title())),
                "legend": tk.BooleanVar(value=pane_dict.get("legend", True)),
                "residuals": tk.BooleanVar(value=pane_dict.get("residuals", False)),
                "show_fit": tk.BooleanVar(value=pane_dict.get("show_fit", not pane_dict.get("residuals", False))),
                "xlabel": tk.StringVar(value=pane_dict.get("xlabel", "")),
                "ylabel": tk.StringVar(value=pane_dict.get("ylabel", "")),
            }

        for pane in panes:
            build_pane_vars(pane)

        def refresh_pane_listbox():
            pane_list.delete(0, tk.END)
            for pane in panes:
                pane_list.insert(tk.END, f"{pane.get('title', pane['id'])} ({pane['id']})")

        def save_current_pane():
            pid = current_pane_id.get()
            if not pid:
                return
            pane = next((p for p in panes if p["id"] == pid), None)
            if not pane:
                return
            vars_map = pane_vars[pid]
            pane["title"] = vars_map["title"].get()
            pane["legend"] = bool(vars_map["legend"].get())
            pane["residuals"] = bool(vars_map["residuals"].get())
            pane["show_fit"] = bool(vars_map["show_fit"].get())
            pane["xlabel"] = vars_map["xlabel"].get() or None
            pane["ylabel"] = vars_map["ylabel"].get() or None

        def load_pane(pid: str):
            if pid not in pane_vars:
                return
            vars_map = pane_vars[pid]
            pane_title_var.set(vars_map["title"].get())
            pane_legend_var.set(vars_map["legend"].get())
            pane_residual_var.set(vars_map["residuals"].get())
            pane_show_fit_var.set(vars_map["show_fit"].get())
            pane_xlabel_var.set(vars_map["xlabel"].get())
            pane_ylabel_var.set(vars_map["ylabel"].get())

        def on_pane_select(event=None):
            selection = pane_list.curselection()
            if not selection:
                return
            new_pid = panes[selection[0]]["id"]
            save_current_pane()
            current_pane_id.set(new_pid)
            load_pane(new_pid)

        pane_list.bind("<<ListboxSelect>>", on_pane_select)

        def update_dataset_pane_choices():
            pass

        def sync_pane_vars_from_controls(*_):
            pid = current_pane_id.get()
            if not pid or pid not in pane_vars:
                return
            vars_map = pane_vars[pid]
            vars_map["title"].set(pane_title_var.get())
            vars_map["legend"].set(pane_legend_var.get())
            vars_map["residuals"].set(pane_residual_var.get())
            vars_map["show_fit"].set(pane_show_fit_var.get())
            vars_map["xlabel"].set(pane_xlabel_var.get())
            vars_map["ylabel"].set(pane_ylabel_var.get())
            refresh_pane_listbox()
            update_dataset_pane_choices()

        for var in [pane_title_var, pane_xlabel_var, pane_ylabel_var]:
            var.trace_add("write", sync_pane_vars_from_controls)
        for var in [pane_legend_var, pane_residual_var, pane_show_fit_var]:
            var.trace_add("write", sync_pane_vars_from_controls)

        def add_pane():
            save_current_pane()
            new_id = self._slugify(f"pane_{len(panes) + 1}", f"pane_{len(panes) + 1}")
            pane_dict = {"id": new_id, "title": f"Pane {len(panes) + 1}", "legend": True, "residuals": False, "show_fit": True}
            panes.append(pane_dict)
            build_pane_vars(pane_dict)
            refresh_pane_listbox()
            pane_list.selection_clear(0, tk.END)
            pane_list.selection_set(tk.END)
            on_pane_select()
            update_dataset_pane_choices()

        def remove_pane():
            if len(panes) <= 1:
                self.show_toast("At least one pane is required", level="warning")
                return
            selection = pane_list.curselection()
            if not selection:
                return
            idx_remove = selection[0]
            pane_id = panes[idx_remove]["id"]
            panes.pop(idx_remove)
            pane_vars.pop(pane_id, None)
            # Reassign datasets that referenced removed pane
            first_pane = panes[0]["id"]
            for ds in fit.get("datasets", []):
                if ds.get("pane") == pane_id:
                    ds["pane"] = first_pane
            refresh_pane_listbox()
            pane_list.selection_set(min(idx_remove, len(panes) - 1))
            on_pane_select()
            update_dataset_pane_choices()

        pane_button_frame = tk.Frame(panes_frame)
        pane_button_frame.grid(row=6, column=0, columnspan=2, pady=(10, 0), sticky="w")
        tk.Button(pane_button_frame, text="➕ Add Pane", command=add_pane).pack(side="left", padx=2)
        tk.Button(pane_button_frame, text="➖ Remove Pane", command=remove_pane).pack(side="left", padx=2)

        refresh_pane_listbox()
        if panes:
            pane_list.selection_set(0)
            load_pane(panes[0]["id"])

        # --- Dataset manager
        datasets_frame = tk.LabelFrame(scrollable_frame, text="Datasets", padx=10, pady=10)
        datasets_frame.pack(fill="x", padx=10, pady=10)

        datasets = fit.get("datasets", [])
        dataset_vars: dict[str, dict[str, tk.Variable]] = {}
        current_dataset_id = tk.StringVar(value=datasets[0]["id"] if datasets else "")
        fit_dataset_combo = None
        residual_dataset_combo = None

        dataset_list = tk.Listbox(datasets_frame, height=6)
        dataset_list.grid(row=0, column=0, rowspan=8, sticky="nsew", padx=(0, 10))
        datasets_frame.grid_columnconfigure(0, weight=1)

        dataset_detail = tk.Frame(datasets_frame)
        dataset_detail.grid(row=0, column=1, sticky="nsew")
        dataset_detail.grid_columnconfigure(1, weight=1)

        ds_label_var = tk.StringVar()
        tk.Label(dataset_detail, text="Label:").grid(row=0, column=0, sticky="w")
        tk.Entry(dataset_detail, textvariable=ds_label_var).grid(row=0, column=1, sticky="ew", padx=5)

        tk.Label(dataset_detail, text="Pane:").grid(row=1, column=0, sticky="w")
        ds_pane_var = tk.StringVar()
        ds_pane_combo = ttk.Combobox(dataset_detail, textvariable=ds_pane_var, state="readonly")
        ds_pane_combo.grid(row=1, column=1, sticky="ew", padx=5)

        tk.Label(dataset_detail, text="Data file:").grid(row=2, column=0, sticky="w")
        ds_data_var = tk.StringVar()
        data_entry_frame = tk.Frame(dataset_detail)
        data_entry_frame.grid(row=2, column=1, sticky="ew", padx=5)
        tk.Entry(data_entry_frame, textvariable=ds_data_var).pack(side="left", fill="x", expand=True)

        def browse_dataset_file():
            ds_id = current_dataset_id.get()
            if not ds_id:
                return
            file_path = filedialog.askopenfilename(
                title="Select data file",
                filetypes=[("Data files", "*.dat *.txt *.csv")]
            )
            if not file_path:
                return
            base_dir = os.path.dirname(os.path.abspath(__file__))
            data_dir = os.path.join(base_dir, "data")
            os.makedirs(data_dir, exist_ok=True)
            dest_path = os.path.join(data_dir, os.path.basename(file_path))
            try:
                if os.path.exists(dest_path) and os.path.samefile(file_path, dest_path):
                    rel_path = f"data/{os.path.basename(dest_path)}"
                else:
                    shutil.copy(file_path, dest_path)
                    rel_path = f"data/{os.path.basename(dest_path)}"
                ds_data_var.set(rel_path)
                dataset_vars[ds_id]["datafile"].set(rel_path)
                self.show_toast(f"📂 Imported {os.path.basename(dest_path)}", level="success")
            except Exception as exc:
                self.show_toast(f"❌ Copy failed: {exc}", level="error")

        tk.Button(data_entry_frame, text="📂", command=browse_dataset_file).pack(side="left", padx=5)

        tk.Label(dataset_detail, text="Style mode:").grid(row=3, column=0, sticky="w")
        ds_mode_var = tk.StringVar()
        ds_mode_combo = ttk.Combobox(dataset_detail, textvariable=ds_mode_var, state="readonly", values=["lines", "points", "linespoints"])
        ds_mode_combo.grid(row=3, column=1, sticky="ew", padx=5)

        tk.Label(dataset_detail, text="Line color:").grid(row=4, column=0, sticky="w")
        ds_color_var = tk.StringVar()
        ds_color_entry = tk.Entry(dataset_detail, textvariable=ds_color_var)
        ds_color_entry.grid(row=4, column=1, sticky="ew", padx=5)

        def choose_dataset_color():
            color = colorchooser.askcolor(ds_color_var.get())[1]
            if color:
                ds_color_var.set(color)

        tk.Button(dataset_detail, text="🎨", command=choose_dataset_color).grid(row=4, column=2, padx=5)

        tk.Label(dataset_detail, text="Line width:").grid(row=5, column=0, sticky="w")
        ds_lw_var = tk.DoubleVar(value=2.0)
        tk.Spinbox(dataset_detail, from_=0.5, to=10, increment=0.5, textvariable=ds_lw_var, width=6).grid(row=5, column=1, sticky="w", padx=5)

        tk.Label(dataset_detail, text="Point type:").grid(row=6, column=0, sticky="w")
        ds_pt_var = tk.IntVar(value=7)
        tk.Spinbox(dataset_detail, from_=0, to=15, textvariable=ds_pt_var, width=6).grid(row=6, column=1, sticky="w", padx=5)

        ds_error_var = tk.BooleanVar()
        tk.Checkbutton(dataset_detail, text="Use error bars (column 3)", variable=ds_error_var).grid(row=7, column=0, columnspan=2, sticky="w")

        def build_dataset_vars(ds_dict):
            style = ds_dict.get("style", {})
            dataset_vars[ds_dict["id"]] = {
                "label": tk.StringVar(value=ds_dict.get("label", ds_dict["id"].title())),
                "pane": tk.StringVar(value=ds_dict.get("pane")),
                "datafile": tk.StringVar(value=ds_dict.get("datafile", "")),
                "mode": tk.StringVar(value=style.get("mode", "linespoints")),
                "color": tk.StringVar(value=style.get("line_color", "#1f77b4")),
                "line_width": tk.DoubleVar(value=style.get("line_width", 2.0)),
                "point_type": tk.IntVar(value=style.get("point_type", 7)),
                "error_bars": tk.BooleanVar(value=ds_dict.get("error_bars", False)),
            }

        for ds in datasets:
            build_dataset_vars(ds)

        def refresh_dataset_list():
            dataset_list.delete(0, tk.END)
            for ds in datasets:
                dataset_list.insert(tk.END, f"{ds.get('label', ds['id'])} ({ds['id']})")

        def update_dataset_pane_choices():
            pane_choices = [p["id"] for p in panes]
            ds_pane_combo.configure(values=pane_choices)
            for ds_id, vars_map in dataset_vars.items():
                if vars_map["pane"].get() not in pane_choices and pane_choices:
                    vars_map["pane"].set(pane_choices[0])
            if pane_choices:
                current_choice = ds_pane_var.get()
                if current_choice not in pane_choices:
                    ds_pane_var.set(pane_choices[0])

        def refresh_dataset_controls():
            update_dataset_pane_choices()
            dataset_choices = [ds["id"] for ds in datasets]
            if fit_dataset_combo is not None:
                fit_dataset_combo.configure(values=dataset_choices)
            if residual_dataset_combo is not None:
                residual_dataset_combo.configure(values=dataset_choices)

        def save_current_dataset():
            ds_id = current_dataset_id.get()
            if not ds_id or ds_id not in dataset_vars:
                return
            ds_dict = next((d for d in datasets if d["id"] == ds_id), None)
            if not ds_dict:
                return
            vars_map = dataset_vars[ds_id]
            ds_dict["label"] = vars_map["label"].get()
            pane_choice = vars_map["pane"].get()
            if pane_choice not in [p["id"] for p in panes] and panes:
                pane_choice = panes[0]["id"]
            ds_dict["pane"] = pane_choice
            ds_dict["datafile"] = vars_map["datafile"].get()
            ds_dict["error_bars"] = bool(vars_map["error_bars"].get())
            style = {
                "mode": vars_map["mode"].get() or "linespoints",
            }
            color_val = vars_map["color"].get()
            if color_val:
                style["line_color"] = color_val
            lw_val = vars_map["line_width"].get()
            if lw_val and lw_val > 0:
                style["line_width"] = float(lw_val)
            pt_val = vars_map["point_type"].get()
            if pt_val:
                style["point_type"] = int(pt_val)
            ds_dict["style"] = style
            refresh_dataset_list()

        def load_dataset(ds_id: str):
            if ds_id not in dataset_vars:
                return
            vars_map = dataset_vars[ds_id]
            ds_label_var.set(vars_map["label"].get())
            ds_pane_var.set(vars_map["pane"].get())
            ds_data_var.set(vars_map["datafile"].get())
            ds_mode_var.set(vars_map["mode"].get())
            ds_color_var.set(vars_map["color"].get())
            ds_lw_var.set(vars_map["line_width"].get())
            ds_pt_var.set(vars_map["point_type"].get())
            ds_error_var.set(vars_map["error_bars"].get())

        def on_dataset_select(event=None):
            selection = dataset_list.curselection()
            if not selection:
                return
            new_id = datasets[selection[0]]["id"]
            save_current_dataset()
            current_dataset_id.set(new_id)
            load_dataset(new_id)

        dataset_list.bind("<<ListboxSelect>>", on_dataset_select)

        def sync_dataset_vars(*_):
            ds_id = current_dataset_id.get()
            if not ds_id or ds_id not in dataset_vars:
                return
            vars_map = dataset_vars[ds_id]
            vars_map["label"].set(ds_label_var.get())
            vars_map["pane"].set(ds_pane_var.get())
            vars_map["datafile"].set(ds_data_var.get())
            vars_map["mode"].set(ds_mode_var.get())
            vars_map["color"].set(ds_color_var.get())
            vars_map["line_width"].set(ds_lw_var.get())
            vars_map["point_type"].set(ds_pt_var.get())
            vars_map["error_bars"].set(ds_error_var.get())
            refresh_dataset_list()

        for var in [ds_label_var, ds_pane_var, ds_data_var, ds_mode_var, ds_color_var]:
            var.trace_add("write", sync_dataset_vars)
        for var in [ds_lw_var, ds_pt_var, ds_error_var]:
            var.trace_add("write", sync_dataset_vars)

        def add_dataset():
            save_current_dataset()
            new_id = self.make_dataset_id(fit)
            pane_choice = panes[0]["id"] if panes else "main"
            ds_dict = {
                "id": new_id,
                "label": f"Dataset {len(datasets) + 1}",
                "datafile": "",
                "pane": pane_choice,
                "style": {"mode": "linespoints", "line_color": color_var.get()},
                "error_bars": False,
            }
            datasets.append(ds_dict)
            build_dataset_vars(ds_dict)
            refresh_dataset_list()
            refresh_dataset_controls()
            dataset_list.selection_clear(0, tk.END)
            dataset_list.selection_set(tk.END)
            on_dataset_select()

        def remove_dataset():
            if len(datasets) <= 1:
                self.show_toast("At least one dataset is required", level="warning")
                return
            selection = dataset_list.curselection()
            if not selection:
                return
            idx_remove = selection[0]
            ds_id = datasets[idx_remove]["id"]
            datasets.pop(idx_remove)
            dataset_vars.pop(ds_id, None)
            # Update fit/residual dataset selection if needed
            if fit.get("fit_dataset") == ds_id:
                new_target = datasets[0]["id"]
                fit["fit_dataset"] = new_target
                fit_dataset_var.set(new_target)
            if fit.get("residual_dataset") == ds_id:
                new_resid = fit.get("fit_dataset")
                fit["residual_dataset"] = new_resid
                residual_dataset_var.set(new_resid)
            refresh_dataset_list()
            refresh_dataset_controls()
            dataset_list.selection_set(min(idx_remove, len(datasets) - 1))
            on_dataset_select()

        dataset_button_frame = tk.Frame(datasets_frame)
        dataset_button_frame.grid(row=8, column=0, columnspan=2, pady=(10, 0), sticky="w")
        tk.Button(dataset_button_frame, text="➕ Add Dataset", command=add_dataset).pack(side="left", padx=2)
        tk.Button(dataset_button_frame, text="➖ Remove Dataset", command=remove_dataset).pack(side="left", padx=2)

        refresh_dataset_list()
        update_dataset_pane_choices()
        if datasets:
            dataset_list.selection_set(0)
            load_dataset(datasets[0]["id"])

        # --- Fit target selection
        selector_frame = tk.LabelFrame(scrollable_frame, text="Fit Targets", padx=10, pady=10)
        selector_frame.pack(fill="x", padx=10, pady=10)

        tk.Label(selector_frame, text="Dataset used for fitting:").grid(row=0, column=0, sticky="w")
        fit_dataset_var = tk.StringVar(value=fit.get("fit_dataset"))
        fit_dataset_combo = ttk.Combobox(selector_frame, textvariable=fit_dataset_var, state="readonly")
        fit_dataset_combo.grid(row=0, column=1, sticky="ew", padx=5)

        tk.Label(selector_frame, text="Dataset used for residuals:").grid(row=1, column=0, sticky="w")
        residual_dataset_var = tk.StringVar(value=fit.get("residual_dataset"))
        residual_dataset_combo = ttk.Combobox(selector_frame, textvariable=residual_dataset_var, state="readonly")
        residual_dataset_combo.grid(row=1, column=1, sticky="ew", padx=5)

        selector_frame.grid_columnconfigure(1, weight=1)
        refresh_dataset_controls()

        # --- Parameters section
        tk.Label(scrollable_frame, text="Parameters:").pack(anchor="w", padx=10, pady=(10, 0))
        params_frame = tk.Frame(scrollable_frame)
        params_frame.pack(fill="x", padx=10)

        param_vars = {}

        def refresh_parameters():
            for widget in params_frame.winfo_children():
                widget.destroy()
            param_names = self.extract_parameters_from_formula(formula_var.get())
            existing_params = fit.get("parameters", {})
            if not param_names:
                tk.Label(params_frame, text="(No parameters detected)", fg="gray").pack(anchor="w")
                return
            for name in param_names:
                row = tk.Frame(params_frame)
                row.pack(fill="x", pady=2)
                tk.Label(row, text=f"{name}:").pack(side="left")
                val = existing_params.get(name, 1.0)
                var = tk.DoubleVar(value=val)
                tk.Entry(row, textvariable=var, width=10).pack(side="left", padx=5)
                param_vars[name] = var

        refresh_parameters()
        formula_var.trace_add("write", lambda *_: refresh_parameters())

        tk.Label(scrollable_frame, text=" ").pack()

        def save_and_close():
            save_current_pane()
            save_current_dataset()

            fit["title"] = title_var.get()
            fit["formula"] = formula_var.get()
            fit["residuals"] = residuals_var.get()
            fit["color"] = color_var.get()

            layout["rows"] = max(1, rows_var.get())
            layout["columns"] = max(1, cols_var.get())
            layout["share_x"] = share_x_var.get()
            layout["share_y"] = share_y_var.get()
            layout["show_legend"] = legend_var.get()

            updated_panes = []
            for pane in panes:
                vars_map = pane_vars[pane["id"]]
                updated_panes.append(
                    {
                        "id": pane["id"],
                        "title": vars_map["title"].get(),
                        "legend": bool(vars_map["legend"].get()),
                        "residuals": bool(vars_map["residuals"].get()),
                        "show_fit": bool(vars_map["show_fit"].get()),
                        "xlabel": vars_map["xlabel"].get() or None,
                        "ylabel": vars_map["ylabel"].get() or None,
                    }
                )
            layout["panes"] = updated_panes
            fit["layout"] = layout

            pane_ids = [p["id"] for p in updated_panes]
            for ds in datasets:
                vars_map = dataset_vars[ds["id"]]
                ds["label"] = vars_map["label"].get()
                pane_choice = vars_map["pane"].get()
                if pane_choice not in pane_ids and pane_ids:
                    pane_choice = pane_ids[0]
                ds["pane"] = pane_choice
                ds["datafile"] = vars_map["datafile"].get()
                ds["error_bars"] = bool(vars_map["error_bars"].get())
                style = {"mode": vars_map["mode"].get() or "linespoints"}
                color_val = vars_map["color"].get()
                if color_val:
                    style["line_color"] = color_val
                lw_val = vars_map["line_width"].get()
                if lw_val and lw_val > 0:
                    style["line_width"] = float(lw_val)
                pt_val = vars_map["point_type"].get()
                if pt_val:
                    style["point_type"] = int(pt_val)
                ds["style"] = style

            dataset_ids = [ds["id"] for ds in datasets]
            fit_id_choice = fit_dataset_var.get()
            if fit_id_choice not in dataset_ids:
                fit_id_choice = dataset_ids[0]
            resid_choice = residual_dataset_var.get()
            if resid_choice not in dataset_ids:
                resid_choice = fit_id_choice
            fit["fit_dataset"] = fit_id_choice
            fit["residual_dataset"] = resid_choice

            fit["parameters"] = {k: v.get() for k, v in param_vars.items()}

            self.save_config()
            self.refresh_table()
            self.show_toast(f"Saved '{fit['title']}'", level="info")
            edit_win.destroy()

        tk.Button(scrollable_frame, text="💾 Save", command=save_and_close, bg="#4CAF50", fg="white").pack(pady=15)

        edit_win.transient(self)
        canvas.yview_moveto(0)
        edit_win.grab_set()
        edit_win.wait_window()

    # --- Folder and execution ---------------------------------------------
    def select_folder(self):
        folder = filedialog.askdirectory(title="Select Data Folder")
        if folder:
            self.folder = folder
            self.show_toast(f"📂 Selected: {os.path.basename(folder)}", level="success")


    def run_batch(self):
        import subprocess, sys, threading, os

        config_path = os.path.join(os.getcwd(), "config.json")
        backend_script = os.path.join(os.getcwd(), "plot_manager.py")

        if not os.path.exists(backend_script):
            self.show_toast("❌ Backend script not found (plot_manager.py)", level="error")
            return

        self.save_config()
        self.show_toast("🚀 Starting batch generation...", level="info")
        self.log_text.delete("1.0", tk.END)
        self.progress.config(mode="indeterminate")
        self.progress.start(10)

        def run_backend():
            try:
                process = subprocess.Popen(
                    [sys.executable, backend_script, config_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True
                )
                for line in iter(process.stdout.readline, ""):
                    self.log_text.insert("end", line)
                    self.log_text.see("end")
                    self.update_idletasks()  # keeps UI responsive
                process.wait()

                if process.returncode == 0:
                    self.show_toast("✅ Batch completed successfully", level="success")
                else:
                    self.show_toast("❌ Batch failed (see log)", level="error")

            except Exception as e:
                self.log_text.insert("end", f"\n⚠️ Exception: {e}\n")
                self.show_toast("⚠️ Backend error (see log)", level="error")

            finally:
                self.progress.stop()
                self.progress.config(mode="determinate", value=0)

        threading.Thread(target=run_backend, daemon=True).start()



    def open_latest_report(self):
        outputs_path = "outputs"
        if not os.path.exists(outputs_path):
            self.show_toast("Warning", "No output folder found.", level="error")
            return
        latest = sorted(os.listdir(outputs_path))[-1]
        report = os.path.join(outputs_path, latest, "report.pdf")
        if os.path.exists(report):
            try:
                system = platform.system()
                if system == "Windows":
                    os.startfile(report)
                elif system == "Darwin":
                    subprocess.run(["open", report], check=False)
                else:
                    opener = shutil.which("xdg-open")
                    if opener:
                        subprocess.run([opener, report], check=False)
                    else:
                        webbrowser.open(f"file://{os.path.abspath(report)}")
            except Exception as exc:
                self.show_toast("Warning", f"Could not open report automatically: {exc}", level="warning")
                return
        else:
            self.show_toast("Warning", "No report.pdf found in latest output.", level="warning")

    # --- Helpers -----------------------------------------------------------
    def log(self, msg):
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")

    def extract_parameters_from_formula(self, formula: str):
        """
        Extracts parameter names from the formula, supporting Latin and Greek-style names.
        Skips 'x', numbers, and common math functions.
        """
        blacklist = {"x", "sin", "cos", "tan", "exp", "log", "sqrt", "np", "math"}

        # Allow Latin and Greek letters (α, β, γ, …) and underscores
        tokens = re.findall(r"[A-Za-zα-ωΑ-Ω_][A-Za-z0-9α-ωΑ-Ω_]*", formula)
        params = sorted(set(t for t in tokens if t not in blacklist))
        return params


if __name__ == "__main__":
    app = PlotinatorApp()
    app.mainloop()
