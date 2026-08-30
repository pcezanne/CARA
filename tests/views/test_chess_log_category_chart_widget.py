"""Tests for ChessLogCategoryChartWidget — pure helpers only (no Qt paint)."""

from __future__ import annotations

import unittest

from app.services.chess_log_stats_service import ChessLogCategoryBin
from app.views.widgets.chess_log_category_chart_widget import ChessLogCategoryChartWidget


def _bin(**counts: int) -> ChessLogCategoryBin:
    return ChessLogCategoryBin(
        time_pct=50.0,
        total=sum(counts.values()),
        lab0="2025-01",
        lab1="2025-06",
        counts=dict(counts),
    )


class TestComputeYMax(unittest.TestCase):

    def test_single_category_three_bins_same_count_returns_that_count(self):
        # Regression: sum across bins was 9, correct answer is 3.
        result = ChessLogCategoryChartWidget._compute_y_max(
            ["C"], [_bin(C=3), _bin(C=3), _bin(C=3)]
        )
        self.assertEqual(result, 3)

    def test_empty_returns_floor_one(self):
        self.assertEqual(ChessLogCategoryChartWidget._compute_y_max([], []), 1)

    def test_all_zero_bins_returns_floor_one(self):
        result = ChessLogCategoryChartWidget._compute_y_max(["C"], [_bin(C=0), _bin(C=0)])
        self.assertEqual(result, 1)

    def test_two_categories_returns_max_single_bin_value(self):
        result = ChessLogCategoryChartWidget._compute_y_max(
            ["C", "L"], [_bin(C=5, L=0), _bin(C=0, L=0)]
        )
        self.assertEqual(result, 5)

    def test_max_is_per_bin_not_sum(self):
        # C has 2 in three bins → sum=6, but max single-bin is 2.
        result = ChessLogCategoryChartWidget._compute_y_max(
            ["C"], [_bin(C=2), _bin(C=2), _bin(C=2)]
        )
        self.assertEqual(result, 2)

    def test_mixed_bins_picks_highest_bin(self):
        result = ChessLogCategoryChartWidget._compute_y_max(
            ["C", "L"], [_bin(C=1, L=4), _bin(C=2, L=1)]
        )
        self.assertEqual(result, 4)


if __name__ == "__main__":
    unittest.main()
