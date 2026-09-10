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


class TestGetEntriesAtActivePath(unittest.TestCase):
    def test_returns_empty_for_untagged_path(self):
        ctrl, _ = make_controller(make_game())
        ctrl._cached_game_id = make_game().game_number
        with patch("app.controllers.chess_log_controller.encode_path", return_value="0"):
            result = ctrl.get_entries_at_active_path()
        self.assertEqual(result, [])

    def test_returns_entries_for_tagged_path(self):
        game = make_game()
        ctrl, _ = make_controller(game)
        ctrl._cached_game_id = game.game_number
        entry = ChessLogStorageService.make_entry("CLAMP", "M")
        ctrl._cached_paths_data = {"0": [entry]}
        with patch("app.controllers.chess_log_controller.encode_path", return_value="0"):
            result = ctrl.get_entries_at_active_path()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["cat"], "M")

    def test_returns_copy_not_reference(self):
        game = make_game()
        ctrl, _ = make_controller(game)
        ctrl._cached_game_id = game.game_number
        ctrl._cached_paths_data = {"0": [ChessLogStorageService.make_entry("CLAMP", "C")]}
        with patch("app.controllers.chess_log_controller.encode_path", return_value="0"):
            result = ctrl.get_entries_at_active_path()
        result.clear()
        self.assertEqual(len(ctrl._cached_paths_data["0"]), 1)


class TestRetagSamePresetReplaces(unittest.TestCase):
    def test_retag_same_preset_replaces_not_appends(self):
        game = make_game()
        ctrl, _ = make_controller(game)
        ctrl._cached_game_id = game.game_number
        ctrl._cached_paths_data = {
            "0": [ChessLogStorageService.make_entry("CLAMP", "M")],
        }
        with patch("app.controllers.chess_log_controller.encode_path", return_value="0"):
            ctrl.add_moment_at_active_path([{"preset": "CLAMP", "cat": "C", "why": ""}])
        entries = ctrl._cached_paths_data["0"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["cat"], "C")

    def test_retag_different_preset_preserves_existing(self):
        game = make_game()
        ctrl, _ = make_controller(game)
        ctrl._cached_game_id = game.game_number
        ctrl._cached_paths_data = {
            "0": [ChessLogStorageService.make_entry("CLAMP", "M")],
        }
        with patch("app.controllers.chess_log_controller.encode_path", return_value="0"):
            ctrl.add_moment_at_active_path([{"preset": "CCT", "cat": "Threats", "why": ""}])
        entries = ctrl._cached_paths_data["0"]
        self.assertEqual(len(entries), 2)
        presets = {e["preset"] for e in entries}
        self.assertEqual(presets, {"CLAMP", "CCT"})

    def test_retag_still_counts_as_one_moment(self):
        """Re-tagging an existing path doesn't increase the moment count."""
        game = make_game()
        ctrl, _ = make_controller(game)
        ctrl._cached_game_id = game.game_number
        ctrl._cached_paths_data = {
            "0": [ChessLogStorageService.make_entry("CLAMP", "M")],
        }
        with patch("app.controllers.chess_log_controller.encode_path", return_value="0"):
            ctrl.add_moment_at_active_path([{"preset": "CLAMP", "cat": "C", "why": ""}])
        self.assertEqual(ChessLogStorageService.count_tags(ctrl._cached_paths_data), 1)


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


class TestGameHasAnyTags(unittest.TestCase):
    def test_true_when_cache_has_entries(self):
        game = make_game()
        ctrl, _ = make_controller(game)
        ctrl._cached_game_id = game.game_number
        ctrl._cached_paths_data = {"0": [ChessLogStorageService.make_entry("CLAMP", "C")]}
        self.assertTrue(ctrl.game_has_any_tags())

    def test_false_when_cache_empty(self):
        game = make_game()
        ctrl, _ = make_controller(game)
        ctrl._cached_game_id = game.game_number
        ctrl._cached_paths_data = {}
        self.assertFalse(ctrl.game_has_any_tags())

    def test_false_when_cache_only_has_empty_lists(self):
        game = make_game()
        ctrl, _ = make_controller(game)
        ctrl._cached_game_id = game.game_number
        ctrl._cached_paths_data = {"0": [], "0.0": []}
        self.assertFalse(ctrl.game_has_any_tags())


