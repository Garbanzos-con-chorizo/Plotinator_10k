"""Guardrails for the Windows packaging documentation."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PACKAGING_SCRIPT = Path("packaging/windows/build-installer.bat")


def _determine_supported_wix_version() -> str:
    """Return the WiX major.minor version encoded in the batch script."""

    if not PACKAGING_SCRIPT.exists():  # pragma: no cover - repository invariant
        raise AssertionError(
            "packaging/windows/build-installer.bat is required for MSI builds"
        )

    script_text = PACKAGING_SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"WiX Toolset v(?P<version>\d+\.\d+)", script_text)
    if not match:  # pragma: no cover - defensive guard for future edits
        raise AssertionError(
            "packaging/windows/build-installer.bat must pin a WiX Toolset version"
        )
    return match.group("version")


SUPPORTED_WIX_VERSION = _determine_supported_wix_version()

DOC_PATHS = [
    Path("docs/INSTALLER.md"),
    Path("packaging/windows/README.md"),
]


@pytest.mark.parametrize("path", DOC_PATHS)
def test_wix_version_and_commands(path: Path) -> None:
    """Ensure the docs reference the WiX toolchain pinned in the batch script."""

    text = path.read_text(encoding="utf-8")

    version_tokens = (
        f"WiX Toolset {SUPPORTED_WIX_VERSION}",
        f"WiX Toolset v{SUPPORTED_WIX_VERSION}",
    )
    assert any(token in text for token in version_tokens), (
        "Update the Windows packaging docs to mention the WiX Toolset version "
        f"pinned in {PACKAGING_SCRIPT} ({SUPPORTED_WIX_VERSION})."
    )
    assert "build-installer.bat" in text

    required_commands = ("candle.exe", "light.exe")
    for command in required_commands:
        assert command in text, f"{path} should mention `{command}`"

    deprecated_patterns = [
        r"\bwix\s+harvest\b",
        r"\bwix\s+build\b",
    ]
    for pattern in deprecated_patterns:
        assert not re.search(pattern, text), (
            f"{path} should not reference deprecated WiX command `{pattern}`"
        )
