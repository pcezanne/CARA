"""Tests for chess_log_charts_user — settings normalization and config override helpers."""

from __future__ import annotations

import unittest

from app.services.chess_log_charts_user import (
    CHOICES_BINNING_MODE,
    CHOICES_LINE_STYLE,
    CHOICES_MAX_GAP_SEGMENT_DAYS,
    CHOICES_SMOOTHING_STRENGTH,
    CHOICES_TARGET_BINS,
    CHOICES_X_AXIS_LAYOUT,
    DEFAULT_CHESS_LOG_CHARTS,
    chart_cfg_with_chess_log_charts_overrides,
    normalize_chess_log_charts_settings,
)


class TestNormalizeChessLogChartsSettings(unittest.TestCase):

    # --- base cases ---

    def test_none_returns_defaults(self):
        result = normalize_chess_log_charts_settings(None)
        self.assertEqual(result, DEFAULT_CHESS_LOG_CHARTS)

    def test_empty_dict_returns_defaults(self):
        result = normalize_chess_log_charts_settings({})
        self.assertEqual(result, DEFAULT_CHESS_LOG_CHARTS)

    def test_extra_keys_not_included(self):
        result = normalize_chess_log_charts_settings({"bogus_key": 99})
        self.assertNotIn("bogus_key", result)

    # --- target_bins ---

    def test_all_valid_target_bins_accepted(self):
        for n in CHOICES_TARGET_BINS:
            result = normalize_chess_log_charts_settings({"target_bins": n})
            self.assertEqual(result["target_bins"], n)

    def test_invalid_target_bins_falls_back_to_default(self):
        result = normalize_chess_log_charts_settings({"target_bins": 13})
        self.assertEqual(result["target_bins"], DEFAULT_CHESS_LOG_CHARTS["target_bins"])

    def test_float_target_bins_invalid(self):
        result = normalize_chess_log_charts_settings({"target_bins": 16.0})
        self.assertEqual(result["target_bins"], DEFAULT_CHESS_LOG_CHARTS["target_bins"])

    # --- binning_mode ---

    def test_all_valid_binning_modes_accepted(self):
        for mode in CHOICES_BINNING_MODE:
            result = normalize_chess_log_charts_settings({"binning_mode": mode})
            self.assertEqual(result["binning_mode"], mode)

    def test_invalid_binning_mode_falls_back_to_default(self):
        result = normalize_chess_log_charts_settings({"binning_mode": "median"})
        self.assertEqual(result["binning_mode"], DEFAULT_CHESS_LOG_CHARTS["binning_mode"])

    # --- x_axis_layout ---

    def test_all_valid_x_axis_layouts_accepted(self):
        for layout in CHOICES_X_AXIS_LAYOUT:
            result = normalize_chess_log_charts_settings({"x_axis_layout": layout})
            self.assertEqual(result["x_axis_layout"], layout)

    def test_invalid_x_axis_layout_falls_back_to_default(self):
        result = normalize_chess_log_charts_settings({"x_axis_layout": "diagonal"})
        self.assertEqual(result["x_axis_layout"], DEFAULT_CHESS_LOG_CHARTS["x_axis_layout"])

    # --- max_gap_segment_days ---

    def test_all_valid_max_gap_days_accepted(self):
        for d in CHOICES_MAX_GAP_SEGMENT_DAYS:
            result = normalize_chess_log_charts_settings({"max_gap_segment_days": d})
            self.assertEqual(result["max_gap_segment_days"], d)

    def test_invalid_max_gap_days_falls_back_to_default(self):
        result = normalize_chess_log_charts_settings({"max_gap_segment_days": 30})
        self.assertEqual(result["max_gap_segment_days"], DEFAULT_CHESS_LOG_CHARTS["max_gap_segment_days"])

    # --- line_style ---

    def test_all_valid_line_styles_accepted(self):
        for style in CHOICES_LINE_STYLE:
            result = normalize_chess_log_charts_settings({"line_style": style})
            self.assertEqual(result["line_style"], style)

    def test_invalid_line_style_falls_back_to_default(self):
        result = normalize_chess_log_charts_settings({"line_style": "dotted"})
        self.assertEqual(result["line_style"], DEFAULT_CHESS_LOG_CHARTS["line_style"])

    # --- smoothing_strength ---

    def test_all_valid_smoothing_strengths_accepted(self):
        for s in CHOICES_SMOOTHING_STRENGTH:
            result = normalize_chess_log_charts_settings({"smoothing_strength": s})
            self.assertAlmostEqual(result["smoothing_strength"], s)

    def test_invalid_smoothing_strength_falls_back_to_default(self):
        result = normalize_chess_log_charts_settings({"smoothing_strength": 3.0})
        self.assertAlmostEqual(result["smoothing_strength"], DEFAULT_CHESS_LOG_CHARTS["smoothing_strength"])

    # --- full valid dict ---

    def test_full_valid_settings_preserved(self):
        raw = {
            "target_bins": 24,
            "binning_mode": "equal_width",
            "x_axis_layout": "gap_compressed",
            "max_gap_segment_days": 50,
            "line_style": "straight",
            "smoothing_strength": 1.5,
        }
        result = normalize_chess_log_charts_settings(raw)
        self.assertEqual(result["target_bins"], 24)
        self.assertEqual(result["binning_mode"], "equal_width")
        self.assertEqual(result["x_axis_layout"], "gap_compressed")
        self.assertEqual(result["max_gap_segment_days"], 50)
        self.assertEqual(result["line_style"], "straight")
        self.assertAlmostEqual(result["smoothing_strength"], 1.5)

    # --- migration from old x_axis_mode ---

    def test_migration_game_count_becomes_uniform_bins(self):
        result = normalize_chess_log_charts_settings({"x_axis_mode": "game_count"})
        self.assertEqual(result["x_axis_layout"], "uniform_bins")
        self.assertNotIn("x_axis_mode", result)

    def test_migration_time_becomes_calendar_linear(self):
        result = normalize_chess_log_charts_settings({"x_axis_mode": "time"})
        self.assertEqual(result["x_axis_layout"], "calendar_linear")
        self.assertNotIn("x_axis_mode", result)

    def test_migration_explicit_x_axis_layout_wins_over_x_axis_mode(self):
        # If both keys present, x_axis_layout takes precedence (migration is skipped).
        result = normalize_chess_log_charts_settings(
            {"x_axis_mode": "game_count", "x_axis_layout": "gap_compressed"}
        )
        self.assertEqual(result["x_axis_layout"], "gap_compressed")

    def test_old_x_axis_mode_key_absent_from_output(self):
        result = normalize_chess_log_charts_settings({"x_axis_mode": "time"})
        self.assertNotIn("x_axis_mode", result)


