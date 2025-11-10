from __future__ import annotations

import pytest

import plot_manager


@pytest.mark.parametrize(
    "argv,expected_path",
    [
        (["plot_manager.py", "custom.json"], "custom.json"),
        (["plot_manager.py"], "config.json"),
    ],
)
def test_main_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    expected_path: str,
) -> None:
    """plot_manager.main should delegate to run_batch and return success."""

    call_args: dict[str, str] = {}

    def fake_run_batch(path: str) -> None:
        call_args["path"] = path

    monkeypatch.setattr(plot_manager, "run_batch", fake_run_batch)

    exit_code = plot_manager.main(argv)

    assert exit_code == 0
    assert call_args["path"] == expected_path
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_main_missing_config(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Missing configuration files should yield an error status and message."""

    def fake_run_batch(path: str) -> None:
        raise FileNotFoundError(f"{path} does not exist")

    monkeypatch.setattr(plot_manager, "run_batch", fake_run_batch)

    exit_code = plot_manager.main(["plot_manager.py"])  # Default path resolved internally

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "[X]" in captured.out
    assert "config.json" in captured.out


def test_main_handles_unexpected_exceptions(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Unexpected exceptions should be surfaced with a non-zero exit code."""

    def fake_run_batch(_: str) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(plot_manager, "run_batch", fake_run_batch)

    exit_code = plot_manager.main(["plot_manager.py", "custom.json"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out.strip() == "[X] boom"
