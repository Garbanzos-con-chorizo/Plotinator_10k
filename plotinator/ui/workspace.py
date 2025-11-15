from __future__ import annotations

import json

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional


__all__ = ["WorkspaceState"]


_DEFAULT_AUTOSAVE_MINUTES = 5
_MAX_RECENT_PROJECTS = 8


@dataclass
class WorkspaceState:
    """Persisted UI state for project-oriented workflows."""

    autosave_minutes: int = _DEFAULT_AUTOSAVE_MINUTES
    recent_projects: List[Path] = field(default_factory=list)
    last_opened: Optional[Path] = None
    _storage_path: Path = field(
        default_factory=lambda: Path.home() / ".plotinator" / "workspace_state.json",
        repr=False,
    )

    def __post_init__(self) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.autosave_minutes = max(0, int(self.autosave_minutes))
        self._normalise_recent()

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, path: Path | None = None) -> "WorkspaceState":
        storage_path = path or (Path.home() / ".plotinator" / "workspace_state.json")
        try:
            payload = json.loads(storage_path.read_text(encoding="utf-8"))
        except OSError:
            return cls(_storage_path=storage_path)
        except json.JSONDecodeError:
            return cls(_storage_path=storage_path)

        if not isinstance(payload, dict):
            return cls(_storage_path=storage_path)

        autosave_raw = payload.get("autosave_minutes", _DEFAULT_AUTOSAVE_MINUTES)
        try:
            autosave_minutes = int(autosave_raw)
        except (TypeError, ValueError):
            autosave_minutes = _DEFAULT_AUTOSAVE_MINUTES

        recent_raw = payload.get("recent_projects", [])
        recent: list[Path] = []
        if isinstance(recent_raw, Iterable):
            for item in recent_raw:
                if not isinstance(item, str):
                    continue
                candidate = Path(item)
                if candidate.exists():
                    recent.append(candidate)

        last_raw = payload.get("last_opened")
        last_opened = Path(last_raw) if isinstance(last_raw, str) else None
        if last_opened is not None and not last_opened.exists():
            last_opened = None

        state = cls(
            autosave_minutes=max(0, autosave_minutes),
            recent_projects=recent[:_MAX_RECENT_PROJECTS],
            last_opened=last_opened,
            _storage_path=storage_path,
        )
        state._normalise_recent()
        return state

    # ------------------------------------------------------------------
    def save(self) -> None:
        data = {
            "autosave_minutes": max(0, int(self.autosave_minutes)),
            "recent_projects": [str(path) for path in self.recent_projects],
            "last_opened": str(self.last_opened) if self.last_opened else None,
        }
        try:
            self._storage_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------------------------
    def record_project(self, project_root: Path) -> None:
        resolved = self._resolve(project_root)
        existing = [p for p in self.recent_projects if p != resolved]
        self.recent_projects = [resolved, *existing][: _MAX_RECENT_PROJECTS]
        self.last_opened = resolved

    def remove_project(self, project_root: Path) -> None:
        resolved = self._resolve(project_root)
        self.recent_projects = [p for p in self.recent_projects if p != resolved]
        if self.last_opened == resolved:
            self.last_opened = None

    def prune_missing(self) -> None:
        self.recent_projects = [p for p in self.recent_projects if (p / "project.json").exists()]
        if self.last_opened and not (self.last_opened / "project.json").exists():
            self.last_opened = None

    # ------------------------------------------------------------------
    def _resolve(self, value: Path) -> Path:
        try:
            return value.resolve()
        except OSError:
            return value

    def _normalise_recent(self) -> None:
        seen: set[Path] = set()
        unique: list[Path] = []
        for entry in self.recent_projects:
            resolved = self._resolve(entry)
            if resolved in seen:
                continue
            seen.add(resolved)
            unique.append(resolved)
        self.recent_projects = unique[: _MAX_RECENT_PROJECTS]
        if self.last_opened is not None:
            self.last_opened = self._resolve(self.last_opened)

