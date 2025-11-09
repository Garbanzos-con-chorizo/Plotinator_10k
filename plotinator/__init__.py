"""Top-level package metadata for Plotinator 10k."""

from __future__ import annotations

from importlib import metadata as _metadata

__all__ = ["__version__"]

try:
    __version__ = _metadata.version("plotinator-10k")
except _metadata.PackageNotFoundError:  # pragma: no cover - fallback for local runs
    __version__ = "0.1.0"
