from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import ttkbootstrap as ttkb
from ttkbootstrap.constants import *

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
        self._stop_log = threading.Event()

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
        columns = ("Title", "Formula", "Data", "Residuals")
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
            datafile = Path(fit.get("data_source", {}).get("path") or fit.get("datafile", "")).name
            residuals = "✅" if fit.get("residuals", True) else "❌"
            self.tree.insert(
                "",
                "end",
                values=(fit.get("title", ""), fit.get("formula", ""), datafile, residuals),
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
        data = fit.copy() if fit else {"title": "", "formula": "", "datafile": "", "residuals": True, "color": "#1f77b4"}
        editor = ttkb.Toplevel(self)
        editor.title("Fit details")
        editor.geometry("420x320")
        editor.grab_set()

        entries = {}
        for i, (label, key) in enumerate([
            ("Title", "title"),
            ("Formula", "formula"),
            ("Data file", "datafile"),
            ("Color", "color"),
        ]):
            ttkb.Label(editor, text=label).grid(row=i, column=0, sticky="w", padx=10, pady=6)
            entry = ttkb.Entry(editor)
            entry.grid(row=i, column=1, sticky="ew", padx=10, pady=6)
            entry.insert(0, data.get(key, ""))
            entries[key] = entry
        editor.columnconfigure(1, weight=1)

        residual_var = tk.BooleanVar(value=data.get("residuals", True))
        ttkb.Checkbutton(editor, text="Generate residual plot", variable=residual_var).grid(
            row=len(entries), column=0, columnspan=2, sticky="w", padx=10, pady=6
        )

        def _save() -> None:
            payload = {
                "title": entries["title"].get().strip() or "Untitled",
                "formula": entries["formula"].get().strip() or "a*x + b",
                "datafile": entries["datafile"].get().strip(),
                "color": entries["color"].get().strip() or "#1f77b4",
                "residuals": residual_var.get(),
            }
            self._ensure_fit_defaults(payload)
            if index is None:
                self.config_data.setdefault("fits", []).append(payload)
            else:
                self.config_data["fits"][index] = payload
            self.refresh_table()
            editor.destroy()

        buttons = ttkb.Frame(editor)
        buttons.grid(row=len(entries) + 1, column=0, columnspan=2, pady=10)
        ttkb.Button(buttons, text="Cancel", command=editor.destroy).pack(side="right", padx=5)
        ttkb.Button(buttons, text="Save", command=_save, bootstyle="success").pack(side="right", padx=5)

    # ------------------------------------------------------------------
    def _ensure_fit_defaults(self, fit: dict) -> None:
        fit.setdefault("title", "Untitled")
        fit.setdefault("formula", "a*x + b")
        fit.setdefault("residuals", True)
        fit.setdefault("color", "#1f77b4")
        data_source = fit.setdefault("data_source", {})
        if "path" not in data_source:
            data_source["path"] = fit.get("datafile", "")
        columns = data_source.get("columns")
        if not isinstance(columns, dict):
            columns = {}
        data_source["columns"] = {
            "x": int(columns.get("x", 1) or 1),
            "y": int(columns.get("y", 2) or 2),
            "error": columns.get("error"),
            "weight": columns.get("weight"),
        }
        data_source.setdefault("preprocessing", [])

    # ------------------------------------------------------------------
    def run_batch(self) -> None:
        if self.runner_thread and self.runner_thread.is_alive():
            messagebox.showinfo("Batch running", "A batch is already running")
            return

        self.save_config()
        self.progress.configure(value=0)
        self.log_text.delete("1.0", tk.END)
        self._stop_log.clear()

        def _runner() -> None:
            cmd = [sys.executable, "plot_manager.py", CONFIG_PATH]
            try:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
            except OSError as exc:
                self._append_log(f"Failed to start plot_manager.py: {exc}\n")
                return

            for line in process.stdout:
                if self._stop_log.is_set():
                    break
                self._append_log(line)
            process.wait()
            self.progress.configure(value=100)
            self._append_log("\n[DONE] Batch finished.\n")

        self.runner_thread = threading.Thread(target=_runner, daemon=True)
        self.runner_thread.start()

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
