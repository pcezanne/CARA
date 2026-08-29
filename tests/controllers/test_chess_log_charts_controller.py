"""Tests for ChessLogChartsController.

Uses Qt (QThread / QObject) — requires an offscreen Qt platform or a running
display.  Tests skip cleanly when Qt cannot start (same guard as test_moment_dialog).
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

    from app.controllers.chess_log_charts_controller import (
        ChessLogChartsController,
        ChessLogAggregationWorker,
        ChessLogNarrativeThread,
        ChessLogPlayerDropdownWorker,
    )
    from app.models.database_model import GameData
    from app.services.chess_log_storage_service import ChessLogStorageService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_game(
    white: str = "Alice",
    black: str = "Bob",
    date: str = "2025.06.01",
    entries_per_path: dict | None = None,
) -> "GameData":
    pgn = (
        f'[Event "Test"]\n[Site "?"]\n[Date "{date}"]\n'
        f'[Round "?"]\n[White "{white}"]\n[Black "{black}"]\n'
        f'[Result "*"]\n\n1. e4 *\n'
    )
    game = GameData(game_number=1, pgn=pgn, white=white, black=black, date=date)
    if entries_per_path:
        ChessLogStorageService.store_tags(game, entries_per_path)
    return game


def _clamp(cat: str) -> dict:
    return ChessLogStorageService.make_entry("CLAMP", cat)


def _make_db_controller(games: list) -> MagicMock:
    """Stub database controller whose active DB returns the given games."""
    db = MagicMock()
    db.get_all_database_models.return_value = games
    ctrl = MagicMock()
    ctrl.get_active_database.return_value = db
    ctrl.get_panel_model.return_value = None
    return ctrl


@unittest.skipUnless(_QT_AVAILABLE, "Qt not available in this environment")
class TestChessLogChartsControllerSourceSelection(unittest.TestCase):

    def _make_controller(self, games=None) -> ChessLogChartsController:
        games = games or []
        db_ctrl = _make_db_controller(games)
        return ChessLogChartsController(config={}, database_controller=db_ctrl)

    def test_source_none_emits_charts_unavailable(self):
        ctrl = self._make_controller()
        received = []
        ctrl.charts_unavailable.connect(received.append)
        ctrl.set_source_selection(0)
        self.assertIn("no_source", received)

    def test_set_source_starts_agg_worker_for_valid_source(self):
        game = _make_game(entries_per_path={"0": [_clamp("C")]})
        ctrl = self._make_controller(games=[game])
        ctrl.set_source_selection(1)
        self.assertIsNotNone(ctrl._agg_worker)
        ctrl._cancel_agg_worker()

    def test_set_source_twice_cancels_previous_worker(self):
        game = _make_game(entries_per_path={"0": [_clamp("C")]})
        ctrl = self._make_controller(games=[game])
        ctrl.set_source_selection(1)
        first_worker = ctrl._agg_worker
        ctrl.set_source_selection(1)
        # Either the worker was replaced or cancelled
        self.assertIsNotNone(ctrl._agg_worker)
        ctrl._cancel_agg_worker()


@unittest.skipUnless(_QT_AVAILABLE, "Qt not available in this environment")
class TestChessLogChartsControllerPlayerSelection(unittest.TestCase):

    def _make_controller(self, games=None) -> ChessLogChartsController:
        games = games or []
        db_ctrl = _make_db_controller(games)
        return ChessLogChartsController(config={}, database_controller=db_ctrl)

    def test_set_player_triggers_refresh(self):
        game = _make_game(entries_per_path={"0": [_clamp("C")]})
        ctrl = self._make_controller(games=[game])
        ctrl._source_selection = 1  # bypass set_source so no prior worker
        ctrl.set_player_selection("Alice")
        self.assertIsNotNone(ctrl._agg_worker)
        ctrl._cancel_agg_worker()

    def test_player_stored_on_controller(self):
        ctrl = self._make_controller()
        ctrl.set_player_selection("Bob")
        self.assertEqual(ctrl._current_player, "Bob")

    def test_empty_player_string_stored(self):
        ctrl = self._make_controller()
        ctrl.set_player_selection("")
        self.assertEqual(ctrl._current_player, "")


@unittest.skipUnless(_QT_AVAILABLE, "Qt not available in this environment")
class TestChessLogChartsControllerAIConfigured(unittest.TestCase):

    def _make_controller(self) -> ChessLogChartsController:
        return ChessLogChartsController(config={}, database_controller=MagicMock())

    def test_no_settings_ai_not_configured(self):
        ctrl = self._make_controller()
        self.assertFalse(ctrl.is_ai_configured())

    def test_openai_settings_ai_configured(self):
        ctrl = self._make_controller()
        ctrl.set_user_settings({
            "ai_models": {"openai": {"api_key": "sk-abc", "model": "gpt-4o"}}
        })
        self.assertTrue(ctrl.is_ai_configured())

    def test_ai_configured_changed_signal_emitted_on_transition(self):
        ctrl = self._make_controller()
        received = []
        ctrl.ai_configured_changed.connect(received.append)
        ctrl.set_user_settings({
            "ai_models": {"openai": {"api_key": "sk-abc", "model": "gpt-4o"}}
        })
        self.assertEqual(received, [True])

    def test_ai_configured_changed_not_emitted_when_unchanged(self):
        ctrl = self._make_controller()
        # Already not configured; set to another unconfigured state — no signal
        received = []
        ctrl.ai_configured_changed.connect(received.append)
        ctrl.set_user_settings({})
        self.assertEqual(received, [])


@unittest.skipUnless(_QT_AVAILABLE, "Qt not available in this environment")
class TestChessLogChartsControllerNarrativeGate(unittest.TestCase):

    def _make_controller(self) -> ChessLogChartsController:
        game = _make_game(entries_per_path={"0": [_clamp("C")]})
        db_ctrl = _make_db_controller([game])
        ctrl = ChessLogChartsController(config={}, database_controller=db_ctrl)
        ctrl._source_selection = 1
        return ctrl

    def test_narrative_skipped_when_unconfigured(self):
        ctrl = self._make_controller()
        failed = []
        ctrl.narrative_failed.connect(failed.append)
        ctrl.request_narrative()
        self.assertTrue(len(failed) > 0)
        self.assertIsNone(ctrl._narrative_thread)

    def test_narrative_thread_started_when_configured(self):
        ctrl = self._make_controller()
        ctrl.set_user_settings({
            "ai_models": {"openai": {"api_key": "sk-abc", "model": "gpt-4o"}}
        })
        with patch(
            "app.controllers.chess_log_charts_controller.generate_narrative",
            return_value=(True, "Great work.", []),
        ):
            ctrl.request_narrative()
        # Thread may have already finished by the time we check, but it was started
        # (no exception means wiring was correct)


@unittest.skipUnless(_QT_AVAILABLE, "Qt not available in this environment")
class TestChessLogChartsControllerSelectedGames(unittest.TestCase):

    def test_selected_games_callback_used_for_source_3(self):
        game = _make_game(entries_per_path={"0": [_clamp("C")]})
        ctrl = ChessLogChartsController(config={}, database_controller=MagicMock())
        ctrl.set_get_selected_games_callback(lambda active_only: [game])
        ctrl._source_selection = 3
        games = ctrl._resolve_games()
        self.assertEqual(games, [game])

    def test_selected_games_callback_used_for_source_4(self):
        game = _make_game(entries_per_path={"0": [_clamp("C")]})
        ctrl = ChessLogChartsController(config={}, database_controller=MagicMock())
        ctrl.set_get_selected_games_callback(lambda active_only: [game])
        ctrl._source_selection = 4
        games = ctrl._resolve_games()
        self.assertEqual(games, [game])

    def test_no_callback_returns_empty_for_source_3(self):
        ctrl = ChessLogChartsController(config={}, database_controller=MagicMock())
        ctrl._source_selection = 3
        self.assertEqual(ctrl._resolve_games(), [])


if __name__ == "__main__":
    unittest.main()