class TestChartCfgWithChessLogChartsOverrides(unittest.TestCase):
    """chart_cfg_with_chess_log_charts_overrides builds a flat chart_cfg dict with ts_block keys
    from app_config and target_progression_bins / ordinal_fallback_mode overridden by callers."""

    _TIME_SERIES_BLOCK = {
        "target_progression_bins": 16,
        "min_games_per_ordinal_bin": 3,
        "max_ordinal_bins": 120,
        "ordinal_fallback_mode": "quantile",
    }
    _APP_CFG = {
        "ui": {
            "panels": {
                "detail": {
                    "player_stats": {
                        "time_series": _TIME_SERIES_BLOCK
                    }
                }
            }
        }
    }

    def test_explicit_target_bins_overrides_config(self):
        cfg = chart_cfg_with_chess_log_charts_overrides(self._APP_CFG, 24)
        self.assertEqual(cfg["target_progression_bins"], 24)

    def test_binning_mode_overrides_ordinal_fallback_mode(self):
        cfg = chart_cfg_with_chess_log_charts_overrides(self._APP_CFG, 16, binning_mode="equal_width")
        self.assertEqual(cfg["ordinal_fallback_mode"], "equal_width")

    def test_binning_mode_defaults_to_quantile(self):
        cfg = chart_cfg_with_chess_log_charts_overrides(self._APP_CFG, 16)
        self.assertEqual(cfg["ordinal_fallback_mode"], "quantile")

    def test_base_ts_keys_preserved(self):
        cfg = chart_cfg_with_chess_log_charts_overrides(self._APP_CFG, 16)
        self.assertIn("min_games_per_ordinal_bin", cfg)

    def test_none_app_config_returns_dict_with_override(self):
        cfg = chart_cfg_with_chess_log_charts_overrides(None, 8)
        self.assertEqual(cfg["target_progression_bins"], 8)

    def test_does_not_mutate_app_config(self):
        import copy
        app = copy.deepcopy(self._APP_CFG)
        chart_cfg_with_chess_log_charts_overrides(app, 8)
        self.assertEqual(
            app["ui"]["panels"]["detail"]["player_stats"]["time_series"]["target_progression_bins"],
            16,
        )


if __name__ == "__main__":
    unittest.main()
