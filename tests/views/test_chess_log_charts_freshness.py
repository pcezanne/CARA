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
    from app.models.database_model import GameData

_MINIMAL_CONFIG: dict = {}
# Use GameData objects as keys (identity-keyed, not game_number-keyed)
_GAME_1 = GameData(game_number=1) if _QT_OK else None
_GAME_2 = GameData(game_number=2) if _QT_OK else None
_SHALLOW_KEYS = frozenset({(_GAME_1, "k1", "CLAMP", ""), (_GAME_2, "k2", "CCT", "")}) if _QT_OK else frozenset()
_GAME_3 = GameData(game_number=3) if _QT_OK else None
_VAGUE_KEYS = frozenset({(_GAME_3, "v1", "3x3", "Why4")}) if _QT_OK else frozenset()


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
        g = GameData(game_number=1)
        self._view._on_shallow_ready({(g, "k", "CLAMP", "")}, frozenset(), frozenset(), None)
        self.assertIsInstance(self._view._last_shallow_keys, frozenset)


@requires_qt
class TestVagueKeysFreshness(unittest.TestCase):
    """_last_vague_keys mirrors _last_shallow_keys lifecycle."""

    def setUp(self):
        self._view = DetailChessLogChartsView(_MINIMAL_CONFIG)

    def test_initial_state_is_none(self):
        self.assertIsNone(self._view._last_vague_keys)

    def test_on_shallow_ready_caches_vague_keys(self):
        self._view._on_shallow_ready(_SHALLOW_KEYS, _VAGUE_KEYS, frozenset(), None)
        self.assertEqual(self._view._last_vague_keys, _VAGUE_KEYS)

    def test_on_shallow_ready_empty_vague_stores_none(self):
        self._view._on_shallow_ready(_SHALLOW_KEYS, _VAGUE_KEYS, frozenset(), None)
        self._view._on_shallow_ready(_SHALLOW_KEYS, frozenset(), frozenset(), None)
        self.assertIsNone(self._view._last_vague_keys)

    def test_on_source_changed_clears_vague_keys(self):
        self._view._on_shallow_ready(_SHALLOW_KEYS, _VAGUE_KEYS, frozenset(), None)
        self._view._on_source_changed(1)
        self.assertIsNone(self._view._last_vague_keys)

    def test_on_player_changed_clears_vague_keys(self):
        self._view._on_shallow_ready(_SHALLOW_KEYS, _VAGUE_KEYS, frozenset(), None)
        self._view._on_player_changed(-1)
        self.assertIsNone(self._view._last_vague_keys)

    def test_cache_type_is_frozenset(self):
        g = GameData(game_number=9)
        self._view._on_shallow_ready(_SHALLOW_KEYS, {(g, "x", "3x3", "Why1")}, frozenset(), None)
        self.assertIsInstance(self._view._last_vague_keys, frozenset)


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

    def test_vague_keys_survive_theme_rebuild(self):
        ctrl = _make_ctrl()
        ctrl._on_shallow_thread_ready(_SHALLOW_KEYS, _VAGUE_KEYS, frozenset(), None)

        view = self._simulate_theme_rebuild(ctrl)

        self.assertEqual(view._last_vague_keys, _VAGUE_KEYS)

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


