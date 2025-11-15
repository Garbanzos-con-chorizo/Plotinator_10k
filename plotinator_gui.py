from __future__ import annotations

import copy
import json
import math
import queue
import re
import shutil
import sys
import threading
import tkinter as tk
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
from typing import Any, Callable, Sequence

import ttkbootstrap as ttkb

from config import ConfigError, FitConfig, PlotinatorConfig, load_config
from engine import run_batch as engine_run_batch
from plotinator import __version__ as PACKAGE_VERSION
from plotinator.project import ProjectManager, PlotinatorProject, TEMP_PROJECT_FOLDER
from plotinator.ui.workspace import WorkspaceState
from plotinator.update_checker import ReleaseInfo, UpdateChecker, UpdateResult
from plotinator.project import PlotinatorProject, ProjectManager, ProjectMetadata, ProjectPaths

CONFIG_PATH = "config.json"

_TOAST_COLORS: dict[str, str] = {
    "info": "#2E86C1",
    "success": "#27AE60",
    "warning": "#F39C12",
    "error": "#C0392B",
}


def _show_toast(widget: tk.Misc, message: str, level: str = "info") -> None:
    """Display a temporary notification near the widget's toplevel window."""

    try:
        anchor: tk.Misc = widget if isinstance(widget, tk.Tk) else widget.winfo_toplevel()
    except tk.TclError:
        return

    def _create_toast() -> None:
        toast = tk.Toplevel(anchor)
        toast.overrideredirect(True)
        toast.configure(bg=_TOAST_COLORS.get(level, _TOAST_COLORS["info"]))
        ttkb.Label(toast, text=message, bootstyle="inverse", padding=10).pack()
        anchor.update_idletasks()
        x = anchor.winfo_rootx() + anchor.winfo_width() - 260
        y = anchor.winfo_rooty() + anchor.winfo_height() - 100
        toast.geometry(f"240x60+{x}+{y}")
        toast.after(2500, toast.destroy)

    try:
        anchor.after(0, _create_toast)
    except tk.TclError:
        _create_toast()


tk.Misc.show_toast = _show_toast


class BatchWorker:
    """Background helper to execute engine runs and forward structured events."""

    def __init__(self, config_path: Path) -> None:
        self.config_path = Path(config_path)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._events: queue.Queue[dict[str, Any]] | None = None
        self._job_error_emitted = False

    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> queue.Queue[dict[str, Any]]:
        if self.is_running():
            raise RuntimeError("Batch already running")

        self._events = queue.Queue()
        self._stop_event.clear()
        self._job_error_emitted = False

        class _BatchCancelled(Exception):
            """Internal sentinel used to abort the engine runner."""

            pass

        def _push_event(event: dict[str, Any]) -> None:
            if self._stop_event.is_set():
                raise _BatchCancelled
            if event.get("type") == "job-error":
                self._job_error_emitted = True
            assert self._events is not None
            self._events.put(event)

        def _runner() -> None:
            try:
                engine_run_batch(str(self.config_path), on_event=_push_event)
            except _BatchCancelled:
                if self._events is not None:
                    self._events.put({"type": "job-cancelled"})
            except Exception as exc:  # noqa: BLE001 - surfaced through events
                if not self._job_error_emitted and self._events is not None:
                    self._events.put({"type": "job-exception", "error": str(exc)})
            finally:
                self._thread = None

        self._thread = threading.Thread(target=_runner, daemon=True)
        self._thread.start()
        return self._events

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join()
        self._thread = None
        self._stop_event.clear()

