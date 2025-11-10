# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build specification for Plotinator Open Beta v1.0 multi-entry executables."""

from __future__ import annotations

import os, sys
import shutil
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# Safely compute the root path regardless of __file__ availability
try:
    ROOT = Path(os.path.abspath(__file__)).resolve().parents[1]
except NameError:
    ROOT = Path(sys.argv[0]).resolve().parents[1]


def _gather_package_modules(*package_names: str) -> list[str]:
    """Collect all submodules for the given packages."""
    modules: set[str] = set()
    for name in package_names:
        modules.update(collect_submodules(name))
    return sorted(modules)


common_hiddenimports = _gather_package_modules("engine", "config", "plotinator", "reports")


common_datas: list[tuple[str, str]] = []


def _add_file(source: Path, target: Path | str) -> None:
    if not source.is_file():
        return
    rel = Path(target)
    common_datas.append((str(source), rel.as_posix()))


def _add_tree(source_dir: Path, target_dir: str) -> None:
    if not source_dir.is_dir():
        return
    for item in source_dir.rglob("*"):
        if item.is_file():
            relative = item.relative_to(source_dir)
            destination = Path(target_dir) / relative
            common_datas.append((str(item), destination.as_posix()))


_add_file(ROOT / "config.json", "config.json")
_add_tree(ROOT / "data", "data")
_add_tree(ROOT / "plotinator" / "config", "plotinator/config")


common_binaries: list[tuple[str, str]] = []


def _add_binary(path: str | None, target_dir: str = "external") -> None:
    if not path:
        return
    candidate = Path(path)
    if not candidate.exists():
        return
    common_binaries.append((str(candidate), Path(target_dir, candidate.name).as_posix()))


_add_binary(os.environ.get("GNUPLOT_PATH") or shutil.which("gnuplot"))
_add_binary(os.environ.get("PANDOC_PATH") or shutil.which("pandoc"))
_add_binary(os.environ.get("WKHTMLTOPDF_PATH") or shutil.which("wkhtmltopdf"))


cli_script = ROOT / "plot_manager.py"
gui_script = ROOT / "plotinator_gui.py"
report_script = ROOT / "generate_pdf.py"


# CLI executable -------------------------------------------------------------
cli_analysis = Analysis(
    [str(cli_script)],
    pathex=[str(ROOT)],
    binaries=list(common_binaries),
    datas=list(common_datas),
    hiddenimports=list(common_hiddenimports),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
cli_pyz = PYZ(cli_analysis.pure, cli_analysis.zipped_data, cipher=block_cipher)
cli_exe = EXE(
    cli_pyz,
    cli_analysis.scripts,
    [],
    exclude_binaries=True,
    name="plotinator-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# GUI executable -------------------------------------------------------------
gui_analysis = Analysis(
    [str(gui_script)],
    pathex=[str(ROOT)],
    binaries=list(common_binaries),
    datas=list(common_datas),
    hiddenimports=list(common_hiddenimports),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
gui_pyz = PYZ(gui_analysis.pure, gui_analysis.zipped_data, cipher=block_cipher)
gui_exe = EXE(
    gui_pyz,
    gui_analysis.scripts,
    [],
    exclude_binaries=True,
    name="plotinator-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# Reporting helper executable -----------------------------------------------
report_analysis = Analysis(
    [str(report_script)],
    pathex=[str(ROOT)],
    binaries=list(common_binaries),
    datas=list(common_datas),
    hiddenimports=list(common_hiddenimports),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
report_pyz = PYZ(report_analysis.pure, report_analysis.zipped_data, cipher=block_cipher)
report_exe = EXE(
    report_pyz,
    report_analysis.scripts,
    [],
    exclude_binaries=True,
    name="plotinator-report",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

bundle = COLLECT(
    cli_exe,
    gui_exe,
    report_exe,
    cli_analysis.binaries,
    cli_analysis.zipfiles,
    cli_analysis.datas,
    gui_analysis.binaries,
    gui_analysis.zipfiles,
    gui_analysis.datas,
    report_analysis.binaries,
    report_analysis.zipfiles,
    report_analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="plotinator-bundle",
)