@requires_qt
class TestMomentInLastShallowHelper(unittest.TestCase):
    """Tests for _moment_in_last_shallow — the identity-safe helper that replaces
    the pre-fix 4-tuple cat-based lookup (which mismatched CLAMP entries)."""

    def setUp(self):
        self._view = DetailChessLogChartsView(_MINIMAL_CONFIG)

    def test_clamp_hit(self):
        """CLAMP moment whose game object is in shallow_keys returns True."""
        self._view._last_shallow_keys = _SHALLOW_KEYS
        self.assertTrue(self._view._moment_in_last_shallow(_GAME_1, "k1", "CLAMP"))

    def test_clamp_miss_different_object(self):
        """A DIFFERENT game object (same game_number) must NOT match — identity check."""
        self._view._last_shallow_keys = _SHALLOW_KEYS
        other_game = GameData(game_number=1)  # same number, different object
        self.assertFalse(self._view._moment_in_last_shallow(other_game, "k1", "CLAMP"))

    def test_clamp_miss_different_path(self):
        self._view._last_shallow_keys = _SHALLOW_KEYS
        self.assertFalse(self._view._moment_in_last_shallow(_GAME_1, "k9", "CLAMP"))

    def test_3x3_any_cat_hit(self):
        """3x3 moment returns True if any Why cat is in shallow_keys."""
        g = GameData(game_number=99)
        self._view._last_shallow_keys = frozenset([(g, "k", "3x3", "Why2")])
        self.assertTrue(self._view._moment_in_last_shallow(g, "k", "3x3"))

    def test_3x3_no_cat_miss(self):
        """3x3 moment returns False when no Why cat is in shallow_keys."""
        g = GameData(game_number=99)
        self._view._last_shallow_keys = frozenset()
        self.assertFalse(self._view._moment_in_last_shallow(g, "k", "3x3"))

    def test_stale_cache_no_false_positive(self):
        """A new game with the same game_number must not match the stale cache entry."""
        game_original = GameData(game_number=1)
        self._view._last_shallow_keys = frozenset([(game_original, "k", "CLAMP", "")])
        game_new = GameData(game_number=1)  # different object, same number
        self.assertFalse(self._view._moment_in_last_shallow(game_new, "k", "CLAMP"),
                         "identity-keyed lookup must not match a different object")

    def test_sort_reindex_does_not_break_identity(self):
        """Even if game_number is reassigned (simulating sort/reindex),
        the object-identity key must still match the original game object."""
        game = GameData(game_number=5)
        self._view._last_shallow_keys = frozenset([(game, "k", "CLAMP", "")])
        # Simulate sort reassigning game_number
        game.game_number = 2
        self.assertTrue(self._view._moment_in_last_shallow(game, "k", "CLAMP"),
                        "shallow_keys must still match after game_number reassignment")

    def test_none_shallow_keys_returns_false(self):
        self._view._last_shallow_keys = None
        self.assertFalse(self._view._moment_in_last_shallow(_GAME_1, "k1", "CLAMP"))

    def test_3x3_vague_only_hit(self):
        """3x3 moment in vague_keys only (not shallow_keys) must return True."""
        g = GameData(game_number=7)
        self._view._last_shallow_keys = frozenset()
        self._view._last_vague_keys = frozenset([(g, "0", "3x3", "Why4")])
        self.assertTrue(self._view._moment_in_last_shallow(g, "0", "3x3"),
                        "vague-only 3x3 Why4 moment must appear in export")

    def test_clamp_vague_only_hit(self):
        """CLAMP moment in vague_keys only must return True."""
        g = GameData(game_number=8)
        self._view._last_shallow_keys = frozenset()
        self._view._last_vague_keys = frozenset([(g, "p", "CLAMP", "")])
        self.assertTrue(self._view._moment_in_last_shallow(g, "p", "CLAMP"),
                        "vague-only CLAMP moment must appear in export")

    def test_3x3_in_neither_returns_false(self):
        """3x3 moment absent from both shallow_keys and vague_keys returns False."""
        g = GameData(game_number=9)
        self._view._last_shallow_keys = frozenset()
        self._view._last_vague_keys = frozenset()
        self.assertFalse(self._view._moment_in_last_shallow(g, "0", "3x3"))

    def test_none_vague_keys_falls_back_to_shallow(self):
        """When vague_keys is None, a shallow_keys hit still returns True."""
        self._view._last_shallow_keys = _SHALLOW_KEYS
        self._view._last_vague_keys = None
        self.assertTrue(self._view._moment_in_last_shallow(_GAME_1, "k1", "CLAMP"))


