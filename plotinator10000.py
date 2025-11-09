import tkinter as tk
from tkinter import ttk, messagebox, filedialog, colorchooser, simpledialog
import subprocess, os, json, threading, platform, webbrowser
import ttkbootstrap as ttkb  # pip install ttkbootstrap
import shutil
import re
import math
import numpy as np
import matplotlib

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
import matplotlib.image as mpimg
from ttkbootstrap.constants import *


CONFIG_PATH = "config.json"

MATH_FUNCS = {name: getattr(math, name) for name in dir(math) if not name.startswith("_")}
SAFE_EVAL_GLOBALS = {"__builtins__": {}, "np": np, "math": math}
SAFE_EVAL_GLOBALS.update(MATH_FUNCS)

class PlotinatorApp(ttkb.Window):
    def __init__(self):
        super().__init__(themename="superhero")
        self.title("Plotinator 100000")
        self.geometry("1500x900")
        self.resizable(True, True)

        self.folder = None
        self.config_data = {}
        self.preview_payload = None
        self.current_preview_manual = None
        self.preview_has_content = False
        self._preview_after_id = None

        self.create_widgets()  # creates self.tree
        self.tree.bind("<Double-1>", self.on_double_click)  # bind AFTER creation
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
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
            ("🗑 Delete Fit", self.delete_fit, "danger-outline"),
            ("👁 Preview Fit", self.preview_selected_fit, "primary")
        ]
        for i, (txt, cmd, style) in enumerate(buttons):
            ttkb.Button(toolbar, text=txt, command=cmd, bootstyle=style).grid(row=0, column=i, padx=6)

        # --- Content area ---
        content = ttkb.Frame(self)
        content.pack(fill="both", expand=True)

        # --- Left column: table + logs ---
        left_column = ttkb.Frame(content, padding=10)
        left_column.pack(side="left", fill="both", expand=True)

        table_frame = ttkb.Frame(left_column)
        table_frame.pack(fill="both", expand=True)

        self.tree = ttkb.Treeview(
            table_frame,
            columns=("Title", "Formula", "Data", "Residuals"),
            show="headings",
            height=15,
            bootstyle="info"
        )
        for col, width in [("Title", 180), ("Formula", 260), ("Data", 220), ("Residuals", 80)]:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=(0, 10))

        # Zebra stripes
        self.style.configure("Treeview", rowheight=30)
        self.tree.tag_configure("odd", background="#222831")
        self.tree.tag_configure("even", background="#1c1f26")

        # --- Progress + Log Console ---
        self.progress = ttkb.Progressbar(left_column, mode="determinate", bootstyle="info-striped")
        self.progress.pack(fill="x", pady=(0, 10))

        self.log_text = tk.Text(left_column, height=10, bg="#101820", fg="#39FF14", insertbackground="#39FF14",
                                font=("Consolas", 10), relief="flat", borderwidth=6,
                                highlightthickness=1, highlightbackground="#3fa9f5")
        self.log_text.pack(fill="both", expand=True)

        # --- Right column: live preview ---
        preview_column = ttkb.Frame(content, padding=10, width=420)
        preview_column.pack(side="right", fill="both", expand=False)

        preview_container = ttkb.Labelframe(preview_column, text="Live Preview", padding=10, bootstyle="info")
        preview_container.pack(fill="both", expand=True)

        controls = ttkb.Frame(preview_container)
        controls.pack(fill="x", pady=(0, 10))

        self.preview_mode = tk.StringVar(value="plot")

        mode_frame = ttkb.Frame(controls)
        mode_frame.pack(side="left", padx=5)

        self.preview_plot_button = ttkb.Radiobutton(
            mode_frame,
            text="Fit",
            variable=self.preview_mode,
            value="plot",
            bootstyle="info-toolbutton",
            command=self.refresh_preview_canvas
        )
        self.preview_plot_button.pack(side="left", padx=2)

        self.preview_residual_button = ttkb.Radiobutton(
            mode_frame,
            text="Residuals",
            variable=self.preview_mode,
            value="residuals",
            bootstyle="info-toolbutton",
            command=self.refresh_preview_canvas
        )
        self.preview_residual_button.pack(side="left", padx=2)

        button_frame = ttkb.Frame(controls)
        button_frame.pack(side="right")

        ttkb.Button(button_frame, text="🔄 Refresh", command=self.preview_selected_fit, bootstyle="primary-outline").pack(side="left", padx=4)
        ttkb.Button(button_frame, text="📸 Snapshot", command=self.export_snapshot, bootstyle="success-outline").pack(side="left", padx=4)
        ttkb.Button(button_frame, text="🧹 Clear", command=self.clear_preview, bootstyle="secondary-outline").pack(side="left", padx=4)

        self.preview_status_var = tk.StringVar(value="No preview loaded")
        ttkb.Label(preview_container, textvariable=self.preview_status_var, anchor="w", bootstyle="light").pack(fill="x", pady=(0, 5))

        canvas_frame = ttkb.Frame(preview_container)
        canvas_frame.pack(fill="both", expand=True)

        self.preview_fig = Figure(figsize=(5, 4), dpi=100)
        self.preview_canvas = FigureCanvasTkAgg(self.preview_fig, master=canvas_frame)
        self.preview_toolbar = NavigationToolbar2Tk(self.preview_canvas, canvas_frame, pack_toolbar=False)
        self.preview_toolbar.update()
        self.preview_toolbar.pack(fill="x", pady=(0, 5))
        self.preview_canvas.get_tk_widget().pack(fill="both", expand=True)

        self.clear_preview()

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
            self.show_toast("Config error", f"Could not read config.json:\n{e}" , level="error")
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
            self.show_toast("Config warning", "config.json has no 'fits' or 'plots'. Starting with an empty list.",level="warning")

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
            title = fit.get("title", "")
            formula = fit.get("formula", "")
            datafile = os.path.basename(fit.get("datafile", ""))  # cleaner filename only
            residuals = "✅" if fit.get("residuals", False) else "❌"
            self.tree.insert("", "end", values=(title, formula, datafile, residuals))


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

    def show_toast(self, message, level="info"):
        """Display a single floating toast message (auto-destroys after 2s)."""
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

        label = tk.Label(
            toast,
            text=message,
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

    def on_double_click(self, event):
        item_id = self.tree.focus()
        if not item_id:
            return
        index = self.tree.index(item_id)
        self.edit_fit(index)

    def add_fit(self):
        new_fit = {
            "title": "New Fit",
            "formula": "a*x + b",
            "datafile": "",
            "residuals": True,
            "color": "#1f77b4",
            "parameters": {"a": 1.0, "b": 1.0}
        }
        self.config_data.setdefault("fits", []).append(new_fit)
        index = len(self.config_data["fits"]) - 1
        self.save_config()
        self.refresh_table()
        self.edit_fit(index)
        self.show_toast("➕ New fit added",level="info")

    def delete_fit(self):
        """Delete the currently selected fit from the list."""
        item_id = self.tree.focus()
        if not item_id:
            self.show_toast("⚠️ No fit selected" , level="warning")
            return

        index = self.tree.index(item_id)
        fit = self.config_data["fits"][index]

        # direct deletion, no popup confirm
        del self.config_data["fits"][index]
        self.save_config()
        self.refresh_table()
        self.show_toast(f"🗑 Deleted '{fit.get('title', 'Unnamed Fit')}'", level="info")


    # --- Preview handling -------------------------------------------------
    def on_tree_select(self, _event=None):
        if self._preview_after_id:
            self.after_cancel(self._preview_after_id)
        self._preview_after_id = self.after(160, self.preview_selected_fit)

    def _set_residual_availability(self, available: bool):
        state = "normal" if available else "disabled"
        try:
            self.preview_residual_button.config(state=state)
        except Exception:
            return
        if not available and self.preview_mode.get() == "residuals":
            self.preview_mode.set("plot")

    def _render_empty_preview(self, message: str = "No preview loaded"):
        if not hasattr(self, "preview_fig"):
            return
        self.preview_fig.clear()
        ax = self.preview_fig.add_subplot(111)
        ax.axis("off")
        ax.text(0.5, 0.5, message, ha="center", va="center", transform=ax.transAxes, color="#8a9aa9", fontsize=12)
        self.preview_canvas.draw_idle()
        self.preview_toolbar.update()
        self.preview_has_content = False

    def clear_preview(self):
        self.preview_payload = None
        self.current_preview_manual = None
        self.preview_has_content = False
        self._set_residual_availability(False)
        self.preview_status_var.set("No preview loaded")
        self._render_empty_preview()

    def refresh_preview_canvas(self):
        if self.preview_payload:
            self._render_payload_preview()
        elif self.current_preview_manual:
            self._render_manual_preview()
        else:
            self._render_empty_preview()

    def _render_payload_preview(self):
        payload = self.preview_payload or {}
        mode = self.preview_mode.get()
        path_key = "residuals_path" if mode == "residuals" else "plot_path"
        path = payload.get(path_key)
        if not path or not os.path.exists(path):
            fallback = payload.get("plot_path")
            if fallback and os.path.exists(fallback):
                self.preview_mode.set("plot")
                path = fallback
            else:
                self.preview_has_content = False
                self._render_empty_preview("Preview image not available yet")
                return

        try:
            image = mpimg.imread(path)
        except Exception as exc:
            self.preview_has_content = False
            self._render_empty_preview(f"Failed to load preview:\n{exc}")
            return

        self.preview_fig.clear()
        ax = self.preview_fig.add_subplot(111)
        ax.imshow(image)
        ax.axis("off")
        title = payload.get("title") or os.path.basename(path)
        ax.set_title(title, color="#dbe9ff", fontsize=11)
        self.preview_fig.tight_layout()
        self.preview_canvas.draw_idle()
        self.preview_toolbar.update()
        self.preview_has_content = True
        residual_available = bool(payload.get("residuals_path") and os.path.exists(payload.get("residuals_path")))
        self._set_residual_availability(residual_available)

    def _render_manual_preview(self):
        data = self.current_preview_manual or {}
        mode = self.preview_mode.get()
        residuals = data.get("residuals")

        if mode == "residuals" and residuals is None:
            self.preview_mode.set("plot")
            mode = "plot"

        self.preview_fig.clear()
        ax = self.preview_fig.add_subplot(111)

        if mode == "residuals" and residuals is not None:
            ax.axhline(0.0, color="#8899aa", linestyle="--", linewidth=1)
            ax.scatter(data.get("x"), residuals, color="#ff7f50", s=30, label="Residuals")
            ax.set_ylabel("y - f(x)")
            ax.set_xlabel("x")
            ax.grid(alpha=0.25)
        else:
            if data.get("yerr") is not None:
                ax.errorbar(data.get("x"), data.get("y"), yerr=data.get("yerr"), fmt="o", color="#1f77b4", ecolor="#4aa6ff", capsize=3, label="Data ±σ")
            else:
                ax.scatter(data.get("x"), data.get("y"), color="#1f77b4", s=36, label="Data")

            if data.get("x_curve") is not None and data.get("y_curve") is not None:
                ax.plot(data.get("x_curve"), data.get("y_curve"), color=data.get("line_color", "#ff7f0e"), linewidth=2, label="Fit curve")

            ax.set_xlabel("x")
            ax.set_ylabel("y")
            ax.grid(alpha=0.25)

        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(loc="best")

        self.preview_fig.tight_layout()
        self.preview_canvas.draw_idle()
        self.preview_toolbar.update()
        self.preview_has_content = True
        self._set_residual_availability(residuals is not None)

    def handle_preview_payload(self, payload: dict):
        self.preview_payload = payload
        self.current_preview_manual = None
        title = payload.get("title", "")
        self.preview_status_var.set(f"Batch preview: {title}")
        self.refresh_preview_canvas()

    def preview_selected_fit(self, _event=None):
        self._preview_after_id = None
        item_id = self.tree.focus()
        if not item_id:
            selection = self.tree.selection()
            if selection:
                item_id = selection[0]
        if not item_id:
            return

        index = self.tree.index(item_id)
        fits = self.config_data.get("fits", [])
        if index >= len(fits):
            return

        fit = fits[index]
        datafile = fit.get("datafile")
        if not datafile:
            self.preview_status_var.set("Preview unavailable: missing data file")
            self._set_residual_availability(False)
            self._render_empty_preview("Select a data file to preview")
            return

        if not os.path.isabs(datafile):
            datafile = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), datafile))

        if not os.path.exists(datafile):
            self.preview_status_var.set("Preview unavailable: data file not found")
            self._set_residual_availability(False)
            self._render_empty_preview("Data file not found")
            return

        def worker():
            try:
                data = np.loadtxt(datafile, ndmin=2)
            except Exception as exc:
                self.after(0, lambda: self.show_toast(f"⚠️ Preview load error: {exc}", level="warning"))
                self.after(0, lambda: self._render_empty_preview("Failed to load data"))
                return

            if data.shape[1] < 2:
                self.after(0, lambda: self._render_empty_preview("Data must have at least two columns"))
                return

            x = data[:, 0]
            y = data[:, 1]
            yerr = data[:, 2] if data.shape[1] >= 3 else None

            params = {}
            for key, value in (fit.get("parameters") or {}).items():
                try:
                    params[key] = float(value)
                except (TypeError, ValueError):
                    continue

            formula = fit.get("formula") or "a*x + b"
            for name in self.extract_parameters_from_formula(formula):
                params.setdefault(name, 1.0)

            try:
                dense_x = np.linspace(np.min(x), np.max(x), 400)
            except ValueError:
                dense_x = x

            try:
                locals_env = params.copy()
                locals_env["x"] = dense_x
                y_curve = np.array(eval(formula, SAFE_EVAL_GLOBALS, locals_env), dtype=float)

                locals_env = params.copy()
                locals_env["x"] = x
                y_fit = np.array(eval(formula, SAFE_EVAL_GLOBALS, locals_env), dtype=float)
            except Exception as exc:
                self.after(0, lambda: self.show_toast(f"⚠️ Preview formula error: {exc}", level="warning"))
                self.after(0, lambda: self._render_empty_preview("Formula could not be evaluated"))
                return

            residuals = y - y_fit if y_fit.shape == y.shape else None

            payload = {
                "title": fit.get("title", "Preview"),
                "x": x,
                "y": y,
                "yerr": yerr,
                "x_curve": dense_x,
                "y_curve": y_curve,
                "residuals": residuals,
                "line_color": fit.get("color", "#ff7f0e"),
            }

            self.after(0, lambda p=payload: self._handle_manual_preview_ready(p))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_manual_preview_ready(self, payload: dict):
        self.current_preview_manual = payload
        self.preview_payload = None
        self.preview_mode.set(self.preview_mode.get())  # keep current selection
        self.preview_status_var.set(f"Config preview: {payload.get('title', 'Preview')}")
        self.refresh_preview_canvas()

    def export_snapshot(self):
        if not self.preview_has_content:
            self.show_toast("⚠️ No preview to export", level="warning")
            return

        filetypes = [("PNG", "*.png"), ("PDF", "*.pdf"), ("SVG", "*.svg")]
        path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=filetypes, title="Export preview snapshot")
        if not path:
            return

        try:
            self.preview_fig.savefig(path, dpi=300)
        except Exception as exc:
            self.show_toast(f"❌ Snapshot failed: {exc}", level="error")
        else:
            self.show_toast(f"📸 Snapshot saved: {os.path.basename(path)}", level="success")

    def _reset_progress(self):
        self.progress.stop()
        self.progress.config(mode="determinate", value=0)


    def edit_fit(self, index):
        """Open the edit window for a specific fit index."""
        fit = self.config_data["fits"][index]
        edit_win = tk.Toplevel(self)
        edit_win.title(f"Edit Fit #{index + 1}")
        edit_win.geometry("600x600")
        edit_win.resizable(False, False)

        # --- Scrollable container setup ---
        canvas = tk.Canvas(edit_win)
        scrollbar = tk.Scrollbar(edit_win, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas)

        # Bind size of inner frame to scroll region
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        # Place the inner frame inside the canvas
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw", width=400)
        canvas.configure(yscrollcommand=scrollbar.set)

        # Layout
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")


        # Bind scroll events (Windows / Mac)
        canvas.bind_all("<MouseWheel>", lambda e: self._on_mousewheel(e, canvas))  # Windows
        canvas.bind_all("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))  # Linux scroll up
        canvas.bind_all("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))   # Linux scroll down


        # --- Title
        tk.Label(scrollable_frame, text="Title:").pack(anchor="w", padx=10, pady=2)
        title_var = tk.StringVar(value=fit.get("title", ""))
        tk.Entry(scrollable_frame, textvariable=title_var).pack(fill="x", padx=10)

        # --- Formula
        tk.Label(scrollable_frame, text="Formula:").pack(anchor="w", padx=10, pady=2)
        formula_var = tk.StringVar(value=fit.get("formula", "a*x+b"))
        tk.Entry(scrollable_frame, textvariable=formula_var).pack(fill="x", padx=10)

        # --- Data file
        tk.Label(scrollable_frame, text="Data file:").pack(anchor="w", padx=10, pady=2)
        data_var = tk.StringVar(value=fit.get("datafile", ""))

        def browse_file():
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

            # If file is already inside data/, skip the copy
            try:
                if os.path.samefile(file_path, dest_path):
                    rel_path = f"data/{os.path.basename(dest_path)}"
                    data_var.set(rel_path)
                    fit["datafile"] = rel_path
                    self.show_toast(f"📄 Using existing file: {os.path.basename(dest_path)}", level="info")
                    return

                shutil.copy(file_path, dest_path)
                rel_path = f"data/{os.path.basename(dest_path)}"
                data_var.set(rel_path)
                fit["datafile"] = rel_path
                self.show_toast(f"📂 Imported {os.path.basename(dest_path)}", level="success")

            except Exception as e:
                self.show_toast(f"❌ Copy failed: {e}", level="error")




        frame = tk.Frame(scrollable_frame)
        frame.pack(fill="x", padx=10)
        tk.Entry(frame, textvariable=data_var).pack(side="left", fill="x", expand=True)
        tk.Button(frame, text="📂", command=browse_file).pack(side="left", padx=5)

        # --- Residuals
        residuals_var = tk.BooleanVar(value=fit.get("residuals", True))
        tk.Checkbutton(scrollable_frame, text="Generate residuals plot", variable=residuals_var).pack(anchor="w", padx=10, pady=5)

        # --- Color
        tk.Label(scrollable_frame, text="Color:").pack(anchor="w", padx=10, pady=2)
        color_var = tk.StringVar(value=fit.get("color", "#1f77b4"))

        def choose_color():
            color = colorchooser.askcolor(color_var.get())[1]
            if color:
                color_var.set(color)

        frame_color = tk.Frame(scrollable_frame)
        frame_color.pack(fill="x", padx=10)
        tk.Entry(frame_color, textvariable=color_var, width=10).pack(side="left")
        tk.Button(frame_color, text="🎨", command=choose_color).pack(side="left", padx=5)

        # --- Parameters ---
        tk.Label(scrollable_frame, text="Parameters:").pack(anchor="w", padx=10, pady=(10, 0))
        params_frame = tk.Frame(scrollable_frame)
        params_frame.pack(fill="x", padx=10)

        param_vars = {}

        def refresh_parameters():
            """Rebuild parameter entries based on formula contents."""
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

            # Smooth feedback toast
            self.show_toast("🔄 Parameters updated from formula" , level="info")

        # Initialize once
        refresh_parameters()

        # Automatically refresh when formula changes
        formula_var.trace_add("write", lambda *_: refresh_parameters())


        # --- Save button
        tk.Label(scrollable_frame, text=" ").pack()  # spacer before Save button
        def save_and_close():
            fit["title"] = title_var.get()
            fit["formula"] = formula_var.get()
            fit["datafile"] = data_var.get()
            fit["residuals"] = residuals_var.get()
            fit["color"] = color_var.get()
            self.save_config()
            self.refresh_table()
            self.show_toast(f"Saved '{fit['title']}'", level="info")
            edit_win.destroy()
            fit["parameters"] = {k: v.get() for k, v in param_vars.items()}


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
        self.preview_status_var.set("Awaiting batch previews...")

        def run_backend():
            try:
                process = subprocess.Popen(
                    [sys.executable, backend_script, config_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1
                )
                for line in iter(process.stdout.readline, ""):
                    stripped = line.rstrip()
                    if stripped.startswith("[PREVIEW]"):
                        try:
                            payload_json = stripped.split(" ", 1)[1]
                            payload = json.loads(payload_json)
                        except (IndexError, json.JSONDecodeError):
                            self.after(0, lambda msg=stripped: self.log(msg))
                        else:
                            self.after(0, lambda msg=stripped: self.log(msg))
                            self.after(0, lambda p=payload: self.handle_preview_payload(p))
                        continue

                    self.after(0, lambda msg=stripped: self.log(msg))
                process.wait()

                if process.returncode == 0:
                    self.after(0, lambda: self.show_toast("✅ Batch completed successfully", level="success"))
                else:
                    self.after(0, lambda: self.show_toast("❌ Batch failed (see log)", level="error"))

            except Exception as e:
                self.after(0, lambda: self.log(f"⚠️ Exception: {e}"))
                self.after(0, lambda: self.show_toast("⚠️ Backend error (see log)", level="error"))

            finally:
                self.after(0, self._reset_progress)

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
