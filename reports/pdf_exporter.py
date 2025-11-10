"""Utilities for exporting Markdown reports via Pandoc."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable

import pypandoc

PANDOC_ENV_VAR = "PANDOC_PATH"
DEFAULT_EXTRA_ARGS = {
    "pdf": ["--pdf-engine=wkhtmltopdf", "--standalone"],
}

__all__ = ["ensure_pandoc_available", "export_document", "export_pdf"]


def ensure_pandoc_available() -> str:
    """Ensure Pandoc is available and return its executable path."""
    env_path = os.environ.get(PANDOC_ENV_VAR)
    if env_path:
        env_path = os.path.abspath(env_path)
        if os.path.isfile(env_path):
            bin_dir = os.path.dirname(env_path)
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
            pypandoc.pandoc_path = env_path
            return env_path

    try:
        detected = pypandoc.get_pandoc_path()
        return detected
    except OSError:
        pass

    which_path = shutil.which("pandoc")
    if which_path:
        pypandoc.pandoc_path = which_path
        return which_path

    raise RuntimeError(
        "Pandoc executable not found. Install Pandoc or set the "
        "PANDOC_PATH environment variable to its location."
    )


def export_document(
    markdown_path: str | Path,
    *,
    output_format: str = "pdf",
    output_path: str | Path | None = None,
    extra_args: Iterable[str] | None = None,
) -> Path:
    """Export a Markdown file to the requested format using Pandoc."""
    ensure_pandoc_available()

    md_path = Path(markdown_path).resolve()
    out_dir = md_path.parent

    if output_path is None:
        suffix = f".{output_format}" if not output_format.startswith(".") else output_format
        out_path = md_path.with_suffix(suffix)
    else:
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

    args = (
        list(extra_args)
        if extra_args is not None
        else list(DEFAULT_EXTRA_ARGS.get(output_format, []))
    )

    cwd = os.getcwd()
    os.chdir(out_dir)
    try:
        target_name = (
            out_path.name
            if out_path.parent == out_dir
            else md_path.with_suffix(f".{output_format}").name
        )
        pypandoc.convert_file(
            md_path.name,
            to=output_format,
            format="md",
            outputfile=target_name,
            extra_args=args or None,
        )
        produced_path = out_dir / target_name
        if produced_path != out_path:
            shutil.move(produced_path, out_path)
    finally:
        os.chdir(cwd)

    return out_path.resolve()


def export_pdf(
    markdown_path: str | Path,
    *,
    output_path: str | Path | None = None,
    extra_args: Iterable[str] | None = None,
) -> Path:
    """Export the Markdown file to a PDF."""
    return export_document(
        markdown_path,
        output_format="pdf",
        output_path=output_path,
        extra_args=extra_args,
    )