@requires_qt
class TestGameSetChangeClearsDisplay(unittest.TestCase):
    """#77: narrative edit, token labels, and flagged box must visually clear when
    the game set changes (DB switch, player change, source change).  Each test
    that mutates display state must fail before the fix and pass after."""

    def setUp(self):
        self._view = DetailChessLogChartsView(_MINIMAL_CONFIG)
        self._view._on_narrative_ready("Old narrative text.", [], None)

    # --- DB switch / reset_player_selection ---

    def test_db_switch_clears_narrative_edit_text(self):
        """After _reset_player_selection (triggered by DB switch), narrative edit is empty."""
        self.assertNotEqual(self._view._narrative_edit.toPlainText().strip(), "")
        self._view._reset_player_selection()
        self.assertEqual(self._view._narrative_edit.toPlainText().strip(), "")

    def test_db_switch_clears_last_narrative(self):
        """_reset_player_selection clears _last_narrative (PDF export protection)."""
        self._view._reset_player_selection()
        self.assertEqual(self._view._last_narrative, "")

    def test_db_switch_clears_shallow_token_label(self):
        """_reset_player_selection clears _shallow_token_label."""
        self._view._shallow_token_label.setText("Tokens: 100 in / 50 out")
        self._view._reset_player_selection()
        self.assertEqual(self._view._shallow_token_label.text(), "")

    def test_db_switch_clears_narrative_token_label(self):
        """_reset_player_selection clears _narrative_token_label."""
        self._view._narrative_token_label.setText("Tokens: 200 in / 80 out")
        self._view._reset_player_selection()
        self.assertEqual(self._view._narrative_token_label.text(), "")

    # --- player change ---

    def test_player_change_clears_narrative_edit_text(self):
        """Player change must clear _narrative_edit display."""
        self.assertNotEqual(self._view._narrative_edit.toPlainText().strip(), "")
        self._view._on_player_changed(-1)
        self.assertEqual(self._view._narrative_edit.toPlainText().strip(), "")

    def test_player_change_clears_last_narrative(self):
        """Player change must clear _last_narrative (PDF export protection)."""
        self.assertEqual(self._view._last_narrative, "Old narrative text.")
        self._view._on_player_changed(-1)
        self.assertEqual(self._view._last_narrative, "")

    def test_player_change_clears_shallow_keys(self):
        """Player change must clear _last_shallow_keys."""
        self._view._last_shallow_keys = _SHALLOW_KEYS
        self._view._on_player_changed(-1)
        self.assertIsNone(self._view._last_shallow_keys)

    # --- positive control: chart redraw does NOT clear ---

    def test_chart_loading_does_not_clear_narrative(self):
        """_on_charts_loading (chart redraw, same game set) must not clear narrative."""
        narrative_before = self._view._last_narrative
        self._view._on_charts_loading()
        self.assertEqual(self._view._last_narrative, narrative_before)
        self.assertNotEqual(self._view._narrative_edit.toPlainText().strip(), "")

    def test_chart_updated_does_not_clear_narrative(self):
        """_on_charts_updated (chart redraw result) must not clear narrative."""
        narrative_before = self._view._last_narrative
        self._view._on_charts_updated({})
        self.assertEqual(self._view._last_narrative, narrative_before)

    # --- export after clear ---

    def test_export_field_empty_after_player_change(self):
        """_last_narrative is empty after player change → PDF export gets no narrative."""
        self._view._on_player_changed(-1)
        self.assertEqual(self._view._last_narrative.strip(), "")

    def test_export_shallow_field_empty_after_db_switch(self):
        """_last_shallow_keys is None after DB switch → PDF export has no Check Logs rows."""
        self._view._last_shallow_keys = _SHALLOW_KEYS
        self._view._reset_player_selection()
        self.assertIsNone(self._view._last_shallow_keys)

    # --- saved data untouched ---

    def test_clear_does_not_call_any_save_method(self):
        """_clear_narrative_and_check_logs must not invoke any Chess Log storage method."""
        with patch(
            "app.services.chess_log_storage_service.ChessLogStorageService.store_tags"
        ) as mock_store:
            self._view._clear_narrative_and_check_logs()
        mock_store.assert_not_called()


if __name__ == "__main__":
    unittest.main()