class TestReplaceEntriesAtPath(unittest.TestCase):
    def test_replaces_only_named_preset(self):
        game = make_game()
        ctrl, _ = make_controller(game)
        ctrl._cached_game_id = game.game_number
        ctrl._cached_paths_data = {
            "0": [
                ChessLogStorageService.make_entry("CLAMP", "M"),
                ChessLogStorageService.make_entry("Custom", "Time trouble"),
            ]
        }
        ctrl.replace_entries_at_path(
            "0", "CLAMP", [{"preset": "CLAMP", "cat": "C", "why": "new"}]
        )
        entries = ctrl._cached_paths_data["0"]
        clamp = [e for e in entries if e["preset"] == "CLAMP"]
        custom = [e for e in entries if e["preset"] == "Custom"]
        self.assertEqual(len(clamp), 1)
        self.assertEqual(clamp[0]["cat"], "C")
        self.assertEqual(len(custom), 1)
        self.assertEqual(custom[0]["cat"], "Time trouble")

    def test_new_path_creates_entry(self):
        game = make_game()
        ctrl, _ = make_controller(game)
        ctrl._cached_game_id = game.game_number
        ctrl._cached_paths_data = {}
        ctrl.replace_entries_at_path(
            "9", "CCT", [{"preset": "CCT", "cat": "Threats", "why": "missed"}]
        )
        self.assertIn("9", ctrl._cached_paths_data)
        self.assertEqual(ctrl._cached_paths_data["9"][0]["cat"], "Threats")


