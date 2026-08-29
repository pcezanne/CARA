"""Tests for DetailChessLogChartsView.

Requires a working Qt platform (CI: QT_QPA_PLATFORM=offscreen).
Uses stub controller so no live data is needed.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

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
    from PyQt6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication(sys.argv)

    from app.views.detail_chess_log_charts_view import DetailChessLogChartsView, _SOURCE_LABELS
    from app.services.chess_log_stats_service import (
        ChessLogCategoryBin,
        ChessLogPresetSeries,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stub_controller(ai_configured: bool = False) -> MagicMock:
    ctrl = MagicMock()
    ctrl.is_ai_configured.return_value = ai_configured
    # Simulate signal attributes so connect() calls succeed
    for sig in (
        "charts_updated", "charts_unavailable", "players_ready",
        "narrative_ready", "narrative_failed", "ai_configured_changed",
    ):
        mock_signal = MagicMock()
        mock_signal.connect = MagicMock()
        mock_signal.disconnect = MagicMock()
        setattr(ctrl, sig, mock_signal)
    return ctrl


def _make_series(preset: str, cats: list[str], n_bins: int = 1) -> ChessLogPresetSeries:
    bins = [
        ChessLogCategoryBin(
            time_pct=50.0,
            total=len(cats),
            lab0="2025-01",
            lab1="2025-06",
            counts={c: 1 for c in cats},
        )
    ] * n_bins
    return ChessLogPresetSeries(preset=preset, categories=cats, bins=bins)


@unittest.skipUnless(_QT_AVAILABLE, "Qt not available in this environment")
class TestDetailChessLogChartsViewPlaceholder(unittest.TestCase):

    def _make_view(self, ai=False) -> DetailChessLogChartsView:
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller(ai_configured=ai))
        return view

    def test_placeholder_visible_on_startup(self):
        view = self._make_view()
        self.assertTrue(view._placeholder.isVisible())

    def test_chart_scroll_hidden_on_startup(self):
        view = self._make_view()
        self.assertFalse(view._chart_scroll.isVisible())

    def test_charts_unavailable_shows_placeholder(self):
        view = self._make_view()
        view._on_charts_unavailable("no_source")
        self.assertTrue(view._placeholder.isVisible())
        self.assertFalse(view._chart_scroll.isVisible())


@unittest.skipUnless(_QT_AVAILABLE, "Qt not available in this environment")
class TestDetailChessLogChartsViewNarrativePanel(unittest.TestCase):

    def test_generate_button_disabled_when_unconfigured(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller(ai_configured=False))
        self.assertFalse(view._generate_btn.isEnabled())

    def test_ai_hint_visible_when_unconfigured(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller(ai_configured=False))
        self.assertTrue(view._ai_hint.isVisible())

    def test_generate_button_enabled_when_configured(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller(ai_configured=True))
        self.assertTrue(view._generate_btn.isEnabled())

    def test_ai_hint_hidden_when_configured(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller(ai_configured=True))
        self.assertFalse(view._ai_hint.isVisible())

    def test_narrative_ready_sets_text(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller(ai_configured=True))
        view._on_narrative_ready("Great patterns found.", [])
        self.assertIn("Great patterns", view._narrative_edit.toPlainText())

    def test_narrative_ready_with_flags_shows_flagged_box(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller(ai_configured=True))
        view._on_narrative_ready("Narrative.", ["shallow note 1"])
        self.assertTrue(view._flagged_box.isVisible())

    def test_narrative_ready_no_flags_hides_flagged_box(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller(ai_configured=True))
        view._on_narrative_ready("Narrative.", [])
        self.assertFalse(view._flagged_box.isVisible())

    def test_narrative_failed_sets_error_text(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller(ai_configured=True))
        view._on_narrative_failed("Connection refused")
        self.assertIn("Connection refused", view._narrative_edit.toPlainText())


@unittest.skipUnless(_QT_AVAILABLE, "Qt not available in this environment")
class TestDetailChessLogChartsViewCharts(unittest.TestCase):

    def test_charts_updated_creates_one_widget_per_preset(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller())
        data = {
            "CLAMP": _make_series("CLAMP", ["C", "L"]),
            "CCT": _make_series("CCT", ["Checks"]),
        }
        view._on_charts_updated(data)
        self.assertEqual(len(view._chart_widgets), 2)

    def test_charts_updated_hides_placeholder(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller())
        data = {"CLAMP": _make_series("CLAMP", ["C"])}
        view._on_charts_updated(data)
        self.assertFalse(view._placeholder.isVisible())
        self.assertTrue(view._chart_scroll.isVisible())

    def test_charts_updated_with_empty_dict_shows_placeholder(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller())
        view._on_charts_updated({})
        self.assertTrue(view._placeholder.isVisible())

    def test_second_update_replaces_first(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller())
        view._on_charts_updated({"CLAMP": _make_series("CLAMP", ["C"])})
        view._on_charts_updated({"CCT": _make_series("CCT", ["Checks"])})
        self.assertEqual(len(view._chart_widgets), 1)


@unittest.skipUnless(_QT_AVAILABLE, "Qt not available in this environment")
class TestDetailChessLogChartsViewSelector(unittest.TestCase):

    def test_source_combo_has_five_options(self):
        view = DetailChessLogChartsView(config={})
        self.assertEqual(view._source_combo.count(), len(_SOURCE_LABELS))

    def test_player_combo_starts_with_all_players(self):
        view = DetailChessLogChartsView(config={})
        self.assertEqual(view._player_combo.count(), 1)
        self.assertEqual(view._player_combo.itemText(0), "All players")

    def test_players_ready_populates_player_combo(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller())
        view._on_players_ready(["Alice", "Bob"])
        # "All players" + 2 names = 3
        self.assertEqual(view._player_combo.count(), 3)

    def test_players_ready_preserves_current_selection(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller())
        view._on_players_ready(["Alice", "Bob"])
        view._player_combo.setCurrentIndex(1)  # "Alice"
        view._on_players_ready(["Alice", "Bob", "Carlos"])
        self.assertEqual(view._player_combo.currentText(), "Alice")


if __name__ == "__main__":
    unittest.main()
