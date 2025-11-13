"""Top-level package metadata for Plotinator Open Beta v1.0."""

from __future__ import annotations

import re
from importlib import metadata as _metadata
from pathlib import Path

__all__ = ["__version__"]

try:
    __version__ = _metadata.version("plotinator-open-beta")
except _metadata.PackageNotFoundError:  # pragma: no cover - fallback for local runs
    _fallback = "0.0.0"
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        text = pyproject_path.read_text(encoding="utf-8")
    except OSError:
        __version__ = _fallback
    else:
        match = re.search(r'^version\s*=\s*"(?P<version>[^"\n]+)"', text, re.MULTILINE)
        __version__ = match.group("version") if match else _fallback