class TestMultiGameCache(unittest.TestCase):
    """Multi-game cache: get_tags_for_game, replace_entries_at_path_for_game,
    save_all_dirty_games, and coherency at active-game transitions."""

    def _make_ctrl(self, active_game=None):
        ctrl, gm = make_controller(active_game)
        if active_game:
            ctrl._cached_game_id = active_game.game_number
        return ctrl, gm

    # ------------------------------------------------------------------
    # Basic API
    # ------------------------------------------------------------------

    def test_get_tags_for_game_active_reads_from_single_cache(self):
        game = make_game(1)
        ctrl, _ = self._make_ctrl(game)
        entry = ChessLogStorageService.make_entry("CLAMP", "C")
        ctrl._cached_paths_data = {"0": [entry]}
        result = ctrl.get_tags_for_game(game)
        self.assertIs(result, ctrl._cached_paths_data)

    def test_get_tags_for_game_inactive_loads_and_caches(self):
        game_a = make_game(1)
        game_b = make_game(2)
        ChessLogStorageService.store_tags(
            game_b, {"0": [ChessLogStorageService.make_entry("CCT", "C")]}, {}
        )
        ctrl, _ = self._make_ctrl(game_a)
        result = ctrl.get_tags_for_game(game_b)
        self.assertEqual(ChessLogStorageService.count_tags(result), 1)
        self.assertIn(2, ctrl._multi_cache)

    def test_replace_entries_at_path_for_game_active_writes_to_single_cache(self):
        game = make_game(1)
        ctrl, _ = self._make_ctrl(game)
        ctrl.replace_entries_at_path_for_game(
            game, "0", "CLAMP", [{"preset": "CLAMP", "cat": "M", "why": "test"}]
        )
        self.assertIn("0", ctrl._cached_paths_data)
        self.assertTrue(ctrl.has_dirty_games())

    def test_replace_entries_at_path_for_game_inactive_writes_to_multi_cache(self):
        game_a = make_game(1)
        game_b = make_game(2)
        ctrl, _ = self._make_ctrl(game_a)
        ctrl.replace_entries_at_path_for_game(
            game_b, "0", "CLAMP", [{"preset": "CLAMP", "cat": "P", "why": ""}]
        )
        self.assertIn(2, ctrl._multi_cache)
        self.assertIn("0", ctrl._multi_cache[2])
        self.assertNotIn("0", ctrl._cached_paths_data)

    def test_save_all_dirty_games_calls_store_tags_for_each(self):
        game_a = make_game(1)
        game_b = make_game(2)
        ctrl, gm = self._make_ctrl(game_a)
        gm.active_game = game_a

        # Edit active game (goes to single-game cache)
        ctrl.replace_entries_at_path_for_game(
            game_a, "0", "CLAMP", [{"preset": "CLAMP", "cat": "C", "why": "a"}]
        )
        # Edit inactive game (goes to multi-cache)
        ctrl.replace_entries_at_path_for_game(
            game_b, "0", "CCT", [{"preset": "CCT", "cat": "Threats", "why": "b"}]
        )

        store_calls = []
        original = ChessLogStorageService.store_tags

        def fake_store(game, data, config):
            store_calls.append((game.game_number, dict(data)))
            return original(game, data, config)

        with patch("app.controllers.chess_log_controller.ChessLogStorageService.store_tags", side_effect=fake_store):
            saved, failed = ctrl.save_all_dirty_games()

        self.assertEqual(saved, 2)
        self.assertEqual(failed, 0)
        self.assertFalse(ctrl.has_dirty_games())
        game_numbers = {gn for gn, _ in store_calls}
        self.assertEqual(game_numbers, {1, 2})

    def test_save_all_dirty_games_reads_correct_store_for_active_game(self):
        """save_all_dirty_games must use _cached_paths_data for the active game."""
        game = make_game(1)
        ctrl, _ = self._make_ctrl(game)
        ctrl.replace_entries_at_path_for_game(
            game, "0", "CLAMP", [{"preset": "CLAMP", "cat": "L", "why": "from cache"}]
        )
        # Put stale data in multi_cache to confirm it is NOT used for the active game
        ctrl._multi_cache[1] = {"0": [ChessLogStorageService.make_entry("CLAMP", "P")]}

        captured = {}

        def fake_store(game, data, config):
            captured["data"] = dict(data)
            return True

        with patch("app.controllers.chess_log_controller.ChessLogStorageService.store_tags", side_effect=fake_store):
            ctrl.save_all_dirty_games()

        self.assertEqual(captured["data"]["0"][0]["cat"], "L")

    def test_save_all_dirty_games_keeps_failed_game_dirty(self):
        game = make_game(1)
        ctrl, _ = self._make_ctrl(game)
        ctrl.replace_entries_at_path_for_game(
            game, "0", "CLAMP", [{"preset": "CLAMP", "cat": "A", "why": ""}]
        )
        with patch("app.controllers.chess_log_controller.ChessLogStorageService.store_tags", return_value=False):
            saved, failed = ctrl.save_all_dirty_games()
        self.assertEqual(saved, 0)
        self.assertEqual(failed, 1)
        self.assertTrue(ctrl.has_dirty_games())

    # ------------------------------------------------------------------
    # Transition coherency
    # ------------------------------------------------------------------

    def test_edit_inactive_game_then_activate_preserves_edit(self):
        """Editing Game B while Game A is active — the edit survives when Game B becomes active."""
        game_a = make_game(1)
        game_b = make_game(2)

        ctrl, gm = self._make_ctrl(game_a)
        gm.active_game = game_a

        ctrl.replace_entries_at_path_for_game(
            game_b, "0", "CLAMP", [{"preset": "CLAMP", "cat": "M", "why": "edited"}]
        )
        self.assertIn("0", ctrl._multi_cache.get(2, {}))

        # Switch active game to Game B
        gm.active_game = game_b
        ctrl._on_active_game_changed(game_b)

        tags = ctrl.get_tags_for_current_game()
        self.assertIn("0", tags)
        self.assertEqual(tags["0"][0]["cat"], "M")
        self.assertEqual(tags["0"][0]["why"], "edited")

    def test_switch_away_from_dirty_active_game_preserves_edit(self):
        """Game A is active and dirty; switching to Game B and back must preserve Game A's edit."""
        game_a = make_game(1)
        game_b = make_game(2)

        ctrl, gm = self._make_ctrl(game_a)
        gm.active_game = game_a

        ctrl.replace_entries_at_path_for_game(
            game_a, "0", "CLAMP", [{"preset": "CLAMP", "cat": "P", "why": "preserved"}]
        )

        # Switch to Game B
        gm.active_game = game_b
        ctrl._on_active_game_changed(game_b)
        self.assertNotEqual(ctrl._cached_game_id, 1)

        # Switch back to Game A
        gm.active_game = game_a
        ctrl._on_active_game_changed(game_a)
        self.assertEqual(ctrl._cached_game_id, 1)
        self.assertIn("0", ctrl._cached_paths_data)
        self.assertEqual(ctrl._cached_paths_data["0"][0]["why"], "preserved")

    def test_save_all_dirty_games_reads_from_correct_store_after_activation(self):
        """One dirty game in multi_cache + one dirty active game — save_all reads from the right place."""
        game_a = make_game(1)  # will be active
        game_b = make_game(2)  # will stay in multi_cache

        ctrl, gm = self._make_ctrl(game_a)
        gm.active_game = game_a

        ctrl.replace_entries_at_path_for_game(
            game_a, "0", "CLAMP", [{"preset": "CLAMP", "cat": "C", "why": "active-edit"}]
        )
        ctrl.replace_entries_at_path_for_game(
            game_b, "0", "CCT", [{"preset": "CCT", "cat": "Checks", "why": "multi-edit"}]
        )

        captured = {}

        def fake_store(game, data, config):
            captured[game.game_number] = {
                pk: [e["why"] for e in entries]
                for pk, entries in data.items()
            }
            return True

        with patch("app.controllers.chess_log_controller.ChessLogStorageService.store_tags", side_effect=fake_store):
            saved, failed = ctrl.save_all_dirty_games()

        self.assertEqual(saved, 2)
        self.assertEqual(failed, 0)
        self.assertIn("active-edit", captured.get(1, {}).get("0", []))
        self.assertIn("multi-edit", captured.get(2, {}).get("0", []))


