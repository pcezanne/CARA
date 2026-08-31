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

from app.services.chess_log_stats_service import ChessLogCategoryBin, ChessLogPresetSeries
from app.views.widgets.chess_log_category_chart_widget import ChessLogCategoryChartWidget


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

    def test_calendar_linear_uses_time_pct(self):
        w = self._widget()
        w._series = _make_series(x_axis_layout="calendar_linear")
        # time_pct=50 → x = 0.5 * pw
        x = w._bin_x(0, 2, 50.0, 400.0)
        self.assertAlmostEqual(x, 200.0)

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
