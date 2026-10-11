"""Tests for DetailChessLogChartsView freshness-cache and invalidation."""

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


_QT_OK = _qt_starts_cleanly()
requires_qt = unittest.skipUnless(_QT_OK, "Qt platform plugin unavailable")

if _QT_OK:
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication(sys.argv[:1])
    from app.views.detail_chess_log_charts_view import DetailChessLogChartsView
    from app.controllers.chess_log_charts_controller import ChessLogChartsController


_MINIMAL_CONFIG: dict = {}
_SHALLOW_KEYS = frozenset({(1, "k1", "CLAMP"), (2, "k2", "CCT")})


@requires_qt
class TestShalowKeysFreshness(unittest.TestCase):
    def setUp(self):
        self._view = DetailChessLogChartsView(_MINIMAL_CONFIG)

    def test_initial_state_is_none(self):
        self.assertIsNone(self._view._last_shallow_keys)

    def test_on_shallow_ready_caches_keys(self):
        self._view._on_shallow_ready(_SHALLOW_KEYS, frozenset(), frozenset(), None)
        self.assertEqual(self._view._last_shallow_keys, _SHALLOW_KEYS)

    def test_on_shallow_ready_empty_set_stores_none(self):
        self._view._on_shallow_ready(_SHALLOW_KEYS, frozenset(), frozenset(), None)  # set first
        self._view._on_shallow_ready(set(), frozenset(), frozenset(), None)
        self.assertIsNone(self._view._last_shallow_keys)

    def test_on_source_changed_clears_cache(self):
        self._view._on_shallow_ready(_SHALLOW_KEYS, frozenset(), frozenset(), None)
        self._view._on_source_changed(1)
        self.assertIsNone(self._view._last_shallow_keys)

    def test_on_player_changed_clears_cache(self):
        self._view._on_shallow_ready(_SHALLOW_KEYS, frozenset(), frozenset(), None)
        # _on_player_changed with index=-1 returns early without controller call
        # but still clears cache
        self._view._on_player_changed(-1)
        self.assertIsNone(self._view._last_shallow_keys)

    def test_cache_survives_narrative_ready(self):
        self._view._on_shallow_ready(_SHALLOW_KEYS, frozenset(), frozenset(), None)
        # Narrative update should not touch shallow cache
        self._view._on_narrative_ready("some narrative", [], None)
        self.assertEqual(self._view._last_shallow_keys, _SHALLOW_KEYS)

    def test_cache_type_is_frozenset(self):
        self._view._on_shallow_ready({(1, "k", "CLAMP")}, frozenset(), frozenset(), None)
        self.assertIsInstance(self._view._last_shallow_keys, frozenset)


def _make_ctrl():
    """Minimal controller that won't start any threads or need real data."""
    db_ctrl = MagicMock()
    db_ctrl.get_panel_model.return_value = None
    db_ctrl.get_active_database.return_value = MagicMock(get_all_games=MagicMock(return_value=[]))
    return ChessLogChartsController(config={}, database_controller=db_ctrl)


