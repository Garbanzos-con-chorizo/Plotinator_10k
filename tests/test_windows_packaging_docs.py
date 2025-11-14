"""Guardrails for the Windows packaging documentation."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DOC_PATHS = [
    Path("docs/INSTALLER.md"),
    Path("packaging/windows/README.md"),
]


@pytest.mark.parametrize("path", DOC_PATHS)
def test_wix_version_and_commands(path: Path) -> None:
    """Ensure the docs reference the supported WiX 3.14 toolchain."""

    text = path.read_text(encoding="utf-8")

    assert "WiX Toolset 3.14" in text or "WiX Toolset v3.14" in text
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
