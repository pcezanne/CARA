"""Tests for ChessLogCategoryChartWidget — pure helpers and Qt-gated paint tests."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _qt_starts_cleanly() -> bool:
    probe = (
        "import os; os.environ.setdefault('QT_QPA_PLATFORM','offscreen'); "
        "from PyQt6.QtWidgets import QApplication; a = QApplication([]); print('ok')"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            timeout=10,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        )
        return result.returncode == 0 and b"ok" in result.stdout
    except Exception:
        return False


_QT_AVAILABLE = _qt_starts_cleanly()

if _QT_AVAILABLE:
    from PyQt6.QtCore import QPointF
    from PyQt6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication(sys.argv)

from datetime import date as _date

from app.services.chess_log_stats_service import ChessLogCategoryBin, ChessLogPresetSeries
from app.views.widgets.chess_log_category_chart_widget import (
    ChessLogCategoryChartWidget,
    _calendar_axis_ticks,
    _effective_calendar_mode,
    _ordinal_to_chart_x,
)


def _bin(**counts: int) -> ChessLogCategoryBin:
    return ChessLogCategoryBin(
        time_pct=50.0,
        total=sum(counts.values()),
        lab0="2025-01",
        lab1="2025-06",
        counts=dict(counts),
    )


def _make_series(
    cats: list[str] = None,
    n_bins: int = 4,
    x_axis_layout: str = "uniform_bins",
    line_style: str = "straight",
    smoothing_strength: float = 1.0,
) -> ChessLogPresetSeries:
    cats = cats or ["C"]
    bins = [
        ChessLogCategoryBin(
            time_pct=i / max(1, n_bins - 1) * 100,
            total=1,
            lab0="2025-01-01",
            lab1="2025-06-30",
            counts={c: 1 for c in cats},
        )
        for i in range(n_bins)
    ]
    return ChessLogPresetSeries(
        preset="CLAMP",
        categories=cats,
        bins=bins,
        x_axis_layout=x_axis_layout,
        line_style=line_style,
        smoothing_strength=smoothing_strength,
    )


# ---------------------------------------------------------------------------
# Pure Python — no Qt needed
# ---------------------------------------------------------------------------

class TestCalendarAxisHelpers(unittest.TestCase):
    """Module-level helpers ported from Player Stats — pure Python, no Qt."""

    # --- _ordinal_to_chart_x ---

    def test_ordinal_to_chart_x_at_min_gives_left(self):
        omin = _date(2026, 1, 1).toordinal()
        omax = _date(2026, 12, 31).toordinal()
        self.assertAlmostEqual(_ordinal_to_chart_x(omin, omin, omax, 50.0, 950.0), 50.0)

    def test_ordinal_to_chart_x_at_max_gives_right(self):
        omin = _date(2026, 1, 1).toordinal()
        omax = _date(2026, 12, 31).toordinal()
        self.assertAlmostEqual(_ordinal_to_chart_x(omax, omin, omax, 50.0, 950.0), 950.0)

    def test_ordinal_to_chart_x_midpoint(self):
        omin = _date(2026, 1, 1).toordinal()
        omax = _date(2026, 1, 1).toordinal() + 100
        omid = omin + 50
        x = _ordinal_to_chart_x(omid, omin, omax, 0.0, 100.0)
        self.assertAlmostEqual(x, 50.0)

    def test_ordinal_to_chart_x_same_function_for_tick_and_bin(self):
        """A tick and a bin at the same ordinal produce the same x-coordinate."""
        omin = _date(2026, 2, 1).toordinal()
        omax = _date(2026, 12, 31).toordinal()
        o_march_1 = _date(2026, 3, 1).toordinal()
        x_tick = _ordinal_to_chart_x(o_march_1, omin, omax, 0.0, 1200.0)
        x_bin = _ordinal_to_chart_x(o_march_1, omin, omax, 0.0, 1200.0)
        self.assertAlmostEqual(x_tick, x_bin)

    # --- _effective_calendar_mode ---

    def test_mode_day_for_short_span(self):
        omin = _date(2026, 6, 1).toordinal()
        omax = _date(2026, 6, 20).toordinal()  # 19 days
        self.assertEqual(_effective_calendar_mode(omin, omax), "day")

    def test_mode_week_for_medium_span(self):
        omin = _date(2026, 1, 1).toordinal()
        omax = _date(2026, 3, 15).toordinal()  # ~73 days
        self.assertEqual(_effective_calendar_mode(omin, omax), "week")

    def test_mode_month_for_synthetic_file_span(self):
        # Synthetic file: Feb–Dec 2026 ≈ 303 days — within month range (120–960)
        omin = _date(2026, 2, 1).toordinal()
        omax = _date(2026, 12, 31).toordinal()
        self.assertEqual(_effective_calendar_mode(omin, omax), "month")

    def test_mode_year_for_long_span(self):
        omin = _date(2020, 1, 1).toordinal()
        omax = _date(2024, 12, 31).toordinal()  # ~5 years
        self.assertEqual(_effective_calendar_mode(omin, omax), "year")

    # --- _calendar_axis_ticks month mode ---

    def test_month_mode_feb_dec_produces_correct_major_ticks(self):
        # omin=Feb 8: Feb 1 is before omin so no Feb tick; Mar–Dec gives 10 ticks.
        omin = _date(2026, 2, 8).toordinal()   # first game date from synthetic file
        omax = _date(2026, 12, 24).toordinal()  # last game date from synthetic file
        mode = _effective_calendar_mode(omin, omax)
        self.assertEqual(mode, "month")
        ticks = _calendar_axis_ticks(omin, omax, mode)
        majors = [(o, lbl) for o, is_major, lbl in ticks if is_major]
        # Mar 1 through Dec 1 all fall within [omin, omax] → 10 major ticks.
        # Feb 1 < omin so February is skipped (same behaviour as Player Stats).
        self.assertEqual(len(majors), 10, f"Expected 10 major ticks (Mar–Dec), got {len(majors)}: {majors}")

    def test_month_mode_aligned_start_produces_full_range_of_ticks(self):
        # omin=Feb 1: Feb 1 == omin → February tick IS included → 11 ticks.
        omin = _date(2026, 2, 1).toordinal()
        omax = _date(2026, 12, 31).toordinal()
        ticks = _calendar_axis_ticks(omin, omax, "month")
        majors = [(o, lbl) for o, is_major, lbl in ticks if is_major]
        self.assertEqual(len(majors), 11, f"Expected 11 major ticks (Feb–Dec), got {len(majors)}: {majors}")

    def test_month_mode_major_labels_are_month_year_format(self):
        omin = _date(2026, 2, 1).toordinal()
        omax = _date(2026, 4, 30).toordinal()
        ticks = _calendar_axis_ticks(omin, omax, "month")
        major_labels = [lbl for _, is_major, lbl in ticks if is_major and lbl]
        self.assertIn("Feb '26", major_labels)
        self.assertIn("Mar '26", major_labels)
        self.assertIn("Apr '26", major_labels)

    def test_month_mode_tick_ordinals_are_first_of_month(self):
        omin = _date(2026, 3, 15).toordinal()
        omax = _date(2026, 6, 20).toordinal()
        ticks = _calendar_axis_ticks(omin, omax, "month")
        for o, is_major, _ in ticks:
            if is_major:
                d = _date.fromordinal(o)
                self.assertEqual(d.day, 1,
                    f"Major tick at {d} is not the 1st of month")

    def test_empty_months_produce_no_major_ticks(self):
        # Jan 2026 is between Dec 2025 and Feb 2026; if data only spans Feb–Apr,
        # there must be no January tick.
        omin = _date(2026, 2, 1).toordinal()
        omax = _date(2026, 4, 30).toordinal()
        ticks = _calendar_axis_ticks(omin, omax, "month")
        major_labels = [lbl for _, is_major, lbl in ticks if is_major and lbl]
        self.assertNotIn("Jan '26", major_labels)
        self.assertNotIn("May '26", major_labels)

    def test_ticks_are_sorted_by_ordinal(self):
        omin = _date(2026, 2, 1).toordinal()
        omax = _date(2026, 12, 31).toordinal()
        ticks = _calendar_axis_ticks(omin, omax, "month")
        ordinals = [o for o, _, _ in ticks]
        self.assertEqual(ordinals, sorted(ordinals))

    def test_year_mode_produces_year_labels(self):
        omin = _date(2021, 6, 1).toordinal()
        omax = _date(2024, 6, 30).toordinal()
        ticks = _calendar_axis_ticks(omin, omax, "year")
        major_labels = [lbl for _, is_major, lbl in ticks if is_major and lbl]
        self.assertIn("2022", major_labels)
        self.assertIn("2023", major_labels)
        self.assertIn("2024", major_labels)

    def test_day_mode_produces_labeled_ticks(self):
        omin = _date(2026, 6, 1).toordinal()
        omax = _date(2026, 6, 10).toordinal()
        ticks = _calendar_axis_ticks(omin, omax, "day")
        self.assertTrue(len(ticks) >= 2)
        # All day-mode ticks are major
        self.assertTrue(all(is_major for _, is_major, _ in ticks))

    def test_empty_range_returns_no_ticks(self):
        omin = _date(2026, 6, 1).toordinal()
        self.assertEqual(_calendar_axis_ticks(omin, omin, "month"), [])


class TestComputeYMax(unittest.TestCase):

    def test_single_category_three_bins_same_count_returns_that_count(self):
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
        result = ChessLogCategoryChartWidget._compute_y_max(
            ["C"], [_bin(C=2), _bin(C=2), _bin(C=2)]
        )
        self.assertEqual(result, 2)

    def test_mixed_bins_picks_highest_bin(self):
        result = ChessLogCategoryChartWidget._compute_y_max(
            ["C", "L"], [_bin(C=1, L=4), _bin(C=2, L=1)]
        )
        self.assertEqual(result, 4)


# ---------------------------------------------------------------------------
# Qt-gated tests
# ---------------------------------------------------------------------------

@unittest.skipUnless(_QT_AVAILABLE, "Qt not available in this environment")
class TestSmoothPolylinePath(unittest.TestCase):
    """_smooth_polyline_path produces cubic curves vs straight lines."""

    def _pts(self, n: int) -> list:
        return [QPointF(i * 50.0, float(i % 2) * 30.0) for i in range(n)]

    def test_fewer_than_two_points_returns_none(self):
        from app.views.widgets.chess_log_category_chart_widget import _smooth_polyline_path
        self.assertIsNone(_smooth_polyline_path([]))
        self.assertIsNone(_smooth_polyline_path([QPointF(0, 0)]))

    def test_two_points_returns_path(self):
        from app.views.widgets.chess_log_category_chart_widget import _smooth_polyline_path
        from PyQt6.QtGui import QPainterPath
        path = _smooth_polyline_path(self._pts(2))
        self.assertIsInstance(path, QPainterPath)

    def test_three_or_more_points_returns_path(self):
        from app.views.widgets.chess_log_category_chart_widget import _smooth_polyline_path
        from PyQt6.QtGui import QPainterPath
        path = _smooth_polyline_path(self._pts(5))
        self.assertIsInstance(path, QPainterPath)

    def test_near_zero_strength_produces_straight_segments(self):
        from app.views.widgets.chess_log_category_chart_widget import _smooth_polyline_path
        pts = [QPointF(0, 0), QPointF(100, 0), QPointF(200, 0)]
        path = _smooth_polyline_path(pts, strength=0.01)
        # At near-zero strength, path elements should only be LineTo
        # QPainterPath.elementCount() and element types can verify this
        for i in range(path.elementCount()):
            elem = path.elementAt(i)
            self.assertFalse(elem.isCurveTo(), "near-zero strength should produce no cubic curves")

    def test_nonzero_strength_produces_cubic_curves(self):
        from app.views.widgets.chess_log_category_chart_widget import _smooth_polyline_path
        from PyQt6.QtGui import QPainterPath
        pts = [QPointF(0, 0), QPointF(50, 80), QPointF(100, 0), QPointF(150, 80)]
        path = _smooth_polyline_path(pts, strength=1.0)
        has_curve = any(path.elementAt(i).isCurveTo() for i in range(path.elementCount()))
        self.assertTrue(has_curve)


@unittest.skipUnless(_QT_AVAILABLE, "Qt not available in this environment")
class TestBinXLayout(unittest.TestCase):
    """_bin_x returns correct pixel offsets for each x_axis_layout value."""

    def _widget(self) -> ChessLogCategoryChartWidget:
        return ChessLogCategoryChartWidget(config={})

    def test_calendar_linear_positions_bin_at_calendar_center(self):
        from datetime import date as _d
        # Single-game bin: lab0=lab1="2026-06-15". Center ordinal = lab0 ordinal.
        # t_min = t_max = that ordinal → clamped to left edge.
        # Use a series with two distinct bins so t_min != t_max.
        from app.services.chess_log_stats_service import ChessLogCategoryBin as _Bin, ChessLogPresetSeries as _S
        o_a = _d(2026, 1, 1).toordinal()
        o_b = _d(2026, 7, 1).toordinal()
        bins = [
            _Bin(time_pct=0.0, total=1, lab0="2026-01-01", lab1="2026-01-31", counts={"C": 1}),
            _Bin(time_pct=100.0, total=1, lab0="2026-07-01", lab1="2026-07-31", counts={"C": 1}),
        ]
        series = _S(preset="CLAMP", categories=["C"], bins=bins, x_axis_layout="calendar_linear",
                    t_min=o_a, t_max=_d(2026, 7, 31).toordinal())
        w = self._widget()
        w._series = series
        pw = 1000.0
        # Bin 0: center = (Jan 1 + Jan 31) // 2 ≈ Jan 16
        o0_center = (o_a + _d(2026, 1, 31).toordinal()) // 2
        t_min = o_a
        t_max = _d(2026, 7, 31).toordinal()
        expected = _ordinal_to_chart_x(o0_center, t_min, t_max, 0.0, pw)
        actual = w._bin_x(0, 2, 0.0, pw)
        self.assertAlmostEqual(actual, expected, delta=1.0)

    def test_uniform_bins_first_index_is_zero(self):
        w = self._widget()
        w._series = _make_series(x_axis_layout="uniform_bins")
        x = w._bin_x(0, 4, 10.0, 300.0)
        self.assertAlmostEqual(x, 0.0)

    def test_uniform_bins_last_index_is_full_width(self):
        w = self._widget()
        w._series = _make_series(x_axis_layout="uniform_bins")
        x = w._bin_x(3, 4, 90.0, 300.0)
        self.assertAlmostEqual(x, 300.0)

    def test_uniform_bins_evenly_spaced(self):
        w = self._widget()
        w._series = _make_series(x_axis_layout="uniform_bins")
        xs = [w._bin_x(i, 5, i * 25.0, 400.0) for i in range(5)]
        gaps = [xs[i + 1] - xs[i] for i in range(4)]
        for g in gaps:
            self.assertAlmostEqual(g, 100.0)

    def test_gap_compressed_falls_back_to_uniform_bins(self):
        w = self._widget()
        w._series = _make_series(x_axis_layout="gap_compressed")
        # Before full port, gap_compressed behaves like uniform_bins
        x = w._bin_x(0, 4, 10.0, 300.0)
        self.assertAlmostEqual(x, 0.0)

    def test_calendar_linear_not_evenly_spaced_for_gappy_data(self):
        """Regression: Calendar Linear must produce a visible gap for April+July data.

        Uses single-game bins (lab0=lab1) so center-of-bin = game date. The April
        cluster renders in the left ~20% of the chart and the July cluster in the
        right ~20%, leaving a large visible May–June gap between them. Uniform Bins
        would spread them evenly regardless of calendar position.
        """
        from datetime import date as _d
        from app.services.chess_log_stats_service import (
            ChessLogCategoryBin as _Bin,
            ChessLogPresetSeries as _Series,
        )
        # 5 April + 5 July single-game bins. Apr 1–21 span = 20 days, Jul 1–21 span = 20 days.
        # Total ordinal span: Apr 1 → Jul 21 = 111 days.
        april_dates = ["2026-04-01", "2026-04-06", "2026-04-11", "2026-04-16", "2026-04-21"]
        july_dates  = ["2026-07-01", "2026-07-06", "2026-07-11", "2026-07-16", "2026-07-21"]

        bins = [
            _Bin(time_pct=0.0, total=1, lab0=d, lab1=d, counts={"C": 1})
            for d in april_dates + july_dates
        ]
        t_min = _d.fromisoformat("2026-04-01").toordinal()
        t_max = _d.fromisoformat("2026-07-21").toordinal()
        series_cal = _Series(preset="CLAMP", categories=["C"], bins=bins,
                             x_axis_layout="calendar_linear", t_min=t_min, t_max=t_max)
        series_uni = _Series(preset="CLAMP", categories=["C"], bins=bins, x_axis_layout="uniform_bins")

        w = self._widget()
        pw = 900.0
        n = len(bins)

        w._series = series_cal
        cal_xs = [w._bin_x(i, n, bins[i].time_pct, pw) for i in range(n)]

        w._series = series_uni
        uni_xs = [w._bin_x(i, n, bins[i].time_pct, pw) for i in range(n)]

        # Uniform Bins must be evenly spaced regardless of dates
        uni_gaps = [uni_xs[i + 1] - uni_xs[i] for i in range(n - 1)]
        for g in uni_gaps:
            self.assertAlmostEqual(g, pw / (n - 1), places=1, msg="Uniform Bins should be evenly spaced")

        # Calendar Linear: April cluster in first ~20%, July cluster in last ~82–100%.
        # Single-game bins → center = lab0 = lab1, so Apr 1 → ~0%, Apr 21 → ~18%.
        # Jul 1 → ~82%, Jul 21 → ~100%.
        cal_gap_between_clusters = cal_xs[5] - cal_xs[4]   # Jul 1 − Apr 21 in pixels
        cal_gap_within_april = cal_xs[1] - cal_xs[0]       # Apr 6 − Apr 1 in pixels
        self.assertGreater(
            cal_gap_between_clusters, cal_gap_within_april * 8,
            f"Calendar Linear gap between clusters ({cal_gap_between_clusters:.1f}px) "
            f"should be >> within-cluster gap ({cal_gap_within_april:.1f}px)"
        )

        # Calendar Linear positions must differ significantly from Uniform Bins
        max_diff = max(abs(cal_xs[i] - uni_xs[i]) for i in range(n))
        self.assertGreater(max_diff, pw * 0.1, "Calendar Linear and Uniform Bins should produce visibly different positions")

    def test_calendar_linear_positions_straddling_bin_at_center(self):
        """Calendar Linear uses bin center, matching Player Stats' coordinate system.

        A quantile bin spanning Apr 30–Jul 1 has its center near Jun 1. The widget
        correctly renders it at that center (≈day 61 of the Apr–Jul span). Empty
        months remain visible via the calendar gridlines drawn by _draw_calendar_axis,
        NOT by shifting data points to avoid the gap. This is the Player Stats pattern.
        """
        from app.services.chess_log_stats_service import (
            ChessLogCategoryBin as _Bin,
            ChessLogPresetSeries as _Series,
        )
        from datetime import date as _d
        # Three bins: pure April, straddling Apr–Jul, pure July.
        # t_min = Apr 1 ordinal, t_max = Jul 30 ordinal → span = 119 days.
        o_apr1 = _d(2026, 4, 1).toordinal()
        o_jul30 = _d(2026, 7, 30).toordinal()
        bins = [
            _Bin(time_pct=0.0, total=3, lab0="2026-04-01", lab1="2026-04-28", counts={"C": 3}),
            _Bin(time_pct=0.0, total=2, lab0="2026-04-30", lab1="2026-07-01", counts={"C": 2}),
            _Bin(time_pct=0.0, total=3, lab0="2026-07-02", lab1="2026-07-30", counts={"C": 3}),
        ]
        series = _Series(preset="CLAMP", categories=["C"], bins=bins,
                         x_axis_layout="calendar_linear", t_min=o_apr1, t_max=o_jul30)
        w = self._widget()
        w._series = series
        pw = 1200.0  # 10px per day for 120-day span (Apr 1–Jul 30)

        xs = [w._bin_x(i, 3, bins[i].time_pct, pw) for i in range(3)]

        # Straddling bin center: (Apr 30 + Jul 1) / 2 ≈ Jun 1 (day ~61)
        o_straddle_center = (_d(2026, 4, 30).toordinal() + _d(2026, 7, 1).toordinal()) // 2
        expected_straddle_x = _ordinal_to_chart_x(o_straddle_center, o_apr1, o_jul30, 0.0, pw)
        self.assertAlmostEqual(xs[1], expected_straddle_x, delta=2.0,
            msg="Straddling bin must render at calendar center, not at lab0")

        # Verify center IS near June (day 61 ≈ 610px), not at April (day 29 ≈ 290px)
        self.assertGreater(xs[1], 500.0,
            "Straddling bin center should be in June territory (>500px), not April")
        self.assertLess(xs[1], 750.0,
            "Straddling bin center should be in June territory (<750px), not July")


@unittest.skipUnless(_QT_AVAILABLE, "Qt not available in this environment")
class TestLineStyleBranching(unittest.TestCase):
    """Widget reads series.line_style to choose between smooth/straight rendering."""

    def test_smooth_series_does_not_raise(self):
        w = ChessLogCategoryChartWidget(config={})
        w.set_series(_make_series(line_style="smooth", n_bins=5))
        # Trigger paintEvent via render — should not raise
        from PyQt6.QtGui import QImage, QPainter
        img = QImage(400, 220, QImage.Format.Format_ARGB32)
        p = QPainter(img)
        w.render(p)
        p.end()

    def test_straight_series_does_not_raise(self):
        w = ChessLogCategoryChartWidget(config={})
        w.set_series(_make_series(line_style="straight", n_bins=5))
        from PyQt6.QtGui import QImage, QPainter
        img = QImage(400, 220, QImage.Format.Format_ARGB32)
        p = QPainter(img)
        w.render(p)
        p.end()


if __name__ == "__main__":
    unittest.main()
