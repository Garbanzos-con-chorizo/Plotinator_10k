"""Guardrails for the Windows packaging documentation."""
from __future__ import annotations

from pathlib import Path
import re

import pytest


@pytest.mark.parametrize(
    "path",
    [
        Path("docs/INSTALLER.md"),
        Path("packaging/windows/README.md"),
    ],
)
def test_wix_cli_instructions_are_v6(path: Path) -> None:
    """Ensure the documentation references the WiX v6 CLI rather than legacy tools."""

    text = path.read_text(encoding="utf-8")

    required = ("wix harvest", "wix build")
    for command in required:
        assert command in text, f"{path} should reference `{command}`"

    deprecated_patterns = [
        r"\bheat(?:\.exe)?\b",
        r"\bcandle(?:\.exe)?\b",
        r"\blight(?:\.exe)?\b",
    ]
    for pattern in deprecated_patterns:
        assert not re.search(pattern, text), (
            f"{path} still references legacy WiX command `{pattern}`"
        )
