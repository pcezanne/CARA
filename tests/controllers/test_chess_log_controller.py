"""Unit tests for ChessLogController.

Uses MagicMock for GameModel to avoid requiring a running QApplication;
the real Qt signal/slot wiring is exercised in CI (QT_QPA_PLATFORM=offscreen).
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.controllers.chess_log_controller import ChessLogController
from app.models.database_model import GameData
from app.services.chess_log_storage_service import ChessLogStorageService

MINIMAL_PGN = (
    '[Event "Test"]\n[Site "?"]\n[Date "2026.08.24"]\n'
    '[Round "?"]\n[White "White"]\n[Black "Black"]\n[Result "*"]\n\n*\n'
)


def make_game(game_number: int = 1, pgn: str = MINIMAL_PGN) -> GameData:
    return GameData(game_number=game_number, pgn=pgn)


def make_game_model_mock(game: GameData = None, active_path=()) -> MagicMock:
    """Return a MagicMock that behaves like GameModel for ChessLogController."""
    gm = MagicMock()
    gm.active_game = game
    gm.get_active_path.return_value = active_path
    gm.active_game_changed = MagicMock()
    gm.active_game_changed.connect = MagicMock()
    gm.metadata_updated = MagicMock()
    gm.metadata_updated.emit = MagicMock()
    return gm


def make_game_controller_mock(game_model: MagicMock) -> MagicMock:
    gc = MagicMock()
    gc.get_game_model.return_value = game_model
    return gc


def make_user_settings_mock(active_preset="CLAMP", custom_categories=None) -> MagicMock:
    uss = MagicMock()
    uss.get_chess_log.return_value = {
        "active_preset": active_preset,
        "custom_categories": custom_categories or [],
    }
    return uss


def make_controller(game=None, active_path=(), user_settings_service=None) -> tuple[ChessLogController, MagicMock]:
    gm = make_game_model_mock(game, active_path)
    gc = make_game_controller_mock(gm)
    ctrl = ChessLogController({}, gc, user_settings_service=user_settings_service)
    return ctrl, gm


class TestPresetAccessors(unittest.TestCase):
    def test_get_active_preset_reads_from_user_settings(self):
        uss = make_user_settings_mock(active_preset="CCT")
        ctrl, _ = make_controller(user_settings_service=uss)
        self.assertEqual(ctrl.get_active_preset(), "CCT")

    def test_get_custom_categories_reads_from_user_settings(self):
        uss = make_user_settings_mock(custom_categories=["Time trouble", "Wrong plan"])
        ctrl, _ = make_controller(user_settings_service=uss)
        self.assertEqual(ctrl.get_custom_categories(), ["Time trouble", "Wrong plan"])

    def test_get_active_preset_defaults_to_clamp_when_no_service(self):
        ctrl, _ = make_controller(user_settings_service=None)
        self.assertEqual(ctrl.get_active_preset(), "CLAMP")

    def test_get_custom_categories_defaults_to_empty_when_no_service(self):
        ctrl, _ = make_controller(user_settings_service=None)
        self.assertEqual(ctrl.get_custom_categories(), [])

    def test_get_active_preset_defaults_to_clamp_when_key_missing(self):
        uss = MagicMock()
        uss.get_chess_log.return_value = {}  # chess_log key exists but active_preset missing
        ctrl, _ = make_controller(user_settings_service=uss)
        self.assertEqual(ctrl.get_active_preset(), "CLAMP")

    def test_get_custom_categories_defaults_to_empty_when_key_missing(self):
        uss = MagicMock()
        uss.get_chess_log.return_value = {}
        ctrl, _ = make_controller(user_settings_service=uss)
        self.assertEqual(ctrl.get_custom_categories(), [])


class TestAddMomentBelowCap(unittest.TestCase):
    def test_add_first_moment(self):
        game = make_game()
        ctrl, _ = make_controller(game)
        ctrl._cached_game_id = game.game_number

        with patch("app.controllers.chess_log_controller.encode_path", return_value="0"):
            result = ctrl.add_moment_at_active_path([{"preset": "CLAMP", "cat": "M", "why": ""}])

        self.assertTrue(result)
        self.assertEqual(ChessLogStorageService.count_tags(ctrl._cached_paths_data), 1)

    def test_add_three_distinct_moments(self):
        game = make_game()
        ctrl, _ = make_controller(game)
        ctrl._cached_game_id = game.game_number
        for path_key in ("0", "0.0", "0.0.0"):
            with patch("app.controllers.chess_log_controller.encode_path", return_value=path_key):
                self.assertTrue(
                    ctrl.add_moment_at_active_path([{"preset": "CLAMP", "cat": "L", "why": ""}])
                )
        self.assertEqual(ChessLogStorageService.count_tags(ctrl._cached_paths_data), 3)

    def test_empty_entries_returns_false(self):
        ctrl, _ = make_controller(make_game())
        self.assertFalse(ctrl.add_moment_at_active_path([]))

    def test_no_active_game_returns_false(self):
        ctrl, _ = make_controller(game=None)
        self.assertFalse(ctrl.add_moment_at_active_path([{"preset": "CCT", "cat": "C", "why": ""}]))


class TestFourthMomentConfirmation(unittest.TestCase):
    def _ctrl_with_three_moments(self) -> ChessLogController:
        game = make_game()
        ctrl, _ = make_controller(game)
        ctrl._cached_game_id = game.game_number
        ctrl._cached_paths_data = {
            "0": [ChessLogStorageService.make_entry("CLAMP", "M")],
            "0.0": [ChessLogStorageService.make_entry("CLAMP", "L")],
            "0.0.0": [ChessLogStorageService.make_entry("CCT", "C")],
        }
        return ctrl

    def test_fourth_moment_confirmation_accepted(self):
        ctrl = self._ctrl_with_three_moments()
        with patch("app.controllers.chess_log_controller.encode_path", return_value="0.0.0.0"), \
             patch("app.views.dialogs.confirmation_dialog.ConfirmationDialog.show_confirmation", return_value=True):
            result = ctrl.add_moment_at_active_path([{"preset": "CLAMP", "cat": "P", "why": ""}])
        self.assertTrue(result)
        self.assertEqual(ChessLogStorageService.count_tags(ctrl._cached_paths_data), 4)

    def test_fourth_moment_confirmation_declined(self):
        ctrl = self._ctrl_with_three_moments()
        with patch("app.controllers.chess_log_controller.encode_path", return_value="0.0.0.0"), \
             patch("app.views.dialogs.confirmation_dialog.ConfirmationDialog.show_confirmation", return_value=False):
            result = ctrl.add_moment_at_active_path([{"preset": "CLAMP", "cat": "A", "why": ""}])
        self.assertFalse(result)
        self.assertEqual(ChessLogStorageService.count_tags(ctrl._cached_paths_data), 3)

    def test_adding_to_existing_path_skips_confirmation(self):
        """Adding a second CCT letter to an already-tagged path stays at 3 moments — no dialog."""
        ctrl = self._ctrl_with_three_moments()
        with patch("app.controllers.chess_log_controller.encode_path", return_value="0.0"):  # already exists
            result = ctrl.add_moment_at_active_path([{"preset": "CCT", "cat": "T", "why": ""}])
        self.assertTrue(result)
        self.assertEqual(ChessLogStorageService.count_tags(ctrl._cached_paths_data), 3)
        self.assertEqual(len(ctrl._cached_paths_data["0.0"]), 2)


class TestSaveAndClear(unittest.TestCase):
    def test_save_persists_to_pgn(self):
        game = make_game()
        ctrl, gm = make_controller(game)
        ctrl._cached_game_id = game.game_number
        with patch("app.controllers.chess_log_controller.encode_path", return_value="0"):
            ctrl.add_moment_at_active_path([{"preset": "CLAMP", "cat": "A", "why": "test"}])
        ctrl.save_tags_for_current_game()
        self.assertTrue(ChessLogStorageService.has_chess_log_tags(game))
        loaded = ChessLogStorageService.load_tags(game)
        self.assertEqual(ChessLogStorageService.count_tags(loaded), 1)

    def test_clear_removes_from_pgn(self):
        game = make_game()
        ctrl, gm = make_controller(game)
        ctrl._cached_game_id = game.game_number
        with patch("app.controllers.chess_log_controller.encode_path", return_value="0"):
            ctrl.add_moment_at_active_path([{"preset": "CCT", "cat": "C", "why": ""}])
        ctrl.save_tags_for_current_game()
        ctrl.clear_tags_for_current_game()
        self.assertFalse(ChessLogStorageService.has_chess_log_tags(game))
        self.assertEqual(ctrl._cached_paths_data, {})

    def test_metadata_updated_emitted_on_save(self):
        game = make_game()
        ctrl, gm = make_controller(game)
        ctrl._cached_game_id = game.game_number
        ctrl.save_tags_for_current_game()
        gm.metadata_updated.emit.assert_called_once()

    def test_metadata_updated_emitted_on_clear(self):
        game = make_game()
        ctrl, gm = make_controller(game)
        ctrl._cached_game_id = game.game_number
        ctrl.clear_tags_for_current_game()
        gm.metadata_updated.emit.assert_called_once()


class TestCacheReloadOnGameChange(unittest.TestCase):
    def test_cache_reloads_when_game_changes(self):
        game2 = make_game(game_number=2)
        ChessLogStorageService.store_tags(
            game2, {"0": [ChessLogStorageService.make_entry("CLAMP", "P")]}
        )
        ctrl, gm = make_controller(game=None)

        # Simulate game1 loaded (no tags)
        game1 = make_game(game_number=1)
        gm.active_game = game1
        ctrl._on_active_game_changed(game1)
        self.assertEqual(ctrl.get_tags_for_current_game(), {})

        # Switch to game2 (has a tag)
        gm.active_game = game2
        ctrl._on_active_game_changed(game2)
        tags = ctrl.get_tags_for_current_game()
        self.assertEqual(ChessLogStorageService.count_tags(tags), 1)

    def test_cache_clears_on_none_game(self):
        game = make_game()
        ctrl, gm = make_controller(game)
        ctrl._cached_game_id = game.game_number
        ctrl._cached_paths_data = {"0": [ChessLogStorageService.make_entry("CCT", "C")]}

        gm.active_game = None
        ctrl._on_active_game_changed(None)
        self.assertEqual(ctrl._cached_paths_data, {})
        self.assertIsNone(ctrl._cached_game_id)


if __name__ == "__main__":
    unittest.main()
