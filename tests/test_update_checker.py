from __future__ import annotations

from pathlib import Path

from plotinator.update_checker import UpdateChecker


def _make_checker(tmp_path: Path, *, current_version: str, payload: dict[str, object] | None):
    def _fetcher(_: str) -> dict[str, object] | None:
        return payload

    return UpdateChecker(
        owner="plotinator-labs",
        repo="Plotinator_10k",
        current_version=current_version,
        settings_path=tmp_path / "settings.json",
        fetcher=_fetcher,
    )


def test_check_for_update_detects_new_release(tmp_path: Path) -> None:
    payload = {
        "tag_name": "v1.2.0",
        "html_url": "https://example.com/download",
        "body": "Bug fixes",
    }
    checker = _make_checker(tmp_path, current_version="1.1.0", payload=payload)
    release = checker.check_for_update()
    assert release is not None
    assert release.version_label == "v1.2.0"
    assert "download" in release.url


def test_check_for_update_ignores_older_release(tmp_path: Path) -> None:
    payload = {
        "tag_name": "v1.0.0",
        "html_url": "https://example.com/old",
        "body": "",
    }
    checker = _make_checker(tmp_path, current_version="1.1.0", payload=payload)
    assert checker.check_for_update() is None


def test_check_for_update_skips_notified_release(tmp_path: Path) -> None:
    payload = {
        "tag_name": "v1.3.0",
        "html_url": "https://example.com/new",
        "body": "Highlights",
    }
    checker = _make_checker(tmp_path, current_version="1.2.0", payload=payload)
    checker.preferences.last_notified_label = "v1.3.0"
    assert checker.check_for_update() is None


def test_update_preferences_persist(tmp_path: Path) -> None:
    checker = _make_checker(tmp_path, current_version="1.0.0", payload=None)
    checker.update_preferences(enabled=False, interval_hours=2)
    assert checker.preferences.enabled is False
    assert checker.preferences.interval_hours == 2
    data = (tmp_path / "settings.json").read_text(encoding="utf-8")
    assert "\"enabled\": false" in data
