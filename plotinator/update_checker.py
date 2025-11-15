"""Background GitHub release checker for the Plotinator desktop app."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import threading
from pathlib import Path
from typing import Any, Callable, Mapping, Optional
import urllib.request
import weakref

from packaging.version import InvalidVersion, Version


__all__ = [
    "ReleaseInfo",
    "UpdatePreferences",
    "UpdateResult",
    "UpdateChecker",
]


_DEFAULT_INTERVAL_HOURS = 24
_MIN_INTERVAL_HOURS = 1
_MAX_INTERVAL_HOURS = 24 * 7


@dataclass(frozen=True)
class ReleaseInfo:
    """Data model describing a GitHub release."""

    version_label: str
    url: str
    notes: str
    published_at: Optional[str] = None


@dataclass
class UpdatePreferences:
    """Persisted user preferences for update checking."""

    enabled: bool = True
    interval_hours: int = _DEFAULT_INTERVAL_HOURS
    last_checked: Optional[datetime] = None
    last_notified_label: Optional[str] = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "UpdatePreferences":
        enabled = bool(data.get("enabled", True))
        interval_raw = data.get("interval_hours", _DEFAULT_INTERVAL_HOURS)
        try:
            interval = int(interval_raw)
        except (TypeError, ValueError):
            interval = _DEFAULT_INTERVAL_HOURS
        interval = max(_MIN_INTERVAL_HOURS, min(_MAX_INTERVAL_HOURS, interval))

        last_checked_raw = data.get("last_checked")
        last_checked: Optional[datetime] = None
        if isinstance(last_checked_raw, str):
            try:
                last_checked = datetime.fromisoformat(last_checked_raw)
            except ValueError:
                last_checked = None

        last_notified = data.get("last_notified_label")
        if not isinstance(last_notified, str):
            last_notified = None

        return cls(
            enabled=enabled,
            interval_hours=interval,
            last_checked=last_checked,
            last_notified_label=last_notified,
        )

    def to_mapping(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "enabled": self.enabled,
            "interval_hours": max(_MIN_INTERVAL_HOURS, min(_MAX_INTERVAL_HOURS, int(self.interval_hours))),
        }
        if self.last_checked is not None:
            payload["last_checked"] = self.last_checked.isoformat()
        if self.last_notified_label:
            payload["last_notified_label"] = self.last_notified_label
        return payload

    def next_due(self, *, now: datetime) -> datetime:
        if self.last_checked is None:
            return now
        return self.last_checked + timedelta(hours=self.interval_hours)

    def should_check(self, *, now: datetime) -> bool:
        return self.last_checked is None or now >= self.next_due(now=now)


@dataclass(frozen=True)
class UpdateResult:
    """Represents the outcome of a release check."""

    release: Optional[ReleaseInfo]
    error: Optional[str]
    checked_at: datetime


class UpdateChecker:
    """Helper that periodically checks GitHub releases in the background."""

    def __init__(
        self,
        *,
        owner: str,
        repo: str,
        current_version: str,
        settings_path: Optional[Path] = None,
        fetcher: Optional[Callable[[str], Any]] = None,
    ) -> None:
        self.owner = owner
        self.repo = repo
        self._current_label = current_version
        self._current_version = self._parse_version(current_version)
        self._settings_path = settings_path or (Path.home() / ".plotinator" / "gui_settings.json")
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.preferences = self._load_preferences()
        self._fetcher = fetcher or self._fetch_latest
        self._lock = threading.Lock()
        self._widget_ref: Optional[weakref.ReferenceType[Any]] = None
        self._result_handler: Optional[Callable[[UpdateResult], None]] = None
        self._after_id: Optional[str] = None
        self._last_result: Optional[UpdateResult] = None

    # ------------------------------------------------------------------
    def _load_preferences(self) -> UpdatePreferences:
        try:
            text = self._settings_path.read_text(encoding="utf-8")
        except OSError:
            return UpdatePreferences()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return UpdatePreferences()
        if not isinstance(data, dict):
            return UpdatePreferences()
        return UpdatePreferences.from_mapping(data)

    def _save_preferences(self) -> None:
        try:
            self._settings_path.write_text(json.dumps(self.preferences.to_mapping(), indent=2), encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------------------------
    def start(self, widget: Any, handler: Callable[[UpdateResult], None]) -> None:
        """Start scheduling background update checks."""

        self._widget_ref = weakref.ref(widget)
        self._result_handler = handler
        self._cancel_scheduled()
        if self.preferences.enabled:
            self._schedule_next(initial=True)

    def check_now(self, widget: Any, handler: Optional[Callable[[UpdateResult], None]] = None) -> None:
        """Trigger an immediate release check."""

        self._widget_ref = weakref.ref(widget)
        if handler is not None:
            self._result_handler = handler
        self._run_async_check(force=True)

    def update_preferences(self, *, enabled: bool, interval_hours: int) -> None:
        interval = max(_MIN_INTERVAL_HOURS, min(_MAX_INTERVAL_HOURS, int(interval_hours)))
        with self._lock:
            self.preferences.enabled = bool(enabled)
            self.preferences.interval_hours = interval
            self._save_preferences()
        self._reschedule()

    @property
    def last_result(self) -> Optional[UpdateResult]:
        return self._last_result

    # ------------------------------------------------------------------
    def _widget(self) -> Optional[Any]:
        return self._widget_ref() if self._widget_ref else None

    def _reschedule(self) -> None:
        self._cancel_scheduled()
        if self.preferences.enabled:
            self._schedule_next(initial=True)

    def _cancel_scheduled(self) -> None:
        widget = self._widget()
        if widget is not None and self._after_id is not None:
            try:
                widget.after_cancel(self._after_id)
            except Exception:  # pragma: no cover - tk raises TclError when shutting down
                pass
        self._after_id = None

    def _schedule_next(self, *, initial: bool) -> None:
        widget = self._widget()
        if widget is None:
            return
        now = datetime.now(timezone.utc)
        if initial:
            due = self.preferences.next_due(now=now)
            delay_seconds = 5 if due <= now else max(60, (due - now).total_seconds())
        else:
            delay_seconds = max(60, self.preferences.interval_hours * 3600)
        self._after_id = widget.after(int(delay_seconds * 1000), self._execute_scheduled)

    def _execute_scheduled(self) -> None:
        if not self.preferences.enabled:
            return
        now = datetime.now(timezone.utc)
        if not self.preferences.should_check(now=now):
            self._schedule_next(initial=True)
            return
        self._run_async_check(force=False)

    def _run_async_check(self, *, force: bool) -> None:
        widget = self._widget()
        handler = self._result_handler
        if widget is None or handler is None:
            return

        if not force and not self.preferences.enabled:
            return

        def _worker() -> None:
            result = self._perform_check()
            target = self._widget()
            callback = self._result_handler
            if target is None or callback is None:
                return
            try:
                target.after(0, lambda: callback(result))
            except Exception:  # pragma: no cover - tk raises during shutdown
                pass

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    # ------------------------------------------------------------------
    def _perform_check(self) -> UpdateResult:
        now = datetime.now(timezone.utc)
        release: Optional[ReleaseInfo] = None
        error: Optional[str] = None
        try:
            release = self.check_for_update()
        except Exception as exc:  # noqa: BLE001 - errors surfaced to UI
            error = str(exc)

        with self._lock:
            self.preferences.last_checked = now
            if release is not None:
                self.preferences.last_notified_label = release.version_label
            self._save_preferences()
            result = UpdateResult(release=release, error=error, checked_at=now)
            self._last_result = result

        if self.preferences.enabled:
            self._schedule_next(initial=False)
        return result

    # ------------------------------------------------------------------
    def check_for_update(self) -> Optional[ReleaseInfo]:
        data = self._fetch_release_payload()
        if not data:
            return None

        version_label = self._extract_version_label(data)
        normalized = self._parse_version(version_label)
        if normalized is not None and self._current_version is not None:
            if normalized <= self._current_version:
                return None

        last_notified = self.preferences.last_notified_label
        if last_notified:
            notified_version = self._parse_version(last_notified)
            if normalized is not None and notified_version is not None and normalized <= notified_version:
                return None
            if normalized is None and version_label == last_notified:
                return None

        url = str(data.get("html_url") or data.get("url") or "").strip()
        if not url:
            return None

        notes = str(data.get("body") or "").strip()
        published_at = data.get("published_at")
        if not isinstance(published_at, str):
            published_at = None

        return ReleaseInfo(version_label=version_label, url=url, notes=notes, published_at=published_at)

    def _fetch_release_payload(self) -> Optional[dict[str, Any]]:
        url = f"https://api.github.com/repos/{self.owner}/{self.repo}/releases/latest"
        response = self._fetcher(url)
        if response is None:
            return None
        if isinstance(response, bytes):
            try:
                decoded = response.decode("utf-8")
            except UnicodeDecodeError as exc:  # pragma: no cover - unexpected payload
                raise RuntimeError("Unable to decode release payload") from exc
            response = json.loads(decoded)
        if isinstance(response, str):
            response = json.loads(response)
        if not isinstance(response, dict):
            return None
        return response

    def _fetch_latest(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "plotinator-gui-update-checker",
            },
        )
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - external request intentional
            payload = response.read()
        return json.loads(payload.decode("utf-8"))

    def _extract_version_label(self, payload: dict[str, Any]) -> str:
        tag = payload.get("tag_name")
        name = payload.get("name")
        label_candidates = [
            str(tag).strip() if isinstance(tag, str) else "",
            str(name).strip() if isinstance(name, str) else "",
        ]
        for candidate in label_candidates:
            if candidate:
                return candidate
        return "latest"

    def _parse_version(self, value: Optional[str]) -> Optional[Version]:
        if not value:
            return None
        stripped = value.strip()
        if stripped.lower().startswith("v"):
            stripped = stripped[1:]
        try:
            return Version(stripped)
        except InvalidVersion:
            return None