class PlotinatorApp(ttkb.Window):
    """Simple desktop helper for editing Plotinator config files."""

    def __init__(self) -> None:
        super().__init__(themename="superhero")
        self._base_window_title = f"Plotinator Open Beta v{PACKAGE_VERSION}"
        self.title(self._base_window_title)
        self.geometry("1200x800")
        self.resizable(True, True)

        base_style = getattr(self, "style", None)
        self._style = base_style if isinstance(base_style, ttkb.Style) else ttkb.Style()
        self.folder: Path | None = None
        self.config_path = Path(CONFIG_PATH).resolve()
        self.job: PlotinatorConfig = PlotinatorConfig(base_path=self.config_path.parent, fits=[])
        self._project_manager = ProjectManager()
        self._project: PlotinatorProject | None = None
        self._app_state = WorkspaceState.load()
        self._autosave_after_id: str | None = None
        self._autosave_in_progress = False
        self._autosave_error_dialog: ttkb.Toplevel | None = None
        self._autosave_last_error: str | None = None
        self._autosave_error_message = tk.StringVar(self, value="")
        self._recent_menu: tk.Menu | None = None
        self._worker: BatchWorker | None = None
        self._event_queue: queue.Queue[dict[str, Any]] | None = None
        self._progress_total = 0
        self._progress_completed = 0
        self.status_var = tk.StringVar(self, value="Idle")
        self._update_checker = UpdateChecker(
            owner="plotinator-labs",
            repo="Plotinator_10k",
            current_version=PACKAGE_VERSION,
        )
        self._update_status_var = tk.StringVar(self, value=self._format_update_status())
        self._settings_window: ttkb.Toplevel | None = None
        self._images: dict[str, tk.PhotoImage] = {}
        self._content_paned: ttkb.Panedwindow | None = None
        self._preview_container: ttkb.Frame | None = None
        self._preview_header_var = tk.StringVar(self, value="Preview")
        self._preview_notebook: ttkb.Notebook | None = None
        self._preview_plot_tab: ttkb.Frame | None = None
        self._preview_canvas: tk.Canvas | None = None
        self._preview_canvas_image: int | None = None
        self._preview_canvas_message: int | None = None
        self._preview_residual_label: ttkb.Label | None = None
        self._preview_summary_vars: dict[str, tk.StringVar] = {}
        self._preview_photo_main: tk.PhotoImage | None = None
        self._preview_photo_residual: tk.PhotoImage | None = None
        self._preview_active_temp_dir: Path | None = None
        self._preview_stale_temp_dirs: set[Path] = set()
        self._preview_pane_visible = False
        self._preview_history: list[dict[str, Any]] = []
        self._preview_history_index: int | None = None
        self._preview_history_limit = 5
        self._preview_prev_button: ttkb.Button | None = None
        self._preview_next_button: ttkb.Button | None = None
        self._current_output_dir: Path | None = None
        self._current_preview_title: str | None = None
        self._latest_preview_title: str | None = None
        self._available_data_files: list[Path] = []
        self._menu_entries: dict[str, tuple[tk.Menu, int]] = {}
        self._configure_styles()
        self._load_images()

        self._create_menus()
        self._create_widgets()
        self._build_menubar()
        self._hide_preview_pane()
        self.tree.bind("<Double-1>", self.on_double_click)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.load_config()
        self._update_checker.start(self, self._handle_update_result)

    # ------------------------------------------------------------------
    def _configure_styles(self) -> None:
        """Establish custom style rules for shared widgets."""

        self._style.configure(
            "Toolbar.TButton",
            font=("Segoe UI", 11, "bold"),
            padding=(14, 10),
        )

    # ------------------------------------------------------------------
    def _create_menus(self) -> None:
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="New Project…", command=self.new_project_dialog)
        file_menu.add_command(label="Open Project…", command=self.open_project_dialog)

        recent_menu = tk.Menu(file_menu, tearoff=False)
        self._recent_menu = recent_menu
        file_menu.add_cascade(label="Open Recent", menu=recent_menu)

        file_menu.add_separator()
        file_menu.add_command(label="Save", command=self.save_config)
        file_menu.add_command(label="Save Project As…", command=self.save_project_as_dialog)

        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)

        menubar.add_cascade(label="File", menu=file_menu)
        self.config(menu=menubar)
        self._update_recent_projects_menu()

    # ------------------------------------------------------------------
    def _create_widgets(self) -> None:
        header = ttkb.Frame(self, padding=10)
        header.pack(fill="x")
        if (logo := self._images.get("icon_header")) is not None:
            ttkb.Label(header, image=logo).pack(side="left", padx=(0, 10))
        ttkb.Label(
            header,
            text=f"⚙️ Plotinator Open Beta v{PACKAGE_VERSION}",
            font=("Segoe UI", 22, "bold"),
        ).pack(side="left")
        ttkb.Button(header, text="🌓", width=3, command=self.toggle_theme).pack(side="right", padx=8)

        toolbar = ttkb.Frame(self, padding=10)
        toolbar.pack(fill="x")
        self._toolbar_buttons: dict[str, ttkb.Button] = {}
        button_plan: Sequence[tuple[str, str, Callable[[], None], str]] = [
            ("new", "New Project", self.new_project_dialog, "secondary-outline"),
            ("open", "Open Project", self.open_project_dialog, "secondary-outline"),
            ("save", "Save Project", lambda: self.save_project(), "secondary"),
            ("save_as", "Save As…", self.save_project_as_dialog, "secondary-outline"),
            ("add_fit", "Add Fit", self.add_fit, "primary"),
            ("delete_fit", "Delete Fit", self.delete_fit, "danger-outline"),
            ("run", "Run Batch", self.run_batch, "success"),
            ("stop", "Stop Batch", self.stop_batch, "danger"),
            ("report", "Open Report", self.open_latest_report, "info"),
            ("settings", "Settings", self.open_settings_dialog, "secondary-outline"),
        ]
        for key, text, cmd, style in button_plan:
            button = ttkb.Button(
                toolbar,
                text=text,
                command=cmd,
                bootstyle=style,
                style="Toolbar.TButton",
                width=14,
            )
            button.pack(side="left", padx=4)
            self._toolbar_buttons[key] = button

        content_paned = ttkb.Panedwindow(self, orient="horizontal")
        content_paned.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._content_paned = content_paned

        queue_frame = ttkb.Frame(content_paned, padding=0)
        queue_frame.columnconfigure(0, weight=1)
        queue_frame.rowconfigure(0, weight=1)
        content_paned.add(queue_frame, weight=3)

        queue_paned = ttkb.Panedwindow(queue_frame, orient="vertical")
        queue_paned.grid(row=0, column=0, sticky="nsew")

        table_frame = ttkb.Frame(queue_paned, padding=10)
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
        queue_paned.add(table_frame, weight=3)

        log_frame = ttkb.Labelframe(queue_paned, padding=10)
        if (log_icon := self._images.get("toolbar_log")) is not None:
            log_label = ttkb.Label(log_frame, text="Batch log", image=log_icon, compound="left")
            log_label.configure(font=("Segoe UI", 11, "bold"), padding=(4, 0))
            log_frame.configure(labelwidget=log_label)
        else:
            log_frame.configure(text="Batch log")
        queue_paned.add(log_frame, weight=2)

        self._log_history: list[str] = []
        self._log_filter_job: str | None = None
        self._log_filter_var = tk.StringVar(self, value="")
        self._log_matches_var = tk.StringVar(self, value="")

        log_controls = ttkb.Frame(log_frame)
        log_controls.pack(fill="x", pady=(0, 8))

        clear_button = ttkb.Button(
            log_controls,
            text="Clear",
            command=lambda: self._clear_logs(user_action=True),
            bootstyle="secondary-outline",
        )
        clear_button.pack(side="right")

        save_button = ttkb.Button(
            log_controls,
            text="Save…",
            command=self._save_logs,
            bootstyle="primary-outline",
        )
        save_button.pack(side="right", padx=(0, 6))

        ttkb.Label(log_controls, textvariable=self._log_matches_var, anchor="w").pack(
            side="left", padx=(0, 10)
        )

        ttkb.Label(log_controls, text="Filter:").pack(side="left")
        self._log_filter_entry = ttkb.Entry(
            log_controls,
            textvariable=self._log_filter_var,
            width=30,
        )
        self._log_filter_entry.pack(side="left", fill="x", expand=True, padx=(6, 0))

        log_container = ttkb.Frame(log_frame)
        log_container.pack(fill="both", expand=True)

        y_scroll = ttkb.Scrollbar(log_container, orient="vertical")
        y_scroll.pack(side="right", fill="y")
        x_scroll = ttkb.Scrollbar(log_container, orient="horizontal")
        x_scroll.pack(side="bottom", fill="x")

        self.log_text = tk.Text(
            log_container,
            height=10,
            wrap="none",
            bg="#101820",
            fg="#39FF14",
            insertbackground="#39FF14",
        )
        self.log_text.pack(side="left", fill="both", expand=True)
        self.log_text.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        y_scroll.configure(command=self.log_text.yview)
        x_scroll.configure(command=self.log_text.xview)
        self.log_text.tag_configure(
            "filter_match", background="#F4D03F", foreground="#101820"
        )

        self._log_filter_var.trace_add("write", self._queue_log_filter_update)
        self.log_text.bind("<Control-f>", self._focus_log_filter)

        queue_paned.pane(table_frame, weight=3)
        queue_paned.pane(log_frame, weight=2)


        self._preview_container = self._build_preview_container(content_paned)

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

    # ------------------------------------------------------------------
    def _build_menubar(self) -> None:
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="New Project…", command=self.new_project_dialog)
        file_menu.add_command(label="Open Project…", command=self.open_project_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="Save Project", command=lambda: self.save_project())
        self._menu_entries["save"] = (file_menu, file_menu.index("end"))
        file_menu.add_command(label="Save Project As…", command=self.save_project_as_dialog)
        self._menu_entries["save_as"] = (file_menu, file_menu.index("end"))
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=file_menu)
        self.config(menu=menubar)
        self._menubar = menubar
        self._set_project_action_state(False)

    # ------------------------------------------------------------------
    def _set_project_action_state(self, enabled: bool) -> None:
        for key, button in self._toolbar_buttons.items():
            if key in {"new", "open"}:
                continue
            if enabled:
                button.state(["!disabled"])
            else:
                button.state(["disabled"])
        menu_state = "normal" if enabled else "disabled"
        for key in ("save", "save_as"):
            menu_entry = self._menu_entries.get(key)
            if menu_entry is None:
                continue
            menu, index = menu_entry
            menu.entryconfig(index, state=menu_state)

    # ------------------------------------------------------------------
    def _initialise_project(self) -> None:
        default_candidate = Path(CONFIG_PATH).resolve()
        project: PlotinatorProject | None = None
        if default_candidate.exists():
            try:
                project = self.project_manager.open_project(default_candidate)
            except FileNotFoundError:
                project = None
            except Exception as exc:  # noqa: BLE001 - surfaced to user
                self._append_log(f"[PROJECT] Failed to open default project: {exc}\n")
                self.show_toast("Unable to open default project", level="error")
        if project is not None:
            self._apply_project(project)
            return
        self._update_window_title()
        self._prompt_for_initial_project()

    # ------------------------------------------------------------------
    def _prompt_for_initial_project(self) -> None:
        response = messagebox.askyesnocancel(
            "Plotinator",
            "No project is currently loaded. Would you like to create a new project?\n"
            "Choose 'No' to open an existing project.",
        )
        if response is None:
            return
        if response:
            self.new_project_dialog()
        else:
            self.open_project_dialog()

    # ------------------------------------------------------------------
    def _project_display_name(self, project: PlotinatorProject | None = None) -> str:
        target = project or self._project
        if target is None:
            return "Untitled"
        return target.metadata.label or target.paths.root.name or "Untitled"

    # ------------------------------------------------------------------
    def _update_window_title(self) -> None:
        base = f"Plotinator Open Beta v{PACKAGE_VERSION}"
        project = self._project
        if project is None:
            self.title(base)
            return
        label = self._project_display_name(project)
        dirty_marker = "*" if self.project_manager.dirty else ""
        self.title(f"{base} — {label}{dirty_marker}")

    # ------------------------------------------------------------------
    def _materialise_engine_config(self, project: PlotinatorProject) -> Path:
        project.paths.root.mkdir(parents=True, exist_ok=True)
        config_path = project.paths.root / CONFIG_PATH
        config_model = project.to_config()
        if config_model.settings.output_dir is None:
            config_model.settings.output_dir = project.paths.exports_dir
        payload = config_model.to_dict()
        with config_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        self._engine_config_path = config_path
        return config_path

    # ------------------------------------------------------------------
    def _confirm_project_change(self) -> bool:
        worker = self._worker
        if worker and worker.is_running():
            warning_message = "Stop the running batch before changing projects."
            self.show_toast(warning_message, level="warning")
            messagebox.showwarning("Plotinator", warning_message)
            return False
        if not self.project_manager.dirty:
            return True
        response = messagebox.askyesnocancel(
            "Plotinator",
            "The current project has unsaved changes. Save them before continuing?",
        )
        if response is None:
            return False
        if response:
            return self.save_project()
        return True

    # ------------------------------------------------------------------
    def _on_project_filesystem_update(self, paths: ProjectPaths) -> None:
        project = self._project
        if project is None:
            return
        if paths.root != project.paths.root:
            return
        self._refresh_available_data_files()

    # ------------------------------------------------------------------
    def _format_timestamp(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone().strftime("%Y-%m-%d %H:%M")

    def _format_update_status(self) -> str:
        prefs = self._update_checker.preferences
        if not prefs.enabled:
            return "Automatic update checks are disabled."

        result = self._update_checker.last_result
        if result is None:
            if prefs.last_checked is None:
                return "Automatic update checks enabled. Next check will run shortly."
            return f"Last checked on {self._format_timestamp(prefs.last_checked)}."

        if result.error:
            return f"Last check failed at {self._format_timestamp(result.checked_at)}: {result.error}"

        if result.release is not None:
            return (
                f"Update available ({result.release.version_label}, checked"
                f" {self._format_timestamp(result.checked_at)})."
            )

        return f"No updates found (checked {self._format_timestamp(result.checked_at)})."

    def open_settings_dialog(self) -> None:
        if self._settings_window is not None and self._settings_window.winfo_exists():
            self._settings_window.lift()
            self._settings_window.focus_force()
            return

        self._update_status_var.set(self._format_update_status())

        window = ttkb.Toplevel(self)
        window.title("Application settings")
        window.geometry("360x260")
        window.resizable(False, False)
        window.transient(self)
        window.grab_set()
        self._settings_window = window

        enabled_var = tk.BooleanVar(value=self._update_checker.preferences.enabled)
        interval_var = tk.IntVar(value=self._update_checker.preferences.interval_hours)
        autosave_var = tk.IntVar(value=self._app_state.autosave_minutes)

        ttkb.Label(window, text="Updates", font=("Segoe UI", 12, "bold")).pack(
            anchor="w", padx=12, pady=(12, 4)
        )
        ttkb.Checkbutton(
            window,
            text="Check for new releases automatically",
            variable=enabled_var,
        ).pack(anchor="w", padx=18, pady=4)

        freq_frame = ttkb.Frame(window)
        freq_frame.pack(fill="x", padx=18, pady=(0, 12))
        ttkb.Label(freq_frame, text="Check frequency (hours)").pack(side="left")
        freq_spin = ttkb.Spinbox(
            freq_frame,
            from_=1,
            to=168,
            width=6,
            textvariable=interval_var,
        )
        freq_spin.pack(side="left", padx=(10, 0))

        ttkb.Separator(window, orient="horizontal").pack(fill="x", padx=12, pady=(6, 6))

        ttkb.Label(window, text="Workspace", font=("Segoe UI", 12, "bold")).pack(
            anchor="w", padx=12, pady=(0, 4)
        )
        autosave_frame = ttkb.Frame(window)
        autosave_frame.pack(fill="x", padx=18, pady=(0, 12))
        ttkb.Label(autosave_frame, text="Autosave every (minutes)").pack(side="left")
        autosave_spin = ttkb.Spinbox(
            autosave_frame,
            from_=0,
            to=120,
            width=6,
            textvariable=autosave_var,
        )
        autosave_spin.pack(side="left", padx=(10, 0))
        ttkb.Label(
            autosave_frame,
            text="(0 disables autosave)",
            bootstyle="secondary",
        ).pack(side="left", padx=(8, 0))

        status_label = ttkb.Label(
            window,
            textvariable=self._update_status_var,
            wraplength=320,
            bootstyle="info",
            justify="left",
        )
        status_label.pack(fill="x", padx=12, pady=(0, 12))

        buttons = ttkb.Frame(window)
        buttons.pack(fill="x", padx=12, pady=(0, 12))

        def _close() -> None:
            if self._settings_window is window:
                self._settings_window = None
            window.destroy()

        def _apply() -> None:
            try:
                interval_value = int(interval_var.get())
            except (tk.TclError, ValueError):
                interval_value = self._update_checker.preferences.interval_hours
            self._update_checker.update_preferences(
                enabled=bool(enabled_var.get()),
                interval_hours=interval_value,
            )
            try:
                autosave_value = int(autosave_var.get())
            except (tk.TclError, ValueError):
                autosave_value = self._app_state.autosave_minutes
            self._app_state.autosave_minutes = max(0, autosave_value)
            self._app_state.save()
            self._schedule_autosave(reset=True)
            self._update_status_var.set(self._format_update_status())
            self.show_toast("Settings updated", level="success")
            _close()

        def _check_now() -> None:
            self._update_status_var.set("Checking for updates…")
            self._update_checker.check_now(self, self._handle_update_result)

        ttkb.Button(buttons, text="Check now", command=_check_now, bootstyle="info-outline").pack(
            side="left"
        )
        ttkb.Button(buttons, text="Save", command=_apply, bootstyle="success").pack(
            side="right"
        )
        ttkb.Button(buttons, text="Close", command=_close).pack(side="right", padx=(0, 8))

        window.protocol("WM_DELETE_WINDOW", _close)

    def _handle_update_result(self, result: UpdateResult) -> None:
        self._update_status_var.set(self._format_update_status())
        if result.error:
            # Only surface failures when the user explicitly asked for a check.
            if self._settings_window is not None and self._settings_window.winfo_exists():
                self.show_toast(f"Update check failed: {result.error}", level="warning")
            return

        if result.release is not None:
            self._announce_release(result.release)

    def _announce_release(self, release: ReleaseInfo) -> None:
        message = f"Update available: Plotinator {release.version_label}"
        self.status_var.set(message)
        self.show_toast(message, level="info")
        summary = release.notes.splitlines()
        excerpt = "\n".join(summary[:3]).strip()
        if excerpt:
            body = f"Plotinator {release.version_label} is available.\n\n{excerpt}\n\nOpen download page?"
        else:
            body = f"Plotinator {release.version_label} is available.\n\nOpen download page?"
        if messagebox.askyesno("Update available", body, parent=self):
            self._open_release_url(release.url)

    def _open_release_url(self, url: str) -> None:
        try:
            webbrowser.open(url, new=2, autoraise=True)
        except webbrowser.Error:
            self.show_toast("Unable to open browser", level="error")

    # ------------------------------------------------------------------
    def _build_preview_container(self, parent: ttkb.Panedwindow) -> ttkb.Frame:
        container = ttkb.Frame(parent, padding=10)
        container.columnconfigure(0, weight=1)

        header = ttkb.Label(
            container,
            textvariable=self._preview_header_var,
            font=("Segoe UI", 14, "bold"),
            anchor="w",
        )
        header.pack(anchor="w")

        controls = ttkb.Frame(container)
        controls.pack(fill="x", pady=(4, 0))
        prev_button = ttkb.Button(
            controls,
            text="◀ Previous",
            bootstyle="secondary-outline",
            command=self._show_previous_preview,
            width=14,
        )
        prev_button.pack(side="left")
        next_button = ttkb.Button(
            controls,
            text="Next ▶",
            bootstyle="secondary-outline",
            command=self._show_next_preview,
            width=14,
        )
        next_button.pack(side="right")
        self._preview_prev_button = prev_button
        self._preview_next_button = next_button

        notebook = ttkb.Notebook(container)
        notebook.pack(fill="both", expand=True, pady=(8, 0))
        self._preview_notebook = notebook

        plot_tab = ttkb.Frame(notebook)
        plot_tab.columnconfigure(0, weight=1)
        plot_tab.rowconfigure(0, weight=1)
        notebook.add(plot_tab, text="Plot")
        self._preview_plot_tab = plot_tab

        canvas_frame = ttkb.Frame(plot_tab)
        canvas_frame.grid(row=0, column=0, sticky="nsew")
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.rowconfigure(0, weight=1)

        canvas = tk.Canvas(canvas_frame, background="#0C1F2C", highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        y_scroll = ttkb.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll = ttkb.Scrollbar(canvas_frame, orient="horizontal", command=canvas.xview)
        x_scroll.grid(row=1, column=0, sticky="ew")
        canvas.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self._preview_canvas = canvas

        residuals_tab = ttkb.Frame(notebook, padding=12)
        notebook.add(residuals_tab, text="Residuals")
        residual_label = ttkb.Label(
            residuals_tab,
            text="Residual preview not available yet.",
            anchor="center",
            justify="center",
            wraplength=280,
        )
        residual_label.pack(fill="both", expand=True)
        self._preview_residual_label = residual_label

        summary_tab = ttkb.Frame(notebook, padding=12)
        summary_tab.columnconfigure(1, weight=1)
        notebook.add(summary_tab, text="Summary")

        summary_fields = [
            ("χ²", "chi2"),
            ("Reduced χ²", "reduced_chi2"),
            ("RMS", "rms"),
            ("Mean residual", "mean"),
            ("Std residual", "std"),
            ("Fit errors", "fit_error"),
        ]
        for row, (label_text, key) in enumerate(summary_fields):
            ttkb.Label(summary_tab, text=label_text).grid(
                row=row,
                column=0,
                sticky="w",
                padx=(0, 10),
                pady=4,
            )
            var = tk.StringVar(value="—")
            self._preview_summary_vars[key] = var
            ttkb.Label(
                summary_tab,
                textvariable=var,
                font=("Segoe UI", 11, "bold"),
                anchor="w",
                justify="left",
                wraplength=260,
            ).grid(row=row, column=1, sticky="ew", pady=4)

        self._update_preview_message("Preview will appear once a fit starts.")
        self._update_preview_history_buttons()
        return container

    # ------------------------------------------------------------------
    def _update_preview_message(self, message: str) -> None:
        canvas = self._preview_canvas
        if canvas is None:
            return
        canvas.delete("all")
        self._preview_canvas_image = None
        self._preview_canvas_message = canvas.create_text(
            16,
            16,
            anchor="nw",
            text=message,
            fill="#F8F9FA",
            font=("Segoe UI", 11),
        )
        canvas.configure(scrollregion=(0, 0, canvas.winfo_width(), canvas.winfo_height()))

    # ------------------------------------------------------------------
    def _show_preview_image(self, image: tk.PhotoImage) -> None:
        canvas = self._preview_canvas
        if canvas is None:
            return
        canvas.delete("all")
        self._preview_canvas_message = None
        self._preview_canvas_image = canvas.create_image(0, 0, anchor="nw", image=image)
        canvas.configure(scrollregion=(0, 0, image.width(), image.height()))

    # ------------------------------------------------------------------
    def _clear_preview_summary(self) -> None:
        for var in self._preview_summary_vars.values():
            var.set("—")

    # ------------------------------------------------------------------
    def _is_project_plot_directory(self, directory: Path | None) -> bool:
        if directory is None:
            return False
        project = self._project
        if project is None:
            return False
        try:
            dir_resolved = directory.resolve()
            plots_root = project.paths.plots_dir.resolve()
        except FileNotFoundError:
            return False
        try:
            dir_resolved.relative_to(plots_root)
            return True
        except ValueError:
            return False

    # ------------------------------------------------------------------
    def _queue_preview_temp_cleanup(self, directory: Path | None) -> None:
        if directory is None:
            return
        if self._is_project_plot_directory(directory):
            return
        self._preview_stale_temp_dirs.add(directory)

    # ------------------------------------------------------------------
    def _cleanup_stale_preview_dirs(self) -> None:
        stale = list(self._preview_stale_temp_dirs)
        self._preview_stale_temp_dirs.clear()
        for directory in stale:
            shutil.rmtree(directory, ignore_errors=True)

    # ------------------------------------------------------------------
    def _cleanup_all_preview_temp_dirs(self) -> None:
        if self._preview_active_temp_dir is not None and not self._is_project_plot_directory(
            self._preview_active_temp_dir
        ):
            self._preview_stale_temp_dirs.add(self._preview_active_temp_dir)
        self._preview_active_temp_dir = None
        self._cleanup_stale_preview_dirs()

    # ------------------------------------------------------------------
    def _activate_preview_temp_dir(self, payload: dict[str, Any]) -> None:
        directory = self._extract_cleanup_dir(payload)
        if directory is None:
            return
        if directory == self._preview_active_temp_dir:
            return
        if not self._is_preview_dir_in_history(self._preview_active_temp_dir):
            self._queue_preview_temp_cleanup(self._preview_active_temp_dir)
        self._preview_active_temp_dir = directory

    # ------------------------------------------------------------------
    def _result_from_preview_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        result_payload = payload.get("result")
        if isinstance(result_payload, dict):
            return copy.deepcopy(result_payload)
        source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
        return {
            "output_plot": payload.get("output_plot") or source.get("output_plot"),
            "residuals_plot": payload.get("residuals_plot") or source.get("residuals_plot"),
            "metrics": copy.deepcopy(payload.get("metrics") or {}),
            "parameters": copy.deepcopy(payload.get("parameters") or {}),
        }

    # ------------------------------------------------------------------
    def _materialise_preview_assets(
        self, title: str, payload: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if not payload:
            return payload
        project = self._project
        if project is None:
            return payload

        copy_payload = copy.deepcopy(payload)
        preview_root = project.paths.plots_dir / "previews"
        try:
            preview_root.mkdir(parents=True, exist_ok=True)
        except OSError:
            return copy_payload

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = re.sub(r"[^A-Za-z0-9_-]+", "_", title).strip("_") or "preview"
        dest_dir = preview_root / f"{timestamp}_{slug[:40]}"
        dest_dir.mkdir(parents=True, exist_ok=True)

        source_mapping = (
            copy_payload.get("source") if isinstance(copy_payload.get("source"), dict) else {}
        )
        for key in ("output_plot", "residuals_plot"):
            candidate = copy_payload.get(key) or source_mapping.get(key)
            if not candidate:
                continue
            try:
                candidate_path = Path(str(candidate))
            except (TypeError, ValueError, OSError):
                continue
            if not candidate_path.exists():
                continue
            target_path = dest_dir / (candidate_path.name or f"{key}.png")
            try:
                shutil.copy2(candidate_path, target_path)
            except OSError:
                continue
            copy_payload[key] = target_path.as_posix()

        copy_payload["project_preview_dir"] = dest_dir.as_posix()
        copy_payload["cleanup_dir"] = dest_dir.as_posix()
        return copy_payload

    # ------------------------------------------------------------------
    def _load_preview_from_payload(self, payload: dict[str, Any], title: str) -> None:
        result = self._result_from_preview_payload(payload)
        self._apply_preview_result_data(result)
        plot_loaded = self._update_main_image_from_path(result.get("output_plot"))
        if not plot_loaded:
            self._update_preview_message(f"Preview not available for \"{title}\".")
        self._update_residual_image_from_path(result.get("residuals_plot"))

    # ------------------------------------------------------------------
    def _extract_cleanup_dir(self, payload: dict[str, Any] | None) -> Path | None:
        if not isinstance(payload, dict):
            return None
        cleanup_dir = payload.get("project_preview_dir") or payload.get("cleanup_dir")
        if not cleanup_dir:
            return None
        try:
            return Path(str(cleanup_dir))
        except (TypeError, ValueError, OSError):
            return None

    # ------------------------------------------------------------------
    def _is_preview_dir_in_history(self, directory: Path | None) -> bool:
        if directory is None:
            return False
        for entry in self._preview_history:
            history_dir = self._extract_cleanup_dir(entry.get("preview"))
            if history_dir is not None and history_dir == directory:
                return True
        return False

    # ------------------------------------------------------------------
    def _record_preview_history(
        self,
        title: str,
        payload: dict[str, Any] | None,
        result: dict[str, Any] | None,
    ) -> None:
        payload_copy = copy.deepcopy(payload) if isinstance(payload, dict) else None
        result_copy = copy.deepcopy(result) if isinstance(result, dict) else None

        history = self._preview_history
        removed_forward: list[dict[str, Any]] = []
        if self._preview_history_index is None:
            if history:
                removed_forward = history[:]
            history.clear()
        elif self._preview_history_index < len(history) - 1:
            removed_forward = history[self._preview_history_index + 1 :]
            del history[self._preview_history_index + 1 :]

        for entry in removed_forward:
            cleanup_dir = self._extract_cleanup_dir(entry.get("preview"))
            if cleanup_dir is not None and cleanup_dir != self._preview_active_temp_dir:
                self._queue_preview_temp_cleanup(cleanup_dir)

        history.append({"title": title, "preview": payload_copy, "result": result_copy})

        while len(history) > self._preview_history_limit:
            removed_entry = history.pop(0)
            cleanup_dir = self._extract_cleanup_dir(removed_entry.get("preview"))
            if cleanup_dir is not None and cleanup_dir != self._preview_active_temp_dir:
                self._queue_preview_temp_cleanup(cleanup_dir)

        self._preview_history_index = len(history) - 1
        self._update_preview_history_buttons()

    # ------------------------------------------------------------------
    def _update_preview_history_buttons(self) -> None:
        prev_button = self._preview_prev_button
        next_button = self._preview_next_button
        history = self._preview_history
        index = self._preview_history_index if self._preview_history_index is not None else -1

        if prev_button is not None:
            if index > 0:
                prev_button.state(["!disabled"])
            else:
                prev_button.state(["disabled"])

        if next_button is not None:
            if 0 <= index < len(history) - 1:
                next_button.state(["!disabled"])
            else:
                next_button.state(["disabled"])

    # ------------------------------------------------------------------
    def _show_previous_preview(self) -> None:
        if self._preview_history_index is None or self._preview_history_index <= 0:
            return
        self._preview_history_index -= 1
        entry = self._preview_history[self._preview_history_index]
        self.render_batch_preview(
            entry.get("title", "Untitled"),
            entry.get("preview"),
            entry.get("result"),
            record_history=False,
            show_notifications=False,
        )
        self._update_preview_history_buttons()

    # ------------------------------------------------------------------
    def _show_next_preview(self) -> None:
        if self._preview_history_index is None:
            return
        if self._preview_history_index >= len(self._preview_history) - 1:
            return
        self._preview_history_index += 1
        entry = self._preview_history[self._preview_history_index]
        self.render_batch_preview(
            entry.get("title", "Untitled"),
            entry.get("preview"),
            entry.get("result"),
            record_history=False,
            show_notifications=False,
        )
        self._update_preview_history_buttons()

    # ------------------------------------------------------------------
    def _ensure_preview_pane(self) -> None:
        if self._content_paned is None or self._preview_container is None:
            return
        if not self._preview_pane_visible:
            try:
                self._content_paned.add(self._preview_container, weight=2)
            except tk.TclError:
                return
            self._preview_pane_visible = True
        if self._preview_notebook is not None and self._preview_plot_tab is not None:
            self._preview_notebook.select(self._preview_plot_tab)

    # ------------------------------------------------------------------
    def _hide_preview_pane(self) -> None:
        if self._content_paned is None or self._preview_container is None:
            return
        if self._preview_pane_visible:
            try:
                self._content_paned.forget(self._preview_container)
            except tk.TclError:
                pass
            self._preview_pane_visible = False
        self._preview_header_var.set("Preview")
        self._update_preview_message("Preview will appear once a fit starts.")
        self._clear_preview_summary()
        if self._preview_residual_label is not None:
            self._preview_residual_label.configure(
                image="",
                text="Residual preview not available yet.",
            )
        self._preview_photo_main = None
        self._preview_photo_residual = None
        self._current_preview_title = None
        self._latest_preview_title = None
        if self._preview_history:
            for entry in self._preview_history:
                cleanup_dir = self._extract_cleanup_dir(entry.get("preview"))
                if cleanup_dir is not None and not self._is_project_plot_directory(cleanup_dir):
                    self._preview_stale_temp_dirs.add(cleanup_dir)
            self._preview_history.clear()
        self._preview_history_index = None
        self._update_preview_history_buttons()
        self._cleanup_all_preview_temp_dirs()

    # ------------------------------------------------------------------
    def _update_main_image_from_path(self, path: Path | str | None) -> bool:
        if path in (None, ""):
            return False
        candidate = Path(str(path))
        if not candidate.exists():
            return False
        try:
            image = tk.PhotoImage(file=candidate.as_posix())
        except tk.TclError:
            return False
        self._preview_photo_main = image
        self._show_preview_image(image)
        return True

    # ------------------------------------------------------------------
    def _update_residual_image_from_path(self, path: Path | str | None) -> bool:
        label = self._preview_residual_label
        if label is None:
            return False
        if path in (None, ""):
            label.configure(image="", text="Residual preview not generated for this fit.")
            self._preview_photo_residual = None
            return False
        candidate = Path(str(path))
        if not candidate.exists():
            label.configure(image="", text="Residual preview not generated for this fit.")
            self._preview_photo_residual = None
            return False
        try:
            image = tk.PhotoImage(file=candidate.as_posix())
        except tk.TclError:
            label.configure(image="", text="Residual preview failed to load.")
            self._preview_photo_residual = None
            return False
        if max(image.width(), image.height()) > 320:
            image = self._scale_image(image, 320)
        self._preview_photo_residual = image
        label.configure(image=image, text="")
        return True

    # ------------------------------------------------------------------
    def _load_preview_images(self, title: str) -> None:
        base = self._current_output_dir
        if base is None:
            self._update_preview_message(f"Preview not available for \"{title}\".")
            return
        safe_title = title.replace(" ", "_")
        plot_dir = base / f"plot_{safe_title}"
        plot_loaded = self._update_main_image_from_path(plot_dir / "plot.png")
        if not plot_loaded:
            self._update_preview_message(f"Preview not available for \"{title}\".")
        self._update_residual_image_from_path(plot_dir / "residuals.png")

    # ------------------------------------------------------------------
    def _set_summary_value(self, key: str, value: Any) -> None:
        var = self._preview_summary_vars.get(key)
        if var is None:
            return
        if value in (None, ""):
            var.set("—")
            return
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            var.set(str(value))
            return
        if math.isnan(numeric):
            var.set("—")
            return
        var.set(f"{numeric:.4g}")

    # ------------------------------------------------------------------
    def _apply_preview_result_data(self, result: dict[str, Any]) -> None:
        metrics = result.get("metrics") or {}
        self._set_summary_value("chi2", metrics.get("chi_squared") or metrics.get("chi2") or metrics.get("chisq"))
        self._set_summary_value(
            "reduced_chi2",
            metrics.get("reduced_chi_squared")
            or metrics.get("reduced_chi2")
            or metrics.get("reduced_chisq"),
        )
        self._set_summary_value("rms", metrics.get("rmse") or metrics.get("rms"))
        self._set_summary_value("mean", metrics.get("mean"))
        self._set_summary_value("std", metrics.get("std"))

        parameters = result.get("parameters") or {}
        fit_errors: list[str] = []
        for name, payload in parameters.items():
            if not isinstance(payload, dict):
                continue
            error = payload.get("error")
            if error in (None, ""):
                continue
            try:
                fit_errors.append(f"{name} ± {float(error):.3g}")
            except (TypeError, ValueError):
                fit_errors.append(f"{name} ± {error}")
        summary = ", ".join(fit_errors) if fit_errors else "—"
        fit_var = self._preview_summary_vars.get("fit_error")
        if fit_var is not None:
            fit_var.set(summary)

    # ------------------------------------------------------------------
    def _load_preview_from_result(self, result: dict[str, Any]) -> None:
        plot_path = result.get("output_plot") or (result.get("canvases") or {}).get("combined")
        residual_path = result.get("residuals_plot") or (result.get("canvases") or {}).get("residuals")
        plot_loaded = self._update_main_image_from_path(plot_path)
        if not plot_loaded and self._current_preview_title:
            self._load_preview_images(self._current_preview_title)
        self._update_residual_image_from_path(residual_path)

    # ------------------------------------------------------------------
    def render_batch_preview(
        self,
        title: str,
        preview_payload: dict[str, Any] | None,
        result_payload: dict[str, Any] | None = None,
        *,
        record_history: bool = True,
        show_notifications: bool = True,
    ) -> None:
        payload_copy = copy.deepcopy(preview_payload) if isinstance(preview_payload, dict) else None
        payload_copy = self._materialise_preview_assets(title, payload_copy)
        result_override = copy.deepcopy(result_payload) if isinstance(result_payload, dict) else None

        if payload_copy and result_override and not isinstance(payload_copy.get("result"), dict):
            payload_copy["result"] = copy.deepcopy(result_override)

        self._ensure_preview_pane()
        self._preview_header_var.set(f"Preview: {title}")
        self._current_preview_title = title
        if record_history:
            self._latest_preview_title = title

        if payload_copy:
            self._activate_preview_temp_dir(payload_copy)
        else:
            if not self._is_preview_dir_in_history(self._preview_active_temp_dir):
                self._queue_preview_temp_cleanup(self._preview_active_temp_dir)
            self._preview_active_temp_dir = None

        result_data: dict[str, Any] | None = None
        if payload_copy:
            try:
                result_data = self._result_from_preview_payload(payload_copy)
            except Exception as exc:  # noqa: BLE001 - surface via notification
                result_data = None
                if show_notifications:
                    self.show_toast(f"Preview data unavailable for {title}", level="warning")
                self._append_log(f"[PREVIEW] Failed to parse preview payload for {title}: {exc}\n")

        if result_data is None and result_override is not None:
            result_data = result_override

        if result_data:
            self._apply_preview_result_data(result_data)
        else:
            self._clear_preview_summary()

        self._preview_photo_main = None
        self._preview_photo_residual = None
        main_loaded = False
        residual_loaded = False
        used_fallback = False
        plot_path = result_data.get("output_plot") if isinstance(result_data, dict) else None
        residual_path = result_data.get("residuals_plot") if isinstance(result_data, dict) else None

        if plot_path:
            main_loaded = self._update_main_image_from_path(plot_path)
            if not main_loaded and show_notifications:
                self.show_toast(f"Preview image missing for {title}", level="warning")
        else:
            self._update_preview_message(f"Preview not available for \"{title}\".")

        if not main_loaded:
            if self._current_output_dir is not None:
                self._load_preview_images(title)
                if self._preview_canvas_image is not None:
                    used_fallback = True
                    main_loaded = True
            if not main_loaded:
                self._preview_photo_main = None
                if show_notifications and (plot_path or payload_copy or result_override):
                    self.show_toast(f"Preview not available for {title}", level="info")

        if residual_path and not used_fallback:
            residual_loaded = self._update_residual_image_from_path(residual_path)
            if not residual_loaded and show_notifications:
                self.show_toast(f"Residual preview missing for {title}", level="info")
        elif not used_fallback:
            self._update_residual_image_from_path(None)

        if record_history:
            self._record_preview_history(title, payload_copy, result_data)
        else:
            self._update_preview_history_buttons()

        self._cleanup_stale_preview_dirs()

    # ------------------------------------------------------------------
    def _on_preview_plot_start(self, title: str) -> None:
        self._ensure_preview_pane()
        self._queue_preview_temp_cleanup(self._preview_active_temp_dir)
        self._preview_active_temp_dir = None
        self._cleanup_stale_preview_dirs()
        self._preview_header_var.set(f"Preview: {title}")
        self._update_preview_message(f"Preparing preview for \"{title}\"…")
        self._clear_preview_summary()
        if self._preview_residual_label is not None:
            self._preview_residual_label.configure(
                image="",
                text="Residual preview will appear after the fit completes.",
            )
        self._preview_photo_main = None
        self._preview_photo_residual = None
        self._current_preview_title = title

    # ------------------------------------------------------------------
    def _on_preview_plot_complete(
        self, title: str, payload: dict[str, Any] | None = None
    ) -> None:
        self.render_batch_preview(title, payload)

    # ------------------------------------------------------------------
    def _on_preview_plot_error(self, title: str, error: str) -> None:
        self._ensure_preview_pane()
        self._queue_preview_temp_cleanup(self._preview_active_temp_dir)
        self._preview_active_temp_dir = None
        self._cleanup_stale_preview_dirs()
        self._preview_header_var.set(f"Preview: {title}")
        self._update_preview_message(f"Preview unavailable: {error}")
        if self._preview_residual_label is not None:
            self._preview_residual_label.configure(
                image="",
                text="Residual preview unavailable due to error.",
            )
        self._clear_preview_summary()
        self._preview_photo_main = None
        self._preview_photo_residual = None

    # ------------------------------------------------------------------
    def _on_preview_job_complete(self, event: dict[str, Any]) -> None:
        results: list[dict[str, Any]] = event.get("results") or []
        if not results:
            return
        target_title = self._latest_preview_title or results[-1].get("title")
        if not target_title:
            return
        for result in results:
            if result.get("title") == target_title:
                self._preview_header_var.set(f"Preview: {target_title}")
                self._ensure_preview_pane()
                self._apply_preview_result_data(result)
                self._load_preview_from_result(result)
                break

    # ------------------------------------------------------------------
    def _on_preview_job_failure(self, message: str) -> None:
        self._ensure_preview_pane()
        self._preview_header_var.set("Preview")
        self._update_preview_message(message)
        if self._preview_residual_label is not None:
            self._preview_residual_label.configure(image="", text="Residual preview unavailable.")
        self._clear_preview_summary()
        self._preview_photo_main = None
        self._preview_photo_residual = None
        self._current_output_dir = None
        self._current_preview_title = None
        self._latest_preview_title = None
        self._cleanup_all_preview_temp_dirs()

    # ------------------------------------------------------------------
    def _reset_preview_state(self) -> None:
        self._current_output_dir = None
        self._hide_preview_pane()

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

        if sys.platform.startswith("win"):
            ico_path = base_path / "packaging" / "windows" / "plotinator.ico"
            if ico_path.exists():
                try:
                    self.iconbitmap(str(ico_path))
                except tk.TclError:
                    pass

        toolbar_icon = self._images.get("toolbar")
        if toolbar_icon is not None:
            self._images["toolbar_button"] = self._scale_image(toolbar_icon, 28)
            self._images["toolbar_status"] = self._scale_image(toolbar_icon, 22)
            self._images["toolbar_log"] = self._scale_image(toolbar_icon, 48)

    # ------------------------------------------------------------------
    def _default_data_dir(self) -> Path | None:
        project = self._project
        if project is None:
            return None
        try:
            return project.paths.data_dir.resolve()
        except FileNotFoundError:
            return project.paths.data_dir

    # ------------------------------------------------------------------
    def _refresh_available_data_files(self) -> None:
        data_dir = self._default_data_dir()
        if data_dir is None:
            self._available_data_files = []
            return
        try:
            files = sorted(p for p in data_dir.rglob("*.dat") if p.is_file())
        except OSError as exc:
            self._available_data_files = []
            self._append_log(f"[DATA] Unable to scan data files: {exc}\n")
            return
        self._available_data_files = files

    # ------------------------------------------------------------------
    def _handle_import_data_file(self, source: Path) -> Path:
        try:
            imported = self._project_manager.import_data_file(source)
        except Exception as exc:  # noqa: BLE001 - surfaced to caller
            self._append_log(f"[DATA] Failed to import {source}: {exc}\n")
            raise
        self._refresh_available_data_files()
        self._update_dirty_ui()
        return imported

    # ------------------------------------------------------------------
    def toggle_theme(self) -> None:
        current = self._style.theme.name
        new_theme = "flatly" if current == "superhero" else "superhero"
        self._style.theme_use(new_theme)
        self.show_toast(f"Theme switched to {new_theme.title()}")

    # ------------------------------------------------------------------
    def load_config(self) -> None:
        self._load_startup_project()

    # ------------------------------------------------------------------
    def _load_startup_project(self) -> None:
        self._app_state.prune_missing()
        self._app_state.save()

        candidates: list[Path] = []
        if self._app_state.last_opened is not None:
            candidates.append(self._app_state.last_opened)
        default_root = self.config_path.parent.resolve()
        if default_root not in candidates:
            candidates.append(default_root)

        project: PlotinatorProject | None = None
        for candidate in candidates:
            try:
                project = self._project_manager.open_project(candidate)
            except FileNotFoundError:
                continue
            except Exception as exc:
                self._append_log(f"[CONFIG] Failed to open project at {candidate}: {exc}\n")
                continue

            if project.paths.root.name == TEMP_PROJECT_FOLDER:
                target_root = candidate if candidate.is_dir() else candidate.parent
                try:
                    project = self._project_manager.save_project_as_dialog(target_root)
                except Exception as exc:  # noqa: BLE001 - surfaced to UI
                    self.show_toast("Project migration failed", level="error")
                    messagebox.showerror(
                        "Plotinator",
                        f"Unable to migrate legacy workspace to {target_root}:\n{exc}",
                        parent=self,
                    )
                    continue

            self._apply_project(project, record_state=True)
            self._write_engine_config(project)
            self._schedule_autosave(reset=True)
            return

        fallback_root = Path.home() / "Plotinator Projects" / "Untitled Project.p10k"
        try:
            project = self._project_manager.new_project(fallback_root)
        except Exception:  # noqa: BLE001 - fallback to application directory
            alt_root = default_root / "Untitled Project.p10k"
            project = self._project_manager.new_project(alt_root)

        self._apply_project(project, record_state=True)
        self._write_engine_config(project)
        self._schedule_autosave(reset=True)
        self.show_toast("Created a new project", level="info")

    # ------------------------------------------------------------------
    def _apply_project(self, project: PlotinatorProject, *, record_state: bool = False) -> None:
        self._project = project
        self.config_path = project.paths.root / CONFIG_PATH
        self._engine_config_path = project.paths.root / CONFIG_PATH
        self.job = project.to_config()
        self.job.base_path = project.paths.data_dir
        self.folder = project.paths.data_dir
        self._current_output_dir = None
        self._hide_preview_pane()
        self.refresh_table()
        self._refresh_available_data_files()
        self._set_project_action_state(True)
        self._update_window_title()

        if record_state:
            self._app_state.record_project(project.paths.root)
            self._app_state.save()
            self._update_recent_projects_menu()

        self._dismiss_autosave_error_dialog()

    # ------------------------------------------------------------------
    def _open_project_path(self, path: Path, *, record_state: bool = True) -> None:
        target = Path(path)
        try:
            project = self._project_manager.open_project(target)
        except FileNotFoundError:
            self.show_toast("Project not found", level="error")
            messagebox.showerror("Plotinator", f"No project located at {target}", parent=self)
            return
        except Exception as exc:  # noqa: BLE001 - surfaced to UI
            self.show_toast("Failed to open project", level="error")
            messagebox.showerror("Plotinator", f"Unable to open project: {exc}", parent=self)
            return

        if project.paths.root.name == TEMP_PROJECT_FOLDER:
            target_root = target if target.is_dir() else target.parent
            try:
                project = self._project_manager.save_project_as_dialog(target_root)
            except Exception as exc:  # noqa: BLE001 - surfaced to UI
                self.show_toast("Project migration failed", level="error")
                messagebox.showerror(
                    "Plotinator",
                    f"Unable to migrate legacy workspace to {target_root}:\n{exc}",
                    parent=self,
                )
                return

        self._apply_project(project, record_state=record_state)
        self._write_engine_config(project)
        self._schedule_autosave(reset=True)
        self.show_toast(f"Project loaded: {project.paths.root.name}", level="success")

    # ------------------------------------------------------------------
    def _update_recent_projects_menu(self) -> None:
        menu = self._recent_menu
        if menu is None:
            return
        menu.delete(0, "end")
        if not self._app_state.recent_projects:
            menu.add_command(label="(empty)", state="disabled")
            return
        for path in self._app_state.recent_projects:
            label = path.name or str(path)
            menu.add_command(label=label, command=lambda p=path: self._open_recent_project(p))

    # ------------------------------------------------------------------
    def _open_recent_project(self, path: Path) -> None:
        if not path.exists() or not (path / "project.json").exists():
            self._app_state.remove_project(path)
            self._app_state.save()
            self._update_recent_projects_menu()
            self.show_toast("Recent project is unavailable", level="warning")
            return
        if not self._confirm_navigation():
            return
        self._open_project_path(path)

    # ------------------------------------------------------------------
    def _update_project_from_job(self) -> None:
        project = self._project
        if project is None:
            return
        project.update_from_config(self.job)
        self.job.base_path = project.paths.data_dir

    # ------------------------------------------------------------------
    def _on_project_modified(self) -> None:
        self._update_project_from_job()
        self._schedule_autosave(reset=False)

    # ------------------------------------------------------------------
    def _write_engine_config(self, project: PlotinatorProject) -> None:
        config_payload = project.to_config().to_dict()
        project.paths.root.mkdir(parents=True, exist_ok=True)
        with (project.paths.root / CONFIG_PATH).open("w", encoding="utf-8") as handle:
            json.dump(config_payload, handle, indent=2)

    # ------------------------------------------------------------------
    def new_project_dialog(self) -> None:
        if not self._confirm_navigation():
            return
        if self._worker and self._worker.is_running():
            warning_message = "Stop the running batch before creating a new project."
            self.show_toast(warning_message, level="warning")
            messagebox.showwarning("Plotinator", warning_message)
            return
        self._stop_runner_thread()

        initial_dir = self.folder or Path.home()
        try:
            initial = initial_dir.resolve()
        except OSError:
            initial = Path.home()

        target = filedialog.asksaveasfilename(
            title="Create Plotinator project",
            defaultextension=".p10k",
            filetypes=[("Plotinator Projects", "*.p10k"), ("All folders", "*.*")],
            initialdir=str(initial),
            initialfile="New Project.p10k",
        )
        if not target:
            return

        target_path = Path(target)
        if target_path.exists():
            try:
                non_empty = any(target_path.iterdir())
            except OSError:
                non_empty = False
            if non_empty and not messagebox.askyesno(
                "Plotinator",
                f"The folder {target_path} already contains files. Continue?",
                parent=self,
            ):
                return

        try:
            project = self._project_manager.new_project(target_path)
        except Exception as exc:  # noqa: BLE001 - surfaced to UI
            self.show_toast("Failed to create project", level="error")
            messagebox.showerror("Plotinator", f"Unable to create project: {exc}", parent=self)
            return

        self._apply_project(project, record_state=True)
        self._write_engine_config(project)
        self._schedule_autosave(reset=True)
        self.show_toast("New project created", level="success")

    # ------------------------------------------------------------------
    def open_project_dialog(self) -> None:
        if not self._confirm_navigation():
            return
        if self._worker and self._worker.is_running():
            warning_message = "Stop the running batch before changing projects."
            self.show_toast(warning_message, level="warning")
            messagebox.showwarning("Plotinator", warning_message)
            return
        self._stop_runner_thread()
        initial_dir = self.folder or Path.home()
        try:
            initial = initial_dir.resolve()
        except OSError:
            initial = Path.home()
        location = filedialog.askdirectory(title="Open Plotinator project", initialdir=str(initial))
        if not location:
            return
        self._open_project_path(Path(location))

    # ------------------------------------------------------------------
    def save_project_as_dialog(self) -> None:
        project = self._project
        if project is None:
            self.show_toast("No project loaded", level="warning")
            return

        if self._worker and self._worker.is_running():
            warning_message = "Stop the running batch before saving to a new location."
            self.show_toast(warning_message, level="warning")
            messagebox.showwarning("Plotinator", warning_message)
            return
        self._stop_runner_thread()

        self._update_project_from_job()

        target = filedialog.asksaveasfilename(
            title="Save Project As",
            defaultextension=".p10k",
            filetypes=[("Plotinator Projects", "*.p10k"), ("All folders", "*.*")],
            initialdir=str(project.paths.root.parent),
            initialfile=f"{project.paths.root.stem}.p10k",
        )
        if not target:
            return

        target_path = Path(target)
        if target_path == project.paths.root:
            self.show_toast("Choose a different location for Save As", level="warning")
            return

        try:
            new_project = self._project_manager.save_project_as_dialog(target_path)
        except FileExistsError as exc:
            self.show_toast("Destination already exists", level="warning")
            messagebox.showerror("Plotinator", str(exc), parent=self)
            return
        except Exception as exc:  # noqa: BLE001 - surfaced to UI
            self.show_toast("Save As failed", level="error")
            messagebox.showerror("Plotinator", f"Unable to save project: {exc}", parent=self)
            return

        self._apply_project(new_project, record_state=True)
        self._write_engine_config(new_project)
        self._schedule_autosave(reset=True)
        self.show_toast("Project saved to new location", level="success")

    # ------------------------------------------------------------------
    def _confirm_navigation(self) -> bool:
        self._update_project_from_job()
        if not self._project_manager.dirty:
            return True
        result = messagebox.askyesnocancel(
            "Plotinator",
            "Save changes before continuing?",
            parent=self,
        )
        if result is None:
            return False
        if result:
            return self.save_config()
        return True

    # ------------------------------------------------------------------
    def _cancel_autosave_timer(self) -> None:
        token = self._autosave_after_id
        if token is None:
            return
        try:
            self.after_cancel(token)
        except Exception:
            pass
        self._autosave_after_id = None

    # ------------------------------------------------------------------
    def _schedule_autosave(self, *, reset: bool) -> None:
        if reset:
            self._cancel_autosave_timer()

        interval = max(0, int(self._app_state.autosave_minutes))
        if interval <= 0:
            return
        if self._autosave_after_id is not None:
            return

        delay_ms = interval * 60 * 1000
        self._autosave_after_id = self.after(delay_ms, self._perform_autosave)

    # ------------------------------------------------------------------
    def _perform_autosave(self) -> None:
        self._autosave_after_id = None
        if self._autosave_in_progress:
            self._schedule_autosave(reset=False)
            return

        self._update_project_from_job()
        if not self._project_manager.dirty:
            self._schedule_autosave(reset=False)
            return

        self._autosave_in_progress = True

        def _worker() -> None:
            try:
                saved_project = self._project_manager.save_project()
                self._write_engine_config(saved_project)
            except Exception as exc:  # noqa: BLE001 - surfaced to UI
                self.after(0, lambda e=exc: self._handle_save_failure(e, autosave=True))
            else:
                self.after(0, lambda p=saved_project: self._handle_autosave_success(p))
            finally:
                self._autosave_in_progress = False
                self.after(0, lambda: self._schedule_autosave(reset=False))

        threading.Thread(target=_worker, daemon=True).start()

    # ------------------------------------------------------------------
    def _handle_autosave_success(self, project: PlotinatorProject) -> None:
        self._project = project
        self.folder = project.paths.data_dir
        self._dismiss_autosave_error_dialog()
        timestamp = datetime.now().astimezone().strftime("%H:%M:%S")
        self.status_var.set(f"Autosaved at {timestamp}")

    # ------------------------------------------------------------------
    def _handle_save_failure(self, error: Exception, *, autosave: bool) -> None:
        message = f"Failed to save project: {error}"
        self._autosave_last_error = message
        if autosave:
            self.show_toast("Autosave failed", level="error")
            self._show_autosave_error_dialog(message)
        else:
            self.show_toast(message, level="error")
            messagebox.showerror("Plotinator", message, parent=self)

    # ------------------------------------------------------------------
    def _show_autosave_error_dialog(self, message: str) -> None:
        self._autosave_error_message.set(message)
        dialog = self._autosave_error_dialog
        if dialog is not None and dialog.winfo_exists():
            dialog.lift()
            return

        dialog = ttkb.Toplevel(self)
        dialog.title("Autosave issue")
        dialog.geometry("420x200")
        dialog.transient(self)

        ttkb.Label(
            dialog,
            textvariable=self._autosave_error_message,
            wraplength=360,
            justify="left",
            padding=12,
        ).pack(fill="both", expand=True)

        button_frame = ttkb.Frame(dialog, padding=(12, 0, 12, 12))
        button_frame.pack(fill="x")

        ttkb.Button(
            button_frame,
            text="Retry now",
            bootstyle="success",
            command=self._retry_autosave_from_dialog,
        ).pack(side="right")
        ttkb.Button(
            button_frame,
            text="Dismiss",
            command=self._dismiss_autosave_error_dialog,
        ).pack(side="right", padx=(0, 8))

        dialog.protocol("WM_DELETE_WINDOW", self._dismiss_autosave_error_dialog)
        self._autosave_error_dialog = dialog

    # ------------------------------------------------------------------
    def _retry_autosave_from_dialog(self) -> None:
        self._dismiss_autosave_error_dialog()
        self.after(0, self.save_config)

    # ------------------------------------------------------------------
    def _dismiss_autosave_error_dialog(self) -> None:
        dialog = self._autosave_error_dialog
        if dialog is not None and dialog.winfo_exists():
            dialog.destroy()
        self._autosave_error_dialog = None

    # ------------------------------------------------------------------
    def _on_close(self) -> None:
        if not self._confirm_navigation():
            return
        self._stop_runner_thread()
        self._cancel_autosave_timer()
        self._dismiss_autosave_error_dialog()
        self._app_state.save()
        try:
            self.destroy()
        except tk.TclError:
            pass


    def save_config(self) -> bool:
        project = self._project
        if project is None:
            return False

        self._update_project_from_job()
        try:
            project = self._project_manager.save_project()
        except Exception as exc:  # noqa: BLE001 - surfaced to UI
            self._handle_save_failure(exc, autosave=False)
            return False

        self._project = project
        self._write_engine_config(project)
        self.folder = project.paths.data_dir
        self.show_toast("Project saved", level="success")
        self._app_state.record_project(project.paths.root)
        self._app_state.save()
        self._update_recent_projects_menu()
        self._cancel_autosave_timer()
        self._schedule_autosave(reset=True)
        self._dismiss_autosave_error_dialog()
        return True

    # ------------------------------------------------------------------
    def _reload_from_mapping(self, mapping: dict) -> bool:
        project = self._project
        if project is None:
            self.show_toast("No project loaded", level="warning")
            return False
        try:
            new_config = load_config(mapping, base_path=project.paths.data_dir)
        except ConfigError as exc:
            error_message = f"Invalid configuration change: {exc}"
            self._append_log(f"[CONFIG] {error_message}\n")
            self.show_toast(error_message, level="error")
            return False
        project.update_from_config(updated_config)
        self.job = project.config
        self.refresh_table()
        self._refresh_available_data_files()
        self._update_dirty_ui()
        return True

    # ------------------------------------------------------------------
    def _require_project(self) -> PlotinatorProject:
        project = self._project
        if project is None:
            raise RuntimeError("No project loaded")
        return project

    # ------------------------------------------------------------------
    def _on_project_loaded(self, project: PlotinatorProject) -> None:
        self._project = project
        self.job = project.config
        self.folder = project.paths.root
        self._project_location = project.paths.root
        runtime_config = self._write_runtime_config(project)
        self._set_status(f"Project loaded: {project.paths.root}")
        self._append_log(f"[PROJECT] Loaded project from {project.paths.root}\n")
        self.refresh_table()
        self._refresh_available_data_files()
        self._update_dirty_ui()
        if runtime_config.exists():
            self._append_log(f"[PROJECT] Runtime config: {runtime_config}\n")

    # ------------------------------------------------------------------
    def _write_runtime_config(self, project: PlotinatorProject) -> Path:
        runtime_path = project.paths.root / "config.runtime.json"
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        payload = project.to_config().to_dict()
        with runtime_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        self.config_path = runtime_path
        return runtime_path

    # ------------------------------------------------------------------
    def _update_dirty_ui(self) -> None:
        project = self._project
        if project is None:
            self.title(self._base_window_title)
            return
        label = project.metadata.label or project.paths.root.name
        dirty_marker = " *" if self._project_manager.dirty else ""
        self.title(f"{label}{dirty_marker} – {self._base_window_title}")

    # ------------------------------------------------------------------
    def refresh_table(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        job = self.job
        if not isinstance(job, PlotinatorConfig):
            return
        for fit in job.fits:
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
        if not folder:
            return

        if self._worker and self._worker.is_running():
            warning_message = "Stop the running batch before changing folders."
            self.show_toast(warning_message, level="warning")
            messagebox.showwarning("Plotinator", warning_message)
            return

        self._stop_runner_thread()
        selected = Path(folder).resolve()
        self.folder = selected
        self._project_location = selected
        self.show_toast(f"Project set to {self.folder}")
        self.load_config()

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
    def run_batch(self) -> None:
        worker = self._worker
        if worker and worker.is_running():
            info_message = "Batch already running."
            self._append_log(f"[WARN] {info_message}\n")
            self.show_toast(info_message, level="warning")
            return

        if not self.save_project(show_feedback=False):
            return
        project = self._project
        if project is None:
            self.show_toast("No project loaded", level="warning")
            return
        config_path = self._engine_config_path
        if config_path is None:
            config_path = self._materialise_engine_config(project)

        self.progress.configure(value=0)
        self._clear_logs(user_action=False)
        self._reset_preview_state()
        self._progress_total = 0
        self._progress_completed = 0
        self._worker = BatchWorker(config_path)
        self._event_queue = self._worker.start()
        self._set_status("Launching batch…")
        self.after(100, self._poll_events)


    def _poll_events(self) -> None:
        if self._event_queue is None or self._worker is None:
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

        if (not self._worker.is_running()) and self._event_queue.empty():
            self._worker = None
            self._event_queue = None
            return

        self.after(100, self._poll_events)

    # ------------------------------------------------------------------
    def _stop_runner_thread(self) -> None:
        """Request cancellation of the in-process engine runner and drain events."""

        worker = self._worker
        if worker is not None:
            worker.stop()
        self._worker = None
        queued_events: queue.Queue[dict[str, Any]] | None = self._event_queue
        self._event_queue = None
        if queued_events is not None:
            try:
                while True:
                    event = queued_events.get_nowait()
                    self._handle_engine_event(event)
            except queue.Empty:
                pass

    # ------------------------------------------------------------------
    def stop_batch(self) -> None:
        """Public helper for stop controls to shut down the batch thread."""
        worker = self._worker
        if worker is None or not worker.is_running():
            self.show_toast("No batch is currently running", level="info")
            return
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
            output_dir = event.get("output_dir")
            if output_dir:
                try:
                    self._current_output_dir = Path(str(output_dir)).resolve()
                except OSError:
                    self._current_output_dir = Path(str(output_dir))
            else:
                self._current_output_dir = None
            self._latest_preview_title = None
            return

        if etype == "plot-start":
            title = event.get("title", "Untitled")
            self._append_log(f"[RUN] Processing: {title}\n")
            self._set_status(f"Processing plot: {title}")
            self._on_preview_plot_start(title)
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
            preview_payload = event.get("preview")
            if isinstance(preview_payload, dict):
                preview_payload = dict(preview_payload)
            else:
                preview_payload = None
            result_payload = event.get("result")
            if isinstance(result_payload, dict):
                result_payload = dict(result_payload)
                if preview_payload is not None:
                    preview_payload.setdefault("result", result_payload)
            else:
                result_payload = None
            self.render_batch_preview(title, preview_payload, result_payload)
            return

        if etype == "plot-error":
            self._progress_completed += 1
            self._update_progress_bar()
            title = event.get("title", "Untitled")
            error_msg = event.get("error", "Unknown error")
            self._append_log(f"[X] Error in {title}: {error_msg}\n")
            self.show_toast(f"Plot failed: {title}", level="error")
            self._set_status(f"Plot error: {title}")
            self._on_preview_plot_error(title, error_msg)
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
            self._on_preview_job_complete(event)
            self._event_queue = None
            self._worker = None
            return

        if etype == "job-error":
            error_msg = event.get("error", "Batch failed")
            self._append_log(f"[X] {error_msg}\n")
            self.show_toast(error_msg, level="error")
            messagebox.showerror("Plotinator", error_msg)
            self._set_status(f"Batch failed: {error_msg}")
            self._on_preview_job_failure(error_msg)
            self._event_queue = None
            self._worker = None
            return

        if etype == "job-exception":
            error_msg = event.get("error", "Batch failed")
            self._append_log(f"[X] {error_msg}\n")
            self.show_toast(error_msg, level="error")
            messagebox.showerror("Plotinator", error_msg)
            self._set_status(f"Batch failed: {error_msg}")
            self._on_preview_job_failure(error_msg)
            self._event_queue = None
            self._worker = None
            return

        if etype == "job-cancelled":
            self._append_log("[CANCELLED] Batch cancelled by user.\n")
            self.show_toast("Batch cancelled", level="warning")
            self._set_status("Batch cancelled")
            self._on_preview_job_failure("Batch cancelled")
            self._event_queue = None
            self._worker = None
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
        self._log_history.append(text)

        def _write() -> None:
            self.log_text.insert(tk.END, text)
            self.log_text.see(tk.END)
            self._apply_log_filter()

        self.after(0, _write)

    # ------------------------------------------------------------------
    def _queue_log_filter_update(self, *_: object) -> None:
        if self._log_filter_job is not None:
            try:
                self.after_cancel(self._log_filter_job)
            except tk.TclError:
                pass
        self._log_filter_job = self.after(150, self._apply_log_filter)

    # ------------------------------------------------------------------
    def _apply_log_filter(self) -> None:
        self._log_filter_job = None
        pattern = self._log_filter_var.get().strip()
        self.log_text.tag_remove("filter_match", "1.0", tk.END)

        if not pattern:
            self._log_matches_var.set("")
            return

        start = "1.0"
        matches = 0
        while True:
            idx = self.log_text.search(pattern, start, stopindex=tk.END, nocase=True)
            if not idx:
                break
            end_idx = f"{idx}+{len(pattern)}c"
            self.log_text.tag_add("filter_match", idx, end_idx)
            start = end_idx
            matches += 1

        if matches:
            label = "match" if matches == 1 else "matches"
            self._log_matches_var.set(f"{matches} {label}")
        else:
            self._log_matches_var.set("No matches")

    # ------------------------------------------------------------------
    def _focus_log_filter(self, event=None) -> str:
        self._log_filter_entry.focus_set()
        self._log_filter_entry.select_range(0, tk.END)
        return "break"

    # ------------------------------------------------------------------
    def _clear_logs(self, *, user_action: bool) -> None:
        if self._log_filter_job is not None:
            try:
                self.after_cancel(self._log_filter_job)
            except tk.TclError:
                pass
            self._log_filter_job = None
        self._log_history.clear()
        self.log_text.delete("1.0", tk.END)
        self._apply_log_filter()
        if user_action:
            self.show_toast("Log cleared", level="info")

    # ------------------------------------------------------------------
    def _save_logs(self) -> None:
        if not self._log_history:
            self.show_toast("No log entries to save yet", level="info")
            return

        file_path = filedialog.asksaveasfilename(
            title="Save log",
            defaultextension=".log",
            filetypes=[
                ("Log files", "*.log"),
                ("Text files", "*.txt"),
                ("All files", "*.*"),
            ],
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", encoding="utf-8") as handle:
                handle.write("".join(self._log_history))
        except OSError as exc:
            self.show_toast("Failed to save logs", level="error")
            self._append_log(f"[X] Could not save logs: {exc}\n")
            return

        self.show_toast("Logs saved", level="success")
        self._append_log(f"[INFO] Logs saved to: {file_path}\n")

    # ------------------------------------------------------------------
    def open_latest_report(self) -> None:
        project = self._project
        if project is None:
            self.show_toast("No project loaded", level="warning")
            return
        outputs = project.paths.exports_dir
        if not outputs.exists():
            info_message = "Project has no exports yet. Run a batch first."
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

        try:
            if pdf_report.exists():
                webbrowser.open(pdf_report.resolve().as_uri())
            elif md_report.exists():
                webbrowser.open(md_report.resolve().as_uri())
            else:
                webbrowser.open(latest_dir.resolve().as_uri())
        except Exception as exc:
            self._append_log(f"[REPORT] Could not open report: {exc}\n")
            self.show_toast("Could not open report", level="error")

    # ------------------------------------------------------------------
    def show_toast(self, message: str, level: str = "info") -> None:
        _show_toast(self, message, level)

    # ------------------------------------------------------------------
    def destroy(self) -> None:  # type: ignore[override]
        stop_runner = getattr(self, "_stop_runner_thread", None)
        if callable(stop_runner):
            stop_runner()
        self._cleanup_all_preview_temp_dirs()
        super().destroy()

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
            data = fit.to_dict(relative_to=self._require_project().paths.data_dir)
        else:
            data = copy.deepcopy(base)
        style_data = copy.deepcopy(data.get("style", {})) if isinstance(data.get("style"), dict) else {}

        editor = ttkb.Toplevel(self)
        editor.title("Fit details")
        editor.geometry("700x560")
        editor.grab_set()

        notebook = ttkb.Notebook(editor)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        general_tab = ttkb.Frame(notebook, padding=10)
        layout_tab = ttkb.Frame(notebook, padding=10)
        style_tab = ttkb.Frame(notebook, padding=10)
        datasets_tab = ttkb.Frame(notebook, padding=10)
        notebook.add(general_tab, text="General")
        notebook.add(layout_tab, text="Layout")
        notebook.add(style_tab, text="Style")
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

        # Style tab ----------------------------------------------------
        style_tab.columnconfigure(1, weight=1)
        style_tab.columnconfigure(3, weight=1)

        def _extract_window_entries(value: object) -> tuple[str, str]:
            lo_text = ""
            hi_text = ""
            if isinstance(value, (list, tuple)):
                if len(value) > 0 and value[0] not in (None, ""):
                    lo_text = str(value[0])
                if len(value) > 1 and value[1] not in (None, ""):
                    hi_text = str(value[1])
            elif isinstance(value, dict):
                if value.get("min") not in (None, ""):
                    lo_text = str(value.get("min"))
                if value.get("max") not in (None, ""):
                    hi_text = str(value.get("max"))
            elif isinstance(value, str):
                stripped = value.strip().strip("[]")
                parts = [part.strip() for part in stripped.split(",") if part.strip()]
                if parts:
                    lo_text = parts[0]
                if len(parts) > 1:
                    hi_text = parts[1]
            elif value not in (None, ""):
                try:
                    lo_text = str(float(value))
                except (TypeError, ValueError):
                    lo_text = str(value)
            return lo_text, hi_text

        def _format_ticks_value(value: object) -> str:
            if value in (None, ""):
                return ""
            if isinstance(value, (list, tuple, dict)):
                try:
                    return json.dumps(value)
                except TypeError:
                    return str(value)
            return str(value)

        style_entries: dict[str, ttkb.Entry] = {}

        ttkb.Label(style_tab, text="X axis window").grid(row=0, column=0, sticky="w", padx=5, pady=6)
        x_min_entry = ttkb.Entry(style_tab, width=12)
        x_min_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=6)
        ttkb.Label(style_tab, text="to").grid(row=0, column=2, sticky="w", padx=5, pady=6)
        x_max_entry = ttkb.Entry(style_tab, width=12)
        x_max_entry.grid(row=0, column=3, sticky="ew", padx=5, pady=6)
        x_lo, x_hi = _extract_window_entries(style_data.get("x_window"))
        if x_lo:
            x_min_entry.insert(0, x_lo)
        if x_hi:
            x_max_entry.insert(0, x_hi)
        style_entries["x_window_min"] = x_min_entry
        style_entries["x_window_max"] = x_max_entry

        ttkb.Label(style_tab, text="Y axis window").grid(row=1, column=0, sticky="w", padx=5, pady=6)
        y_min_entry = ttkb.Entry(style_tab, width=12)
        y_min_entry.grid(row=1, column=1, sticky="ew", padx=5, pady=6)
        ttkb.Label(style_tab, text="to").grid(row=1, column=2, sticky="w", padx=5, pady=6)
        y_max_entry = ttkb.Entry(style_tab, width=12)
        y_max_entry.grid(row=1, column=3, sticky="ew", padx=5, pady=6)
        y_lo, y_hi = _extract_window_entries(style_data.get("y_window"))
        if y_lo:
            y_min_entry.insert(0, y_lo)
        if y_hi:
            y_max_entry.insert(0, y_hi)
        style_entries["y_window_min"] = y_min_entry
        style_entries["y_window_max"] = y_max_entry

        ttkb.Label(style_tab, text="X axis ticks").grid(row=2, column=0, sticky="w", padx=5, pady=6)
        x_ticks_entry = ttkb.Entry(style_tab)
        x_ticks_entry.grid(row=2, column=1, columnspan=3, sticky="ew", padx=5, pady=6)
        x_ticks_entry.insert(0, _format_ticks_value(style_data.get("x_ticks")))
        style_entries["x_ticks"] = x_ticks_entry

        ttkb.Label(style_tab, text="Y axis ticks").grid(row=3, column=0, sticky="w", padx=5, pady=6)
        y_ticks_entry = ttkb.Entry(style_tab)
        y_ticks_entry.grid(row=3, column=1, columnspan=3, sticky="ew", padx=5, pady=6)
        y_ticks_entry.insert(0, _format_ticks_value(style_data.get("y_ticks")))
        style_entries["y_ticks"] = y_ticks_entry

        ttkb.Label(
            style_tab,
            text="Leave fields blank for automatic ranges/ticks. Use '*' for defaults or JSON lists for custom ticks.",
            wraplength=480,
            bootstyle="info",
        ).grid(row=4, column=0, columnspan=4, sticky="w", padx=5, pady=(6, 0))

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
            dialog = DatasetDialog(
                editor,
                data_dir=self._default_data_dir(),
                data_files=self._available_data_files,
                import_data_file=self._handle_import_data_file,
            )
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
            dialog = DatasetDialog(
                editor,
                dataset=current,
                data_dir=self._default_data_dir(),
                data_files=self._available_data_files,
                import_data_file=self._handle_import_data_file,
            )
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
            style_overrides = copy.deepcopy(style_data)

            def _parse_window(min_key: str, max_key: str, dest_key: str) -> None:
                min_text = style_entries[min_key].get().strip()
                max_text = style_entries[max_key].get().strip()

                def _convert(value: str) -> float | None:
                    if not value or value == "*":
                        return None
                    try:
                        return float(value)
                    except ValueError:
                        return None

                if not min_text and not max_text:
                    style_overrides.pop(dest_key, None)
                    return

                lo_value = _convert(min_text)
                hi_value = _convert(max_text)
                if lo_value is None and hi_value is None:
                    style_overrides.pop(dest_key, None)
                else:
                    style_overrides[dest_key] = [lo_value, hi_value]

            def _parse_ticks(entry_key: str, dest_key: str) -> None:
                text = style_entries[entry_key].get().strip()
                if not text:
                    style_overrides.pop(dest_key, None)
                    return
                if text.startswith("[") or text.startswith("{"):
                    try:
                        style_overrides[dest_key] = json.loads(text)
                        return
                    except json.JSONDecodeError:
                        pass
                try:
                    style_overrides[dest_key] = float(text)
                except ValueError:
                    style_overrides[dest_key] = text

            _parse_window("x_window_min", "x_window_max", "x_window")
            _parse_window("y_window_min", "y_window_max", "y_window")
            _parse_ticks("x_ticks", "x_ticks")
            _parse_ticks("y_ticks", "y_ticks")

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
                self._refresh_available_data_files()
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
    def __init__(
        self,
        master: tk.Misc,
        dataset: dict | None = None,
        *,
        data_dir: Path | None = None,
        data_files: Sequence[Path] | None = None,
        import_data_file: Callable[[Path], Path] | None = None,
    ) -> None:
        super().__init__(master)
        self.title("Dataset settings")
        self.result: dict | None = None
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        if data_dir is not None:
            try:
                self._data_dir = data_dir.resolve()
            except FileNotFoundError:
                self._data_dir = data_dir
        else:
            self._data_dir = None
        self._import_data_file = import_data_file
        resolved_files: list[Path] = []
        for path in data_files or []:
            try:
                resolved_files.append(path.resolve())
            except FileNotFoundError:
                resolved_files.append(path)
        self._available_files: list[Path] = sorted(resolved_files)
        self._file_selector: ttkb.Combobox | None = None

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
            dialog_options: dict[str, object] = {
                "title": "Select data file",
                "filetypes": (("Data files", "*.dat"), ("All files", "*.*")),
            }
            if self._data_dir is not None and self._data_dir.exists():
                dialog_options["initialdir"] = str(self._data_dir)
            chosen = filedialog.askopenfilename(**dialog_options)
            if chosen:
                selected = self._ensure_local_copy(Path(chosen))
                if selected is None:
                    return
                self._set_path_entry(selected)
                self._select_file_in_combobox(selected)

        ttkb.Button(self, text="Browse", command=browse, bootstyle="secondary-outline").grid(
            row=2, column=2, padx=10, pady=6
        )

        if self._available_files:
            ttkb.Label(self, text="Available data files").grid(
                row=3, column=0, sticky="w", padx=10, pady=6
            )
            display_values = [self._format_display_path(path) for path in self._available_files]
            self._file_selector = ttkb.Combobox(self, values=display_values, state="readonly")
            self._file_selector.grid(row=3, column=1, columnspan=2, sticky="ew", padx=10, pady=6)
            self._file_selector.bind("<<ComboboxSelected>>", self._on_data_file_selected)
            current_path_text = self.path_entry.get().strip()
            if current_path_text:
                resolved_current = self._resolve_candidate(current_path_text)
                for idx, file_path in enumerate(self._available_files):
                    if resolved_current == file_path:
                        self._file_selector.current(idx)
                        break
        else:
            display_values = []

        ttkb.Label(self, text="X column").grid(row=4, column=0, sticky="w", padx=10, pady=6)
        self.x_spin = ttkb.Spinbox(self, from_=1, to=128, width=6)
        self.x_spin.grid(row=4, column=1, sticky="w", padx=10, pady=6)
        self.x_spin.set(str(columns.get("x", 1)))

        ttkb.Label(self, text="Y column").grid(row=5, column=0, sticky="w", padx=10, pady=6)
        self.y_spin = ttkb.Spinbox(self, from_=1, to=128, width=6)
        self.y_spin.grid(row=5, column=1, sticky="w", padx=10, pady=6)
        self.y_spin.set(str(columns.get("y", 2)))

        ttkb.Label(self, text="Error column").grid(row=4, column=2, sticky="w", padx=10, pady=6)
        self.error_entry = ttkb.Entry(self, width=6)
        if columns.get("error") not in (None, ""):
            self.error_entry.insert(0, str(columns.get("error")))
        self.error_entry.grid(row=4, column=3, sticky="w", padx=10, pady=6)

        ttkb.Label(self, text="Weight column").grid(row=5, column=2, sticky="w", padx=10, pady=6)
        self.weight_entry = ttkb.Entry(self, width=6)
        if columns.get("weight") not in (None, ""):
            self.weight_entry.insert(0, str(columns.get("weight")))
        self.weight_entry.grid(row=5, column=3, sticky="w", padx=10, pady=6)

        ttkb.Label(self, text="Line color").grid(row=6, column=0, sticky="w", padx=10, pady=6)
        self.color_entry = ttkb.Entry(self)
        self.color_entry.grid(row=6, column=1, columnspan=2, sticky="ew", padx=10, pady=6)
        self.color_entry.insert(0, style.get("line_color", ""))

        ttkb.Label(self, text="Preprocessing (JSON list)").grid(
            row=7,
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
        self.preprocess_text.grid(row=7, column=1, columnspan=3, sticky="nsew", padx=10, pady=6)

        self.columnconfigure(1, weight=1)
        self.columnconfigure(2, weight=0)
        self.rowconfigure(7, weight=1)

        button_frame = ttkb.Frame(self)
        button_frame.grid(row=8, column=0, columnspan=4, sticky="e", padx=10, pady=10)
        ttkb.Button(button_frame, text="Cancel", command=self.destroy).pack(side="right", padx=5)
        ttkb.Button(
            button_frame,
            text="Save",
            command=self._on_save,
            bootstyle="success",
        ).pack(side="right", padx=5)

        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _format_display_path(self, path: Path) -> str:
        try:
            if self._data_dir is not None:
                return path.relative_to(self._data_dir).as_posix()
        except ValueError:
            pass
        return path.as_posix()

    def _resolve_candidate(self, raw_path: str | Path) -> Path:
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            if self._data_dir is not None:
                candidate = self._data_dir / candidate
            else:
                candidate = Path.cwd() / candidate
        try:
            return candidate.resolve()
        except FileNotFoundError:
            return candidate

    def _refresh_file_selector(self) -> None:
        if not self._file_selector:
            return
        values = [self._format_display_path(path) for path in self._available_files]
        self._file_selector.configure(values=values)

    def _add_available_file(self, path: Path) -> None:
        try:
            resolved = path.resolve()
        except FileNotFoundError:
            resolved = path
        if resolved not in self._available_files:
            self._available_files.append(resolved)
            self._available_files.sort()
            self._refresh_file_selector()

    def _set_path_entry(self, path: Path) -> None:
        display_value = self._format_display_path(path)
        self.path_entry.delete(0, tk.END)
        self.path_entry.insert(0, display_value)

    def _select_file_in_combobox(self, path: Path) -> None:
        selector = self._file_selector
        if selector is None:
            return
        try:
            resolved = path.resolve()
        except FileNotFoundError:
            resolved = path
        for idx, candidate in enumerate(self._available_files):
            if candidate == resolved:
                selector.current(idx)
                break

    def _ensure_local_copy(self, path: Path) -> Path | None:
        try:
            resolved_path = path.resolve()
        except FileNotFoundError:
            resolved_path = path
        if self._data_dir is None or self._import_data_file is None:
            self._add_available_file(resolved_path)
            return resolved_path
        try:
            data_root = self._data_dir.resolve()
        except FileNotFoundError:
            data_root = self._data_dir
        try:
            resolved_path.relative_to(data_root)
            self._add_available_file(resolved_path)
            return resolved_path
        except ValueError:
            pass
        try:
            imported_path = self._import_data_file(resolved_path)
        except Exception as exc:  # noqa: BLE001 - surfaced via toast
            self.show_toast(f"Failed to import data file: {exc}", level="error")
            return None
        self._add_available_file(imported_path)
        self.show_toast(f"Imported {imported_path.name} into project", level="info")
        return imported_path

    def _on_data_file_selected(self, _event: tk.Event | None = None) -> None:
        if not self._file_selector:
            return
        index = self._file_selector.current()
        if index < 0 or index >= len(self._available_files):
            return
        selected_path = self._available_files[index]
        self._set_path_entry(selected_path)

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

        path_raw = self.path_entry.get().strip()
        if not path_raw:
            notify("Select a data file before saving.", focus_widget=self.path_entry)
            return

        resolved_path = self._resolve_candidate(path_raw)
        if not resolved_path.exists() and self._data_dir is not None:
            target = Path(path_raw)
            if target.name:
                try:
                    matches = list(self._data_dir.rglob(target.name))
                except OSError:
                    matches = []
                if matches:
                    resolved_path = matches[0]
        if not resolved_path.exists():
            notify(f"Data file not found: {path_raw}", focus_widget=self.path_entry)
            return

        local_path = self._ensure_local_copy(resolved_path)
        if local_path is None:
            return
        resolved_path = local_path

        if self._data_dir is not None:
            try:
                path_value = resolved_path.relative_to(self._data_dir).as_posix()
            except ValueError:
                path_value = resolved_path.as_posix()
        else:
            path_value = resolved_path.as_posix()

        self.path_entry.delete(0, tk.END)
        self.path_entry.insert(0, path_value)
        self._select_file_in_combobox(resolved_path)

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

        data_source = {"path": path_value, "columns": columns, "preprocessing": preprocessing}

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
   
def main() -> int:
    app = PlotinatorApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