class TestIgnoreShallowPreservation(unittest.TestCase):
    """replace_entries_at_path and _for_game must preserve the ignore_shallow field."""

    def test_replace_entries_at_path_preserves_ignore_shallow(self):
        game = make_game(1)
        ctrl, _ = make_controller(game)
        ctrl._cached_game_id = game.game_number
        entry = ChessLogStorageService.make_entry("CLAMP", "C", "note", ignore_shallow=True)
        ctrl.replace_entries_at_path("0", "CLAMP", [entry])
        result = ctrl._cached_paths_data["0"]
        self.assertTrue(result[0].get("ignore_shallow"))

    def test_replace_entries_at_path_omits_ignore_shallow_when_false(self):
        game = make_game(1)
        ctrl, _ = make_controller(game)
        ctrl._cached_game_id = game.game_number
        entry = ChessLogStorageService.make_entry("CLAMP", "C", "note")
        ctrl.replace_entries_at_path("0", "CLAMP", [entry])
        result = ctrl._cached_paths_data["0"]
        self.assertNotIn("ignore_shallow", result[0])

    def test_replace_entries_at_path_for_game_preserves_ignore_shallow(self):
        game_a = make_game(1)
        game_b = make_game(2)
        ctrl, _ = make_controller(game_a)
        ctrl._cached_game_id = game_a.game_number
        entry = ChessLogStorageService.make_entry("CLAMP", "C", "note", ignore_shallow=True)
        ctrl.replace_entries_at_path_for_game(game_b, "0", "CLAMP", [entry])
        result = ctrl._multi_cache[2]["0"]
        self.assertTrue(result[0].get("ignore_shallow"))


if __name__ == "__main__":
    unittest.main()