@requires_qt
class TestThemeRebuildPreservesResults(unittest.TestCase):
    """Result cache in the controller survives view destruction (theme change)."""

    def _simulate_theme_rebuild(self, ctrl):
        """Return a fresh view wired to ctrl — the same as apply_theme's _setup_ui does."""
        view = DetailChessLogChartsView(_MINIMAL_CONFIG)
        with patch.object(ctrl, "_start_dropdown_worker"):
            view.set_controller(ctrl)
        return view

    def test_narrative_survives_theme_rebuild(self):
        ctrl = _make_ctrl()
        ctrl._on_narrative_thread_ready("Deep pawn structure issues.", [], None)

        view = self._simulate_theme_rebuild(ctrl)

        self.assertEqual(view._last_narrative, "Deep pawn structure issues.")
        # Token label is empty (None usage) but narrative text is present.
        self.assertNotEqual(view._narrative_edit.toPlainText().strip(), "")

    def test_narrative_token_counts_survive_theme_rebuild(self):
        from app.services.ai_service import TokenUsage
        ctrl = _make_ctrl()
        usage = TokenUsage(input_tokens=100, output_tokens=50, reasoning_tokens=None, reported=True)
        ctrl._on_narrative_thread_ready("Good endgame technique.", [], usage)

        view = self._simulate_theme_rebuild(ctrl)

        self.assertIn("50", view._narrative_token_label.text())

    def test_shallow_keys_survive_theme_rebuild(self):
        ctrl = _make_ctrl()
        ctrl._on_shallow_thread_ready(_SHALLOW_KEYS, frozenset(), frozenset(), None)

        view = self._simulate_theme_rebuild(ctrl)

        self.assertEqual(view._last_shallow_keys, _SHALLOW_KEYS)

    def test_shallow_token_counts_survive_theme_rebuild(self):
        from app.services.ai_service import TokenUsage
        ctrl = _make_ctrl()
        usage = TokenUsage(input_tokens=80, output_tokens=30, reasoning_tokens=None, reported=True)
        ctrl._on_shallow_thread_ready(_SHALLOW_KEYS, frozenset(), frozenset(), usage)

        view = self._simulate_theme_rebuild(ctrl)

        self.assertIn("30", view._shallow_token_label.text())

    def test_database_switch_clears_narrative_before_rebuild(self):
        ctrl = _make_ctrl()
        ctrl._on_narrative_thread_ready("Stale narrative.", [], None)
        ctrl._source_selection = 1  # needed so _on_active_database_changed acts

        with patch.object(ctrl, "_start_dropdown_worker"), \
             patch.object(ctrl, "_cancel_agg_worker"), \
             patch.object(ctrl, "_cancel_shallow_thread"):
            ctrl._on_active_database_changed(MagicMock())

        view = self._simulate_theme_rebuild(ctrl)

        self.assertEqual(view._last_narrative, "")
        self.assertEqual(view._narrative_edit.toPlainText().strip(), "")

    def test_database_switch_clears_shallow_before_rebuild(self):
        ctrl = _make_ctrl()
        ctrl._on_shallow_thread_ready(_SHALLOW_KEYS, frozenset(), frozenset(), None)
        ctrl._source_selection = 1

        with patch.object(ctrl, "_start_dropdown_worker"), \
             patch.object(ctrl, "_cancel_agg_worker"), \
             patch.object(ctrl, "_cancel_shallow_thread"):
            ctrl._on_active_database_changed(MagicMock())

        view = self._simulate_theme_rebuild(ctrl)

        self.assertIsNone(view._last_shallow_keys)

    def test_player_change_clears_both_before_rebuild(self):
        ctrl = _make_ctrl()
        ctrl._on_narrative_thread_ready("Player A narrative.", [], None)
        ctrl._on_shallow_thread_ready(_SHALLOW_KEYS, frozenset(), frozenset(), None)

        with patch.object(ctrl, "_kick_debounce"):
            ctrl.set_player_selection("Player B")

        view = self._simulate_theme_rebuild(ctrl)

        self.assertEqual(view._last_narrative, "")
        self.assertIsNone(view._last_shallow_keys)

    def test_source_change_clears_both_before_rebuild(self):
        ctrl = _make_ctrl()
        ctrl._on_narrative_thread_ready("Source A narrative.", [], None)
        ctrl._on_shallow_thread_ready(_SHALLOW_KEYS, frozenset(), frozenset(), None)

        with patch.object(ctrl, "_start_dropdown_worker"), \
             patch.object(ctrl, "_cancel_agg_worker"):
            ctrl.set_source_selection(2)

        view = self._simulate_theme_rebuild(ctrl)

        self.assertEqual(view._last_narrative, "")
        self.assertIsNone(view._last_shallow_keys)


if __name__ == "__main__":
    unittest.main()
