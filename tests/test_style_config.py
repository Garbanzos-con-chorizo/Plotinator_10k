"""Tests for the StyleConfig helpers."""

from plotinator.config.style import StyleConfig


def test_style_config_window_normalization() -> None:
    cfg = StyleConfig.from_dict(
        {
            "x_window": [0, 10],
            "y_window": {"min": -1, "max": 1},
        }
    )

    assert cfg.x_window == (0.0, 10.0)
    assert cfg.y_window == (-1.0, 1.0)
    assert cfg.axis_range_clause("x") == "set xrange [0:10]"
    assert cfg.axis_range_clause("y") == "set yrange [-1:1]"
    assert cfg.to_dict()["x_window"] == [0.0, 10.0]
    assert cfg.to_dict()["y_window"] == [-1.0, 1.0]


def test_style_config_tick_clauses() -> None:
    cfg = StyleConfig.from_dict(
        {
            "x_ticks": 2,
            "y_ticks": [["Low", -1], ["High", 1]],
        }
    )

    assert cfg.axis_ticks_clause("x") == "set xtics 2.0"
    assert cfg.axis_ticks_clause("y") == 'set ytics ("Low" -1.0, "High" 1.0)'
    assert cfg.to_dict()["x_ticks"] == 2.0
    assert cfg.to_dict()["y_ticks"] == [["Low", -1.0], ["High", 1.0]]
