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
    '[Round "?"]\n[White "White"]\n[Black "Black"]\n[Result "*"]\n\n'
    '1. e4 ( 1. d4 ) e5 2. Nf3 Nc6 *\n'
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


def make_user_settings_mock(active_preset="CLAMP") -> MagicMock:
    uss = MagicMock()
    uss.get_chess_log.return_value = {"active_preset": active_preset}
    return uss


def make_controller(game=None, active_path=(), user_settings_service=None) -> tuple[ChessLogController, MagicMock]:
    gm = make_game_model_mock(game, active_path)
    gc = make_game_controller_mock(gm)
    ctrl = ChessLogController({}, gc, user_settings_service=user_settings_service)
    if game is not None:
        ctrl._cached_game = game
    return ctrl, gm


class TestPresetAccessors(unittest.TestCase):
    def test_get_active_preset_reads_from_user_settings(self):
        uss = make_user_settings_mock(active_preset="CCT")
        ctrl, _ = make_controller(user_settings_service=uss)
        self.assertEqual(ctrl.get_active_preset(), "CCT")

    def test_get_active_preset_defaults_to_clamp_when_no_service(self):
        ctrl, _ = make_controller(user_settings_service=None)
        self.assertEqual(ctrl.get_active_preset(), "CLAMP")

    def test_get_active_preset_defaults_to_clamp_when_key_missing(self):
        uss = MagicMock()
        uss.get_chess_log.return_value = {}  # chess_log key exists but active_preset missing
        ctrl, _ = make_controller(user_settings_service=uss)
        self.assertEqual(ctrl.get_active_preset(), "CLAMP")

    def test_get_active_preset_coerces_unknown_preset_to_clamp(self):
        uss = make_user_settings_mock(active_preset="Custom")
        ctrl, _ = make_controller(user_settings_service=uss)
        self.assertEqual(ctrl.get_active_preset(), "CLAMP")


class TestAddMomentBelowCap(unittest.TestCase):
    def test_add_first_moment(self):
        game = make_game()
        ctrl, _ = make_controller(game)
        ctrl._cached_game_id = id(game)

        with patch("app.controllers.chess_log_controller.encode_path", return_value="0"):
            result = ctrl.add_moment_at_active_path([{"preset": "CLAMP", "cat": "M", "why": ""}])

        self.assertTrue(result)
        self.assertEqual(ChessLogStorageService.count_tags(ctrl._cached_paths_data), 1)

    def test_add_three_distinct_moments(self):
        game = make_game()
        ctrl, _ = make_controller(game)
        ctrl._cached_game_id = id(game)
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


class TestAddMomentNagRemoved(unittest.TestCase):
    """add_moment_at_active_path no longer fires the nag — nag moved to should_confirm_extra_moment."""

    def _ctrl_with_three_moments(self) -> ChessLogController:
        game = make_game()
        ctrl, _ = make_controller(game)
        ctrl._cached_game_id = id(game)
        ctrl._cached_paths_data = {
            "0": [ChessLogStorageService.make_entry("CLAMP", "M")],
            "0.0": [ChessLogStorageService.make_entry("CLAMP", "L")],
            "0.0.0": [ChessLogStorageService.make_entry("CCT", "C")],
        }
        return ctrl

    def test_fourth_moment_added_without_nag(self):
        ctrl = self._ctrl_with_three_moments()
        with patch("app.controllers.chess_log_controller.encode_path", return_value="0.0.0.0"), \
             patch("app.views.dialogs.confirmation_dialog.ConfirmationDialog.show_confirmation") as mock_dlg:
            result = ctrl.add_moment_at_active_path([{"preset": "CLAMP", "cat": "P", "why": ""}])
        self.assertTrue(result)
        self.assertEqual(ChessLogStorageService.count_tags(ctrl._cached_paths_data), 4)
        mock_dlg.assert_not_called()

    def test_adding_to_existing_path_succeeds(self):
        ctrl = self._ctrl_with_three_moments()
        with patch("app.controllers.chess_log_controller.encode_path", return_value="0.0"):
            result = ctrl.add_moment_at_active_path([{"preset": "CCT", "cat": "T", "why": ""}])
        self.assertTrue(result)
        self.assertEqual(ChessLogStorageService.count_tags(ctrl._cached_paths_data), 3)
        self.assertEqual(len(ctrl._cached_paths_data["0.0"]), 2)


class TestShouldConfirmExtraMoment(unittest.TestCase):
    """should_confirm_extra_moment: nag fires at the right time and is suppressed correctly."""

    def _ctrl_with_three_moments(self, gid: int = 1) -> tuple[ChessLogController, MagicMock]:
        game = make_game(game_number=gid)
        ctrl, gm = make_controller(game)
        ctrl._cached_game_id = id(game)
        ctrl._cached_paths_data = {
            "0": [ChessLogStorageService.make_entry("CLAMP", "M")],
            "0.0": [ChessLogStorageService.make_entry("CLAMP", "L")],
            "0.0.0": [ChessLogStorageService.make_entry("CCT", "C")],
        }
        return ctrl, gm

    def test_nag_fires_on_fourth_new_moment_when_never_shown(self):
        ctrl, gm = self._ctrl_with_three_moments()
        gm.get_active_path.return_value = (99,)  # maps to a fresh path key
        with patch("app.controllers.chess_log_controller.encode_path", return_value="fresh"), \
             patch("app.views.dialogs.confirmation_dialog.ConfirmationDialog.show_confirmation", return_value=True) as mock_dlg:
            result = ctrl.should_confirm_extra_moment(None)
        mock_dlg.assert_called_once()
        self.assertTrue(result)
        self.assertTrue(ctrl._nag_shown_this_session)
        self.assertTrue(ctrl._nag_shown_by_game.get(id(ctrl._cached_game), False))

    def test_nag_suppressed_by_session_flag(self):
        ctrl, gm = self._ctrl_with_three_moments()
        ctrl._nag_shown_this_session = True
        gm.get_active_path.return_value = (99,)
        with patch("app.controllers.chess_log_controller.encode_path", return_value="fresh"), \
             patch("app.views.dialogs.confirmation_dialog.ConfirmationDialog.show_confirmation") as mock_dlg:
            result = ctrl.should_confirm_extra_moment(None)
        mock_dlg.assert_not_called()
        self.assertTrue(result)

    def test_nag_suppressed_by_per_game_flag(self):
        ctrl, gm = self._ctrl_with_three_moments(gid=1)
        ctrl._nag_shown_by_game[id(ctrl._cached_game)] = True
        ctrl._nag_shown_this_session = False
        gm.get_active_path.return_value = (99,)
        with patch("app.controllers.chess_log_controller.encode_path", return_value="fresh"), \
             patch("app.views.dialogs.confirmation_dialog.ConfirmationDialog.show_confirmation") as mock_dlg:
            result = ctrl.should_confirm_extra_moment(None)
        mock_dlg.assert_not_called()
        self.assertTrue(result)

    def test_nag_does_not_fire_for_reused_path(self):
        ctrl, gm = self._ctrl_with_three_moments()
        gm.get_active_path.return_value = ()
        with patch("app.controllers.chess_log_controller.encode_path", return_value="0.0"), \
             patch("app.views.dialogs.confirmation_dialog.ConfirmationDialog.show_confirmation") as mock_dlg:
            result = ctrl.should_confirm_extra_moment(None)
        mock_dlg.assert_not_called()
        self.assertTrue(result)

    def test_nag_does_not_fire_below_threshold(self):
        game = make_game()
        ctrl, gm = make_controller(game)
        ctrl._cached_game_id = id(game)
        ctrl._cached_paths_data = {
            "0": [ChessLogStorageService.make_entry("CLAMP", "M")],
            "0.0": [ChessLogStorageService.make_entry("CLAMP", "L")],
        }
        gm.get_active_path.return_value = ()
        with patch("app.controllers.chess_log_controller.encode_path", return_value="fresh"), \
             patch("app.views.dialogs.confirmation_dialog.ConfirmationDialog.show_confirmation") as mock_dlg:
            result = ctrl.should_confirm_extra_moment(None)
        mock_dlg.assert_not_called()
        self.assertTrue(result)

    def test_nag_declined_still_sets_flags(self):
        """Declining the nag still sets both flags — it fires at most once regardless of answer."""
        ctrl, gm = self._ctrl_with_three_moments(gid=1)
        gm.get_active_path.return_value = (99,)
        with patch("app.controllers.chess_log_controller.encode_path", return_value="fresh"), \
             patch("app.views.dialogs.confirmation_dialog.ConfirmationDialog.show_confirmation", return_value=False):
            result = ctrl.should_confirm_extra_moment(None)
        self.assertFalse(result)
        self.assertTrue(ctrl._nag_shown_this_session)
        self.assertTrue(ctrl._nag_shown_by_game.get(id(ctrl._cached_game), False))

    def test_add_moment_no_longer_fires_nag(self):
        ctrl, gm = self._ctrl_with_three_moments()
        gm.get_active_path.return_value = ()
        with patch("app.controllers.chess_log_controller.encode_path", return_value="fresh"), \
             patch("app.views.dialogs.confirmation_dialog.ConfirmationDialog.show_confirmation") as mock_dlg:
            ctrl.add_moment_at_active_path([{"preset": "CLAMP", "cat": "A", "why": ""}])
        mock_dlg.assert_not_called()


class TestSaveAndClear(unittest.TestCase):
    def test_save_persists_to_pgn(self):
        game = make_game()
        ctrl, gm = make_controller(game)
        ctrl._cached_game_id = id(game)
        with patch("app.controllers.chess_log_controller.encode_path", return_value="0"):
            ctrl.add_moment_at_active_path([{"preset": "CLAMP", "cat": "A", "why": "test"}])
        ctrl.save_tags_for_current_game()
        self.assertTrue(ChessLogStorageService.has_chess_log_tags(game))
        loaded = ChessLogStorageService.load_tags(game)
        self.assertEqual(ChessLogStorageService.count_tags(loaded), 1)

    def test_clear_removes_from_pgn(self):
        game = make_game()
        ctrl, gm = make_controller(game)
        ctrl._cached_game_id = id(game)
        with patch("app.controllers.chess_log_controller.encode_path", return_value="0"):
            ctrl.add_moment_at_active_path([{"preset": "CCT", "cat": "C", "why": ""}])
        ctrl.save_tags_for_current_game()
        ctrl.clear_tags_for_current_game()
        self.assertFalse(ChessLogStorageService.has_chess_log_tags(game))
        self.assertEqual(ctrl._cached_paths_data, {})

    def test_metadata_updated_emitted_on_save(self):
        game = make_game()
        ctrl, gm = make_controller(game)
        ctrl._cached_game_id = id(game)
        ctrl.save_tags_for_current_game()
        gm.metadata_updated.emit.assert_called_once()

    def test_metadata_updated_emitted_on_clear(self):
        game = make_game()
        ctrl, gm = make_controller(game)
        ctrl._cached_game_id = id(game)
        ctrl.clear_tags_for_current_game()
        gm.metadata_updated.emit.assert_called_once()

    def test_clear_removes_game_from_dirty_games(self):
        """clear_tags_for_current_game must pop the game from _dirty_games so
        save_all_dirty_games doesn't re-save it with empty data."""
        game = make_game()
        ctrl, gm = make_controller(game)
        ctrl._cached_game_id = id(game)
        gm.active_game = game
        # Simulate the game having been made dirty via ShowTagsDialog.
        ctrl._dirty_games[id(game)] = game
        ctrl.clear_tags_for_current_game()
        self.assertNotIn(id(game), ctrl._dirty_games)

    def test_clear_does_not_appear_in_subsequent_save_all_count(self):
        """After clearing, save_all_dirty_games must not count the cleared game."""
        game = make_game()
        ctrl, gm = make_controller(game)
        ctrl._cached_game_id = id(game)
        gm.active_game = game
        # Make dirty, then clear.
        ctrl._dirty_games[id(game)] = game
        ctrl.clear_tags_for_current_game()
        saved, failed = ctrl.save_all_dirty_games()
        self.assertEqual(saved, 0)
        self.assertEqual(failed, 0)


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
        ctrl._cached_game_id = id(game)
        entry = ChessLogStorageService.make_entry("CLAMP", "M")
        ctrl._cached_paths_data = {"0": [entry]}
        with patch("app.controllers.chess_log_controller.encode_path", return_value="0"):
            result = ctrl.get_entries_at_active_path()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["cat"], "M")

    def test_returns_copy_not_reference(self):
        game = make_game()
        ctrl, _ = make_controller(game)
        ctrl._cached_game_id = id(game)
        ctrl._cached_paths_data = {"0": [ChessLogStorageService.make_entry("CLAMP", "C")]}
        with patch("app.controllers.chess_log_controller.encode_path", return_value="0"):
            result = ctrl.get_entries_at_active_path()
        result.clear()
        self.assertEqual(len(ctrl._cached_paths_data["0"]), 1)


class TestRetagSamePresetReplaces(unittest.TestCase):
    def test_retag_same_preset_replaces_not_appends(self):
        game = make_game()
        ctrl, _ = make_controller(game)
        ctrl._cached_game_id = id(game)
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
        ctrl._cached_game_id = id(game)
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
        ctrl._cached_game_id = id(game)
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
        ctrl._cached_game_id = id(game)
        ctrl._cached_paths_data = {"0": [ChessLogStorageService.make_entry("CCT", "C")]}

        gm.active_game = None
        ctrl._on_active_game_changed(None)
        self.assertEqual(ctrl._cached_paths_data, {})
        self.assertIsNone(ctrl._cached_game_id)


class TestGameHasAnyTags(unittest.TestCase):
    def test_true_when_cache_has_entries(self):
        game = make_game()
        ctrl, _ = make_controller(game)
        ctrl._cached_game_id = id(game)
        ctrl._cached_paths_data = {"0": [ChessLogStorageService.make_entry("CLAMP", "C")]}
        self.assertTrue(ctrl.game_has_any_tags())

    def test_false_when_cache_empty(self):
        game = make_game()
        ctrl, _ = make_controller(game)
        ctrl._cached_game_id = id(game)
        ctrl._cached_paths_data = {}
        self.assertFalse(ctrl.game_has_any_tags())

    def test_false_when_cache_only_has_empty_lists(self):
        game = make_game()
        ctrl, _ = make_controller(game)
        ctrl._cached_game_id = id(game)
        ctrl._cached_paths_data = {"0": [], "0.0": []}
        self.assertFalse(ctrl.game_has_any_tags())


class TestReplaceEntriesAtPath(unittest.TestCase):
    def test_replaces_only_named_preset(self):
        game = make_game()
        ctrl, _ = make_controller(game)
        ctrl._cached_game_id = id(game)
        ctrl._cached_paths_data = {
            "0": [
                ChessLogStorageService.make_entry("CLAMP", "M"),
                ChessLogStorageService.make_entry("CCT", "Threats"),
            ]
        }
        ctrl.replace_entries_at_path(
            "0", "CLAMP", [{"preset": "CLAMP", "cat": "C", "why": "new"}]
        )
        entries = ctrl._cached_paths_data["0"]
        clamp = [e for e in entries if e["preset"] == "CLAMP"]
        cct = [e for e in entries if e["preset"] == "CCT"]
        self.assertEqual(len(clamp), 1)
        self.assertEqual(clamp[0]["cat"], "C")
        self.assertEqual(len(cct), 1)
        self.assertEqual(cct[0]["cat"], "Threats")

    def test_new_path_creates_entry(self):
        game = make_game()
        ctrl, _ = make_controller(game)
        ctrl._cached_game_id = id(game)
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
            ctrl._cached_game_id = id(active_game)
        return ctrl, gm

    # ------------------------------------------------------------------
    # Basic API
    # ------------------------------------------------------------------

    def test_get_tags_for_game_active_reads_from_single_cache(self):
        """For the active game, get_tags_for_game reads the single-game cache
        (resolved copy — not the raw dict reference)."""
        game = make_game(1)
        ctrl, _ = self._make_ctrl(game)
        entry = ChessLogStorageService.make_entry("CLAMP", "C")
        ctrl._cached_paths_data = {"0": [entry]}
        result = ctrl.get_tags_for_game(game)
        # Returns a resolved copy; verify the expected entry is present.
        self.assertIn("0", result)
        self.assertEqual(result["0"][0]["cat"], "C")

    def test_get_tags_for_game_inactive_loads_and_caches(self):
        game_a = make_game(1)
        game_b = make_game(2)
        ChessLogStorageService.store_tags(
            game_b, {"0": [ChessLogStorageService.make_entry("CCT", "C")]}, {}
        )
        ctrl, _ = self._make_ctrl(game_a)
        result = ctrl.get_tags_for_game(game_b)
        self.assertEqual(ChessLogStorageService.count_tags(result), 1)
        self.assertIn(id(game_b), ctrl._multi_cache)

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
        self.assertIn(id(game_b), ctrl._multi_cache)
        self.assertIn("0", ctrl._multi_cache[id(game_b)])
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

        def fake_store(game, data, config, nag_shown=False, **_kwargs):
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
        ctrl._multi_cache[id(game)] = {"0": [ChessLogStorageService.make_entry("CLAMP", "P")]}

        captured = {}

        def fake_store(game, data, config, nag_shown=False, **_kwargs):
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
        self.assertIn("0", ctrl._multi_cache.get(id(game_b), {}))

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
        self.assertNotEqual(ctrl._cached_game_id, id(game_a))

        # Switch back to Game A
        gm.active_game = game_a
        ctrl._on_active_game_changed(game_a)
        self.assertEqual(ctrl._cached_game_id, id(game_a))
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

        def fake_store(game, data, config, nag_shown=False, **_kwargs):
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
        ctrl._cached_game_id = id(game)
        entry = ChessLogStorageService.make_entry("CLAMP", "C", "note", ignore_shallow=True)
        ctrl.replace_entries_at_path("0", "CLAMP", [entry])
        result = ctrl._cached_paths_data["0"]
        self.assertTrue(result[0].get("ignore_shallow"))

    def test_replace_entries_at_path_omits_ignore_shallow_when_false(self):
        game = make_game(1)
        ctrl, _ = make_controller(game)
        ctrl._cached_game_id = id(game)
        entry = ChessLogStorageService.make_entry("CLAMP", "C", "note")
        ctrl.replace_entries_at_path("0", "CLAMP", [entry])
        result = ctrl._cached_paths_data["0"]
        self.assertNotIn("ignore_shallow", result[0])

    def test_replace_entries_at_path_for_game_preserves_ignore_shallow(self):
        game_a = make_game(1)
        game_b = make_game(2)
        ctrl, _ = make_controller(game_a)
        ctrl._cached_game_id = id(game_a)
        entry = ChessLogStorageService.make_entry("CLAMP", "C", "note", ignore_shallow=True)
        ctrl.replace_entries_at_path_for_game(game_b, "0", "CLAMP", [entry])
        result = ctrl._multi_cache[id(game_b)]["0"]
        self.assertTrue(result[0].get("ignore_shallow"))


class TestSaveAllIncludesCurrentGame(unittest.TestCase):
    """Regression: save_all_dirty_games must also save the active game's
    single-game cache even when it wasn't added to _dirty_games
    (add_moment_at_active_path does not add it there)."""

    def _make_ctrl_with_tagged_active_game(self):
        game = make_game(1)
        ctrl, gm = make_controller(game)
        ctrl._cached_game_id = id(game)
        gm.active_game = game
        # Simulate a moment tagged via add_moment_at_active_path (writes to
        # _cached_paths_data but does NOT add to _dirty_games).
        ctrl._cached_paths_data = {
            "0": [ChessLogStorageService.make_entry("3x3", "Why1", "test answer")]
        }
        return ctrl, gm, game

    def test_save_all_saves_active_game_not_in_dirty_games(self):
        ctrl, gm, game = self._make_ctrl_with_tagged_active_game()
        self.assertNotIn(id(game), ctrl._dirty_games)
        saved, failed = ctrl.save_all_dirty_games()
        self.assertEqual(saved, 1)
        self.assertEqual(failed, 0)
        # Tags must now be persisted in the game's PGN.
        loaded = ChessLogStorageService.load_tags(game)
        self.assertIn("0", loaded)
        self.assertEqual(loaded["0"][0]["cat"], "Why1")

    def test_save_all_active_game_already_in_dirty_not_double_saved(self):
        """If the active game is already in _dirty_games, it must be saved exactly once."""
        game = make_game(1)
        ctrl, gm = make_controller(game)
        ctrl._cached_game_id = id(game)
        gm.active_game = game
        ctrl._cached_paths_data = {
            "0": [ChessLogStorageService.make_entry("CLAMP", "C")]
        }
        ctrl._dirty_games[id(game)] = game
        saved, failed = ctrl.save_all_dirty_games()
        self.assertEqual(saved, 1)
        self.assertEqual(failed, 0)

    def test_save_all_skips_active_game_when_no_unsaved_changes(self):
        """Active game with no unsaved changes must NOT be saved (would write empty)."""
        game = make_game(1)
        ctrl, gm = make_controller(game)
        ctrl._cached_game_id = id(game)
        gm.active_game = game
        # Empty cache == no unsaved changes relative to an untagged game.
        ctrl._cached_paths_data = {}
        saved, failed = ctrl.save_all_dirty_games()
        self.assertEqual(saved, 0)
        self.assertEqual(failed, 0)

    def test_save_all_emits_metadata_updated_for_active_game(self):
        ctrl, gm, game = self._make_ctrl_with_tagged_active_game()
        ctrl.save_all_dirty_games()
        gm.metadata_updated.emit.assert_called()


class TestSaveCurrentGameDirtyState(unittest.TestCase):
    """Dirty-state regression tests for save and clear paths."""

    def test_save_current_game_clears_dirty_flag(self):
        """save_tags_for_current_game must pop _dirty_games for the saved game.

        Scenario: game B is dirtied via replace_entries_at_path_for_game while A
        is active (simulating a ShowTagsDialog OK); user switches to B; hits
        Ctrl+Alt+L — after save has_dirty_games() must be False.
        """
        game_a = make_game(1)
        game_b = make_game(2)
        ctrl, gm = make_controller(game_a)
        gm.active_game = game_a
        ctrl._cached_game_id = id(game_a)

        # Dirty game B while A is active (via ShowTagsDialog OK path)
        ctrl.replace_entries_at_path_for_game(
            game_b, "0", "CLAMP", [{"preset": "CLAMP", "cat": "M", "why": "edit-b"}]
        )
        self.assertIn(id(game_b), ctrl._dirty_games)

        # Switch active to B (Rule A promotes from multi-cache)
        gm.active_game = game_b
        ctrl._on_active_game_changed(game_b)

        # Save B via single-game save (Ctrl+Alt+L)
        ctrl.save_tags_for_current_game()

        # After save, no games should remain dirty
        self.assertFalse(ctrl.has_dirty_games())

    def test_clear_active_game_leaves_inactive_game_dirty(self):
        """Clearing the active game must not disturb an inactive game's dirty state."""
        game_a = make_game(1)
        game_b = make_game(2)
        ctrl, gm = make_controller(game_a)
        gm.active_game = game_a
        ctrl._cached_game_id = id(game_a)

        # Tag A while A is active, then switch to B and tag B
        ctrl.replace_entries_at_path_for_game(
            game_a, "0", "CLAMP", [{"preset": "CLAMP", "cat": "M", "why": "a-tag"}]
        )
        gm.active_game = game_b
        ctrl._on_active_game_changed(game_b)
        ctrl.replace_entries_at_path_for_game(
            game_b, "0", "CCT", [{"preset": "CCT", "cat": "C", "why": "b-tag"}]
        )

        # Switch back to A and clear it
        gm.active_game = game_a
        ctrl._on_active_game_changed(game_a)
        ctrl.clear_tags_for_current_game()

        # A is clean
        self.assertNotIn(id(game_a), ctrl._dirty_games)
        self.assertEqual(ctrl._cached_paths_data, {})
        # B is still dirty with its tag intact
        self.assertIn(id(game_b), ctrl._dirty_games)
        b_data = ctrl._multi_cache.get(id(game_b), {})
        self.assertIn("0", b_data)
        self.assertEqual(b_data["0"][0]["cat"], "C")

    def test_repeated_save_all_cycles_stay_consistent(self):
        """Two successive tag → save-all cycles must each leave a clean dirty state."""
        game = make_game(1)
        ctrl, gm = make_controller(game)
        ctrl._cached_game_id = id(game)
        gm.active_game = game

        # First cycle
        ctrl.replace_entries_at_path_for_game(
            game, "0", "CLAMP", [{"preset": "CLAMP", "cat": "M", "why": "first"}]
        )
        saved, failed = ctrl.save_all_dirty_games()
        self.assertEqual(saved, 1)
        self.assertFalse(ctrl.has_dirty_games())

        # Second cycle — a fresh tag on a different path
        ctrl.replace_entries_at_path_for_game(
            game, "1", "CLAMP", [{"preset": "CLAMP", "cat": "C", "why": "second"}]
        )
        saved, failed = ctrl.save_all_dirty_games()
        self.assertEqual(saved, 1)
        self.assertFalse(ctrl.has_dirty_games())

        loaded = ChessLogStorageService.load_tags(game)
        self.assertIn("0", loaded)
        self.assertIn("1", loaded)

    def test_clear_writes_to_pgn_immediately(self):
        """clear_tags_for_current_game writes through to the PGN at once;
        switching away and back does NOT restore the pre-clear data from disk."""
        game_a = make_game(1)
        game_b = make_game(2)
        ctrl, gm = make_controller(game_a)
        ctrl._cached_game_id = id(game_a)
        gm.active_game = game_a

        # Tag A and persist to disk
        ctrl._cached_paths_data = {"0": [ChessLogStorageService.make_entry("CLAMP", "M")]}
        ctrl.save_tags_for_current_game()
        self.assertTrue(ChessLogStorageService.has_chess_log_tags(game_a))

        # Clear A — writes through to PGN immediately, no separate save needed
        ctrl.clear_tags_for_current_game()
        self.assertFalse(ChessLogStorageService.has_chess_log_tags(game_a))

        # Switch away and back — reload from disk must still show empty
        gm.active_game = game_b
        ctrl._on_active_game_changed(game_b)
        gm.active_game = game_a
        ctrl._on_active_game_changed(game_a)
        self.assertEqual(ctrl._cached_paths_data, {})


class TestSwitchAndSaveAllIntegration(unittest.TestCase):
    """Scenario 2: tag A via add_moment → switch to B → save-all → A persisted."""

    def test_clear_tag_switch_save_all_persists(self):
        """Regression: clear → tag → switch → save-all must save the new moment.

        save_all_dirty_games previously missed this because add_moment_at_active_path
        does not write _dirty_games, and the special active-game check only applies to
        the *currently* active game.  Rule B now marks the outgoing game dirty on every
        game switch that flushes a non-empty cache.
        """
        game_a = make_game(1)
        game_b = make_game(2)
        ctrl, gm = make_controller(game_a)
        ctrl._cached_game_id = id(game_a)
        gm.active_game = game_a

        # Seed PGN with existing data so clear actually removes something
        ctrl._cached_paths_data = {"0": [ChessLogStorageService.make_entry("CLAMP", "M")]}
        ctrl.save_tags_for_current_game()

        # Clear A (writes through, removes from _dirty_games)
        ctrl.clear_tags_for_current_game()
        self.assertFalse(ctrl.has_dirty_games())

        # Tag a fresh moment on A — only _cached_paths_data is touched
        with patch("app.controllers.chess_log_controller.encode_path", return_value="1"):
            ctrl.add_moment_at_active_path([{"preset": "CLAMP", "cat": "C", "why": "after-clear"}])

        # Switch to B — Rule B should flush A to multi_cache AND mark A dirty
        gm.active_game = game_b
        ctrl._on_active_game_changed(game_b)
        self.assertIn(id(game_a), ctrl._dirty_games)

        # Save All while B is active — must reach A via _dirty_games
        saved, failed = ctrl.save_all_dirty_games()
        self.assertEqual(saved, 1)
        self.assertEqual(failed, 0)

        loaded = ChessLogStorageService.load_tags(game_a)
        self.assertIn("1", loaded)
        self.assertEqual(loaded["1"][0]["why"], "after-clear")

    def test_tag_switch_save_all_persists(self):
        """tag A → switch to B (stay on B) → save-all → A's moment persisted."""
        game_a = make_game(1)
        game_b = make_game(2)
        ctrl, gm = make_controller(game_a)
        ctrl._cached_game_id = id(game_a)
        gm.active_game = game_a

        with patch("app.controllers.chess_log_controller.encode_path", return_value="0"):
            ctrl.add_moment_at_active_path([{"preset": "CLAMP", "cat": "A", "why": "no-return"}])

        gm.active_game = game_b
        ctrl._on_active_game_changed(game_b)
        self.assertIn(id(game_a), ctrl._dirty_games)

        saved, failed = ctrl.save_all_dirty_games()
        self.assertEqual(saved, 1)

        loaded = ChessLogStorageService.load_tags(game_a)
        self.assertIn("0", loaded)
        self.assertEqual(loaded["0"][0]["why"], "no-return")

    def test_tag_switch_back_save_all_persists(self):
        game_a = make_game(1)
        game_b = make_game(2)
        ctrl, gm = make_controller(game_a)
        ctrl._cached_game_id = id(game_a)
        gm.active_game = game_a

        # Tag A via the UI path — writes to _cached_paths_data only (not _dirty_games)
        with patch("app.controllers.chess_log_controller.encode_path", return_value="0"):
            ctrl.add_moment_at_active_path([{"preset": "CLAMP", "cat": "A", "why": "switch test"}])

        # Switch to B — Rule B flushes A's cache to multi_cache
        gm.active_game = game_b
        ctrl._on_active_game_changed(game_b)

        # Switch back to A — Rule A promotes A's data from multi_cache
        gm.active_game = game_a
        ctrl._on_active_game_changed(game_a)

        # Save All — must include A's moment via has_unsaved_changes() check
        saved, failed = ctrl.save_all_dirty_games()
        self.assertEqual(saved, 1)
        self.assertEqual(failed, 0)

        loaded = ChessLogStorageService.load_tags(game_a)
        self.assertIn("0", loaded)
        self.assertEqual(loaded["0"][0]["why"], "switch test")


class TestShallowFlagPersistence(unittest.TestCase):
    """is_shallow and ignore_shallow flags must survive save_all_dirty_games."""

    def test_is_shallow_flag_persists_via_save_all(self):
        game = make_game(1)
        ctrl, gm = make_controller(game)
        ctrl._cached_game_id = id(game)
        gm.active_game = game

        entry = ChessLogStorageService.make_entry("CLAMP", "C", "note", is_shallow=True)
        ctrl.replace_entries_at_path_for_game(game, "0", "CLAMP", [entry])
        ctrl.save_all_dirty_games()

        loaded = ChessLogStorageService.load_tags(game)
        self.assertTrue(loaded["0"][0].get("is_shallow"))

    def test_ignore_shallow_flag_persists_via_save_all(self):
        game = make_game(1)
        ctrl, gm = make_controller(game)
        ctrl._cached_game_id = id(game)
        gm.active_game = game

        entry = ChessLogStorageService.make_entry("CLAMP", "C", "note", ignore_shallow=True)
        ctrl.replace_entries_at_path_for_game(game, "0", "CLAMP", [entry])
        ctrl.save_all_dirty_games()

        loaded = ChessLogStorageService.load_tags(game)
        self.assertTrue(loaded["0"][0].get("ignore_shallow"))

    def test_shallow_flags_across_active_and_inactive_games(self):
        """Shallow flags in both active and inactive games must both persist via save_all."""
        game_a = make_game(1)
        game_b = make_game(2)
        ctrl, gm = make_controller(game_a)
        ctrl._cached_game_id = id(game_a)
        gm.active_game = game_a

        entry_a = ChessLogStorageService.make_entry("CLAMP", "M", "active-note", is_shallow=True)
        ctrl.replace_entries_at_path_for_game(game_a, "0", "CLAMP", [entry_a])

        entry_b = ChessLogStorageService.make_entry("CCT", "Checks", "inactive-note", ignore_shallow=True)
        ctrl.replace_entries_at_path_for_game(game_b, "0", "CCT", [entry_b])

        saved, failed = ctrl.save_all_dirty_games()
        self.assertEqual(saved, 2)
        self.assertEqual(failed, 0)

        loaded_a = ChessLogStorageService.load_tags(game_a)
        loaded_b = ChessLogStorageService.load_tags(game_b)
        self.assertTrue(loaded_a["0"][0].get("is_shallow"))
        self.assertTrue(loaded_b["0"][0].get("ignore_shallow"))


class TestNagRoundTrip(unittest.TestCase):
    """Nag flag set in memory → save → fresh controller reloads → flag rehydrated."""

    def test_nag_flag_survives_save_and_reload(self):
        game = make_game(1)
        ctrl, gm = make_controller(game)
        ctrl._cached_game_id = id(game)
        gm.active_game = game

        # Three moments to put us at the threshold
        ctrl._cached_paths_data = {
            "0":     [ChessLogStorageService.make_entry("CLAMP", "M")],
            "0.0":   [ChessLogStorageService.make_entry("CLAMP", "L")],
            "0.0.0": [ChessLogStorageService.make_entry("CCT",   "C")],
        }

        # Trigger the nag for a fourth new path — sets _nag_shown_by_game[id(game)]
        gm.get_active_path.return_value = (99,)
        with patch("app.controllers.chess_log_controller.encode_path", return_value="fresh"), \
             patch("app.views.dialogs.confirmation_dialog.ConfirmationDialog.show_confirmation",
                   return_value=True):
            ctrl.should_confirm_extra_moment(None)
        self.assertTrue(ctrl._nag_shown_by_game.get(id(game)))

        # Save — nag_shown flag rides along with the PGN payload
        ctrl.save_tags_for_current_game()

        # Fresh controller — simulates a new session (session-level flag reset)
        ctrl2, gm2 = make_controller(game)
        gm2.active_game = game
        ctrl2._on_active_game_changed(game)  # triggers _load_into_cache

        # Per-game nag flag must be rehydrated from disk
        self.assertTrue(ctrl2._nag_shown_by_game.get(id(game), False))


class TestIdentityKeyingCrossDatabase(unittest.TestCase):
    """Verify that identity-keyed caches isolate games from different databases
    that share the same sequential game_number."""

    def test_two_games_with_same_game_number_cache_independently(self):
        """Two GameData objects with game_number=5 from different databases
        must occupy separate cache slots and never return each other's tags."""
        pgn_a = (
            '[Event "DB-A"]\n[Site "?"]\n[Date "2026.01.01"]\n'
            '[Round "?"]\n[White "A"]\n[Black "B"]\n[Result "*"]\n\n'
            '1. e4 e5 2. Nf3 Nc6 *\n'
        )
        pgn_b = (
            '[Event "DB-B"]\n[Site "?"]\n[Date "2026.02.01"]\n'
            '[Round "?"]\n[White "C"]\n[Black "D"]\n[Result "*"]\n\n'
            '1. e4 e5 2. Nf3 Nc6 *\n'
        )
        game_a = GameData(game_number=5, pgn=pgn_a)
        game_b = GameData(game_number=5, pgn=pgn_b)
        self.assertEqual(game_a.game_number, game_b.game_number)  # same integer key
        self.assertIsNot(game_a, game_b)  # but different objects

        ctrl, _ = make_controller()

        # Tag game_a via replace_entries_at_path_for_game (inactive game path)
        ctrl.replace_entries_at_path_for_game(
            game_a, "0", "CLAMP", [{"preset": "CLAMP", "cat": "M", "why": "a-tag"}]
        )
        # Tag game_b with a different category
        ctrl.replace_entries_at_path_for_game(
            game_b, "0", "CLAMP", [{"preset": "CLAMP", "cat": "P", "why": "b-tag"}]
        )

        # Two distinct slots must exist
        self.assertEqual(len(ctrl._multi_cache), 2)
        self.assertIn(id(game_a), ctrl._multi_cache)
        self.assertIn(id(game_b), ctrl._multi_cache)

        # Each slot must contain its own data, not the other's
        tags_a = ctrl.get_tags_for_game(game_a)
        tags_b = ctrl.get_tags_for_game(game_b)
        self.assertEqual(tags_a["0"][0]["cat"], "M")
        self.assertEqual(tags_b["0"][0]["cat"], "P")

    def test_db_switch_resets_active_cache_pointers(self):
        """After switch, active-game pointers must be cleared so a new active
        game can be loaded cleanly.  (Dirty entries are preserved — see
        TestDbSwitchPreservesDirtyEdits for that contract.)"""
        game = make_game(1)
        ctrl, gm = make_controller(game)
        ctrl._cached_game_id = id(game)
        gm.active_game = game
        ctrl._cached_paths_data = {}  # untouched active game — nothing to flush

        ctrl._on_active_database_changed(None)

        self.assertEqual(ctrl._cached_paths_data, {})
        self.assertIsNone(ctrl._cached_game_id)
        self.assertIsNone(ctrl._cached_game)

    def test_identity_keyed_dirty_games_write_to_right_game(self):
        """save_all_dirty_games must write game_a's data to game_a and game_b's
        data to game_b even when both have game_number=5."""
        pgn_a = (
            '[Event "DB-A"]\n[Site "?"]\n[Date "2026.01.01"]\n'
            '[Round "?"]\n[White "A"]\n[Black "B"]\n[Result "*"]\n\n'
            '1. e4 e5 2. Nf3 Nc6 *\n'
        )
        pgn_b = (
            '[Event "DB-B"]\n[Site "?"]\n[Date "2026.02.01"]\n'
            '[Round "?"]\n[White "C"]\n[Black "D"]\n[Result "*"]\n\n'
            '1. e4 e5 2. Nf3 Nc6 *\n'
        )
        game_a = GameData(game_number=5, pgn=pgn_a)
        game_b = GameData(game_number=5, pgn=pgn_b)

        ctrl, _ = make_controller()
        ctrl.replace_entries_at_path_for_game(
            game_a, "0", "CLAMP", [{"preset": "CLAMP", "cat": "M", "why": "a-data"}]
        )
        ctrl.replace_entries_at_path_for_game(
            game_b, "0", "CLAMP", [{"preset": "CLAMP", "cat": "P", "why": "b-data"}]
        )

        written = {}

        def fake_store(game, data, config, nag_shown=False, **_kwargs):
            written[id(game)] = {
                pk: [e["why"] for e in entries]
                for pk, entries in data.items()
            }
            return True

        with patch(
            "app.controllers.chess_log_controller.ChessLogStorageService.store_tags",
            side_effect=fake_store,
        ):
            saved, failed = ctrl.save_all_dirty_games()

        self.assertEqual(saved, 2)
        self.assertEqual(failed, 0)
        self.assertIn("a-data", written.get(id(game_a), {}).get("0", []))
        self.assertIn("b-data", written.get(id(game_b), {}).get("0", []))
        # Cross-contamination check: game_a must not have b-data and vice versa
        self.assertNotIn("b-data", written.get(id(game_a), {}).get("0", []))
        self.assertNotIn("a-data", written.get(id(game_b), {}).get("0", []))


def _make_fake_panel_model(db_models):
    pm = MagicMock()
    pm.get_all_database_models.return_value = list(db_models)
    pm.active_database_changed = MagicMock()
    pm.active_database_changed.connect = MagicMock()
    pm.active_database_changed.disconnect = MagicMock()
    return pm


def _make_fake_db_model(games):
    db = MagicMock()
    db.get_all_games.return_value = list(games)
    return db


def _make_fake_db_controller(panel_model):
    dc = MagicMock()
    dc.get_panel_model.return_value = panel_model
    dc.find_database_model_for_game.return_value = None
    return dc


def make_controller_with_dbs(active_game, dbs_games, active_path=()):
    """dbs_games: list of lists of GameData (one list per database)."""
    gm = make_game_model_mock(active_game, active_path)
    gc = make_game_controller_mock(gm)
    db_models = [_make_fake_db_model(gs) for gs in dbs_games]
    panel_model = _make_fake_panel_model(db_models)
    dc = _make_fake_db_controller(panel_model)
    ctrl = ChessLogController({}, gc, database_controller=dc)
    if active_game is not None:
        ctrl._cached_game = active_game
        ctrl._cached_game_id = id(active_game)
    return ctrl, gm, dc


class TestDbSwitchPreservesDirtyEdits(unittest.TestCase):
    """Phase 2 — _on_active_database_changed must preserve unsaved Chess Log
    edits.  Phase 1 cleared _dirty_games unconditionally on switch; the fix
    flushes the outgoing active game's real edits into _dirty_games/_multi_cache
    and only prunes entries belonging to games no longer in any open DB."""

    def test_db_switch_preserves_dirty_edits_from_outgoing_active_game(self):
        game_a = make_game(1)
        game_b = make_game(2)
        ctrl, gm, _dc = make_controller_with_dbs(game_a, [[game_a], [game_b]])
        gm.active_game = game_a
        ctrl.add_moment_at_active_path([{"preset": "CLAMP", "cat": "L", "why": "edit"}])

        ctrl._on_active_database_changed(None)

        self.assertIn(id(game_a), ctrl._dirty_games)
        self.assertIn(id(game_a), ctrl._multi_cache)
        self.assertEqual(ctrl._multi_cache[id(game_a)][""][0]["why"], "edit")

        captured = {}

        def fake_store(game, data, config, nag_shown=False, **_kwargs):
            captured[id(game)] = {pk: [e["why"] for e in es] for pk, es in data.items()}
            return True

        with patch("app.controllers.chess_log_controller.ChessLogStorageService.store_tags",
                   side_effect=fake_store):
            saved, failed = ctrl.save_all_dirty_games()

        self.assertEqual((saved, failed), (1, 0))
        self.assertIn("edit", captured.get(id(game_a), {}).get("", []))

    def test_db_switch_preserves_dirty_edits_from_inactive_game_tags_report(self):
        active = make_game(1)
        game_a7 = make_game(7)
        game_b = make_game(99)
        ctrl, gm, _dc = make_controller_with_dbs(active, [[active, game_a7], [game_b]])
        gm.active_game = active
        ctrl.replace_entries_at_path_for_game(
            game_a7, "", "CLAMP", [{"preset": "CLAMP", "cat": "M", "why": "tags-report-edit"}]
        )
        self.assertIn(id(game_a7), ctrl._dirty_games)
        self.assertIn(id(game_a7), ctrl._multi_cache)

        ctrl._on_active_database_changed(None)

        self.assertIn(id(game_a7), ctrl._dirty_games)
        self.assertIn(id(game_a7), ctrl._multi_cache)

    def test_db_switch_prunes_non_dirty_multi_cache_entries(self):
        active = make_game(1)
        peek_game = make_game(2)
        ctrl, gm, _dc = make_controller_with_dbs(active, [[active, peek_game]])
        gm.active_game = active
        # Peek at an inactive game (populates _multi_cache without dirtying)
        _ = ctrl.get_tags_for_game(peek_game)
        self.assertIn(id(peek_game), ctrl._multi_cache)
        self.assertNotIn(id(peek_game), ctrl._dirty_games)

        ctrl._on_active_database_changed(None)

        self.assertNotIn(id(peek_game), ctrl._multi_cache)

    def test_db_switch_untouched_active_game_not_marked_dirty(self):
        game = make_game(1)
        ctrl, gm, _dc = make_controller_with_dbs(game, [[game]])
        gm.active_game = game
        # No edits — _cached_paths_data stays matching the on-disk tag (both empty)
        ctrl._on_active_database_changed(None)
        self.assertNotIn(id(game), ctrl._dirty_games)
        self.assertNotIn(id(game), ctrl._multi_cache)

    def test_db_switch_last_moment_deletion_survives_and_saves(self):
        """Game has 1 moment on disk; delete via replace_entries_at_path on the
        active cache (does NOT dirty-mark); switch DB; verify dirty + save
        writes a tag-less PGN."""
        game = make_game(1)
        # Pre-seed on-disk tag with one CLAMP moment at path ""
        ChessLogStorageService.store_tags(
            game, {"": [ChessLogStorageService.make_entry("CLAMP", "C", "orig")]}, {}
        )
        ctrl, gm, _dc = make_controller_with_dbs(game, [[game]])
        gm.active_game = game
        # Force-load from disk so _cached_paths_data reflects the stored moment
        ctrl._load_into_cache(game)
        self.assertEqual(ChessLogStorageService.count_tags(ctrl._cached_paths_data), 1)
        # Delete the moment via the active-cache replace (NOT dirty-marking)
        ctrl.replace_entries_at_path("", "CLAMP", [])
        self.assertEqual(ctrl._cached_paths_data, {})
        self.assertNotIn(id(game), ctrl._dirty_games)  # replace_entries_at_path doesn't dirty-mark

        ctrl._on_active_database_changed(None)

        # Flush decision compared against disk (which had 1 moment) → dirty
        self.assertIn(id(game), ctrl._dirty_games)
        self.assertIn(id(game), ctrl._multi_cache)
        self.assertEqual(ctrl._multi_cache[id(game)], {})

        captured = {}

        def fake_store(game_, data, config, nag_shown=False, **_kwargs):
            captured["data"] = dict(data)
            return True

        with patch("app.controllers.chess_log_controller.ChessLogStorageService.store_tags",
                   side_effect=fake_store):
            saved, failed = ctrl.save_all_dirty_games()

        self.assertEqual((saved, failed), (1, 0))
        self.assertEqual(captured["data"], {})  # tag payload empty — no moments

    def test_db_switch_then_back_then_save_persists_edits(self):
        game_a = make_game(1)
        game_b = make_game(2)
        ctrl, gm, _dc = make_controller_with_dbs(game_a, [[game_a], [game_b]])
        gm.active_game = game_a
        ctrl.add_moment_at_active_path([{"preset": "CLAMP", "cat": "A", "why": "edit-a"}])

        # Switch away (DB-B)
        ctrl._on_active_database_changed(None)
        # Switch back (DB-A) — simulate the user clicking game_a in the newly-active tab
        gm.active_game = game_a
        ctrl._on_active_game_changed(game_a)

        self.assertEqual(ctrl._cached_game_id, id(game_a))
        self.assertEqual(ctrl._cached_paths_data[""][0]["why"], "edit-a")

        captured = {}

        def fake_store(game_, data, config, nag_shown=False, **_kwargs):
            captured[id(game_)] = {pk: [e["why"] for e in es] for pk, es in data.items()}
            return True

        with patch("app.controllers.chess_log_controller.ChessLogStorageService.store_tags",
                   side_effect=fake_store):
            ctrl.save_tags_for_current_game()

        self.assertIn("edit-a", captured.get(id(game_a), {}).get("", []))

    def test_save_all_dirty_after_cross_db_edits_writes_each_to_own_pgn(self):
        game_a3 = make_game(3)
        game_b5 = make_game(5)
        other = make_game(1)
        ctrl, gm, _dc = make_controller_with_dbs(other, [[other, game_a3], [game_b5]])
        gm.active_game = other
        ctrl.replace_entries_at_path_for_game(
            game_a3, "", "CLAMP", [{"preset": "CLAMP", "cat": "C", "why": "a3-edit"}]
        )
        ctrl.replace_entries_at_path_for_game(
            game_b5, "", "CCT", [{"preset": "CCT", "cat": "Threats", "why": "b5-edit"}]
        )

        ctrl._on_active_database_changed(None)

        captured = {}

        def fake_store(game_, data, config, nag_shown=False, **_kwargs):
            captured[id(game_)] = {pk: [e["why"] for e in es] for pk, es in data.items()}
            return True

        with patch("app.controllers.chess_log_controller.ChessLogStorageService.store_tags",
                   side_effect=fake_store):
            saved, failed = ctrl.save_all_dirty_games()

        self.assertEqual((saved, failed), (2, 0))
        self.assertIn("a3-edit", captured.get(id(game_a3), {}).get("", []))
        self.assertIn("b5-edit", captured.get(id(game_b5), {}).get("", []))
        self.assertNotIn("b5-edit", captured.get(id(game_a3), {}).get("", []))
        self.assertNotIn("a3-edit", captured.get(id(game_b5), {}).get("", []))

    def test_reload_drops_dirty_entries_for_games_no_longer_open(self):
        game_a3 = make_game(3)
        game_b5 = make_game(5)
        other = make_game(1)
        db_a_games = [other, game_a3]
        db_b_games = [game_b5]
        ctrl, gm, dc = make_controller_with_dbs(other, [db_a_games, db_b_games])
        gm.active_game = other
        ctrl.replace_entries_at_path_for_game(
            game_a3, "", "CLAMP", [{"preset": "CLAMP", "cat": "C", "why": "a3"}]
        )
        ctrl.replace_entries_at_path_for_game(
            game_b5, "", "CCT", [{"preset": "CCT", "cat": "Threats", "why": "b5"}]
        )
        self.assertIn(id(game_a3), ctrl._dirty_games)
        self.assertIn(id(game_b5), ctrl._dirty_games)

        # Simulate reload of DB-A: replace game list with fresh GameData objects.
        new_other = make_game(1)
        new_a3 = make_game(3)
        panel_model = dc.get_panel_model()
        panel_model.get_all_database_models.return_value[0].get_all_games.return_value = [new_other, new_a3]

        # active_game_changed(None) fires on reload — same prune path.
        gm.active_game = None
        ctrl._on_active_game_changed(None)

        self.assertNotIn(id(game_a3), ctrl._dirty_games)
        self.assertIn(id(game_b5), ctrl._dirty_games)

    def test_chess_log_edit_marks_database_unsaved(self):
        game = make_game(1)
        ctrl, gm, dc = make_controller_with_dbs(game, [[game]])
        gm.active_game = game
        fake_db_model = MagicMock()
        dc.find_database_model_for_game.return_value = fake_db_model

        ctrl.add_moment_at_active_path([{"preset": "CLAMP", "cat": "A", "why": "x"}])
        ctrl.replace_entries_at_path("", "CLAMP", [
            ChessLogStorageService.make_entry("CLAMP", "B", "y")
        ])
        other = make_game(2)
        ctrl.replace_entries_at_path_for_game(other, "", "CLAMP", [
            {"preset": "CLAMP", "cat": "C", "why": "z"}
        ])

        marked_games = [c.args[0] for c in dc.mark_database_unsaved.call_args_list]
        self.assertEqual(dc.mark_database_unsaved.call_count, 3)
        # All three calls should pass the correct game
        self.assertIs(marked_games[0], fake_db_model)
        self.assertIs(marked_games[1], fake_db_model)
        self.assertIs(marked_games[2], fake_db_model)

    def test_edit_preserved_when_active_game_becomes_none(self):
        """Amendment 21: active game becomes None (close / clipboard clear) →
        the outgoing-game flush must still fire.  Covers the regression where
        has_unsaved_changes() would read active_game=None and skip the flush."""
        game = make_game(1)
        ctrl, gm, _dc = make_controller_with_dbs(game, [[game]])
        gm.active_game = game
        ctrl.add_moment_at_active_path([{"preset": "CLAMP", "cat": "A", "why": "preserved"}])

        # Simulate close/clear: game model's active_game goes to None BEFORE
        # the handler fires.  If the flush decision used has_unsaved_changes()
        # (which reads game model.active_game), the edit would be lost.
        gm.active_game = None
        ctrl._on_active_game_changed(None)

        self.assertIn(id(game), ctrl._dirty_games)
        self.assertIn(id(game), ctrl._multi_cache)
        self.assertEqual(ctrl._multi_cache[id(game)][""][0]["why"], "preserved")

        captured = {}

        def fake_store(game_, data, config, nag_shown=False, **_kwargs):
            captured[id(game_)] = {pk: [e["why"] for e in es] for pk, es in data.items()}
            return True

        with patch("app.controllers.chess_log_controller.ChessLogStorageService.store_tags",
                   side_effect=fake_store):
            saved, failed = ctrl.save_all_dirty_games()

        self.assertEqual((saved, failed), (1, 0))
        self.assertIn("preserved", captured.get(id(game), {}).get("", []))


class TestSaveOrphanGuard(unittest.TestCase):
    """Commit 2 — save-side orphan guard wired through production save paths.

    Tests 10-13 from the Phase 2 plan.
    """

    def _make_ctrl_with_game(self):
        """Return a controller with an active game fully loaded into cache."""
        game = make_game()
        ctrl, gm = make_controller(game)
        gm.active_game = game
        ctrl._load_into_cache(game)
        return ctrl, gm, game

    def test_save_tags_for_current_game_passes_original_paths(self):
        """save_tags_for_current_game must pass _cached_original_paths[gid] as
        original_paths= to store_tags so the orphan guard is active."""
        ctrl, gm, game = self._make_ctrl_with_game()
        # Inject a recognisable sentinel snapshot so we can verify identity.
        sentinel = {"sentinel": [ChessLogStorageService.make_entry("CLAMP", "M")]}
        ctrl._cached_original_paths[id(game)] = sentinel

        captured = {}

        def fake_store(game_, data, config, nag_shown=False, original_paths=None):
            captured["original_paths"] = original_paths
            return True

        with patch("app.controllers.chess_log_controller.ChessLogStorageService.store_tags",
                   side_effect=fake_store):
            ctrl.save_tags_for_current_game()

        self.assertIs(captured["original_paths"], sentinel)

    def test_save_refuses_new_orphan_via_production_path(self):
        """An unresolvable path_key injected into the in-memory cache after load
        must not reach the PGN.  LoggingService.error must fire exactly once."""
        ctrl, gm, game = self._make_ctrl_with_game()
        orphan_key = "99999"
        ctrl._cached_paths_data[orphan_key] = [ChessLogStorageService.make_entry("CLAMP", "M")]

        with patch("app.services.chess_log_storage_service.LoggingService") as mock_ls:
            mock_logger = MagicMock()
            mock_ls.get_instance.return_value = mock_logger
            ctrl.save_tags_for_current_game()

        loaded = ChessLogStorageService.load_tags(game)
        self.assertNotIn(orphan_key, loaded)
        mock_logger.error.assert_called_once()

    def test_save_refuses_new_orphan_remains_refused_on_second_save(self):
        """The orphan guard must fire on every save.

        After a successful save, _cached_original_paths is refreshed from the
        on-disk snapshot (which never received the refused key), so the refused
        key is still treated as 'new' on the next save call.
        """
        ctrl, gm, game = self._make_ctrl_with_game()
        orphan_key = "99999"
        ctrl._cached_paths_data[orphan_key] = [ChessLogStorageService.make_entry("CLAMP", "M")]

        with patch("app.services.chess_log_storage_service.LoggingService") as mock_ls:
            mock_logger = MagicMock()
            mock_ls.get_instance.return_value = mock_logger
            ctrl.save_tags_for_current_game()   # first save
            ctrl.save_tags_for_current_game()   # second save

        loaded = ChessLogStorageService.load_tags(game)
        self.assertNotIn(orphan_key, loaded)
        self.assertEqual(mock_logger.error.call_count, 2)

    def test_save_preserves_preexisting_on_disk_orphan(self):
        """An orphan path_key already present in the PGN must pass through on save
        (byte-identical round-trip), even when a new resolvable moment is added."""
        game = make_game()
        orphan_key = "99999"
        # Pre-seed the PGN with an orphan key — bypass guard with no original_paths.
        ChessLogStorageService.store_tags(
            game,
            {orphan_key: [ChessLogStorageService.make_entry("CLAMP", "M", "orphan")]},
            {},
        )

        ctrl, gm = make_controller(game)
        gm.active_game = game
        ctrl._load_into_cache(game)   # _cached_original_paths[gid] = {orphan_key: [...]}

        # Add a new resolvable moment at path "0" (first move — exists in MINIMAL_PGN).
        with patch("app.controllers.chess_log_controller.encode_path", return_value="0"):
            ctrl.add_moment_at_active_path([{"preset": "CLAMP", "cat": "C", "why": "new"}])

        ctrl.save_tags_for_current_game()

        loaded = ChessLogStorageService.load_tags(game)
        self.assertIn(orphan_key, loaded)
        self.assertIn("0", loaded)
        self.assertEqual(loaded["0"][0]["why"], "new")


# ---------------------------------------------------------------------------
# Resolved view — orphans excluded from feature code (tests 14–16, amendments 22–23)
# ---------------------------------------------------------------------------

class TestResolvedView(unittest.TestCase):
    """_resolved_view filters orphan path_keys; get_tags_for_current_game returns the
    filtered copy; memoization prevents redundant PGN re-parsing."""

    def _make_ctrl_with_orphan_game(self):
        """Return (ctrl, game) where game has one resolvable + one orphan path key."""
        game = make_game()
        orphan_key = "99999"
        resolvable_key = "0"
        ChessLogStorageService.store_tags(game, {
            resolvable_key: [ChessLogStorageService.make_entry("CLAMP", "C", "real note")],
            orphan_key: [ChessLogStorageService.make_entry("CLAMP", "M", "ghost note")],
        })
        ctrl, gm = make_controller(game)
        gm.active_game = game
        ctrl._load_into_cache(game)
        return ctrl, game

    def test_get_tags_for_current_game_returns_resolved_view(self):
        """get_tags_for_current_game must exclude orphan path_keys.

        has_unsaved_changes() must still return False immediately after load —
        both sides of the full-dict comparison include the orphan, so cache==disk.
        """
        ctrl, game = self._make_ctrl_with_orphan_game()
        result = ctrl.get_tags_for_current_game()
        self.assertIn("0", result)
        self.assertNotIn("99999", result)
        # Full-dict comparison: cached == stored (both include the orphan)
        self.assertFalse(ctrl.has_unsaved_changes())

    def test_should_confirm_extra_moment_ignores_on_disk_orphans(self):
        """On-disk orphans must not count toward the 3-moment nag threshold.

        2 resolvable + 2 orphan moments in the PGN.  Tagging a 3rd resolvable
        path must not trigger the nag (resolved count = 2 < 3).
        """
        game = make_game()
        ChessLogStorageService.store_tags(game, {
            "0":     [ChessLogStorageService.make_entry("CLAMP", "C", "note1")],
            "0.0":   [ChessLogStorageService.make_entry("CLAMP", "L", "note2")],
            "99997": [ChessLogStorageService.make_entry("CLAMP", "A", "orphan1")],
            "99998": [ChessLogStorageService.make_entry("CLAMP", "M", "orphan2")],
        })
        # active path is "0.0.0" — a new, not-yet-tagged move
        ctrl, gm = make_controller(game, active_path=(0, 0, 0))
        gm.active_game = game
        ctrl._load_into_cache(game)

        with patch.object(ctrl, "_confirm_extra_moment", return_value=True) as mock_nag:
            result = ctrl.should_confirm_extra_moment()
        # Resolved count = 2 < 3, so no nag should fire; confirm returns True
        self.assertTrue(result)
        mock_nag.assert_not_called()

    def test_resolved_view_memoized_across_calls(self):
        """Calling get_tags_for_current_game 100× must parse the PGN exactly once.

        After add_moment_at_active_path bumps the version, the next call parses
        the PGN exactly once more (total 2 times).
        """
        import chess.pgn as _chess_pgn

        game = make_game()
        ChessLogStorageService.store_tags(game, {
            "0": [ChessLogStorageService.make_entry("CLAMP", "C", "memo test")],
        })
        ctrl, gm = make_controller(game, active_path=(0,))
        gm.active_game = game
        ctrl._load_into_cache(game)

        with patch.object(_chess_pgn, "read_game", wraps=_chess_pgn.read_game) as spy:
            for _ in range(100):
                ctrl.get_tags_for_current_game()
            self.assertEqual(spy.call_count, 1, "PGN parsed more than once despite stable version")

            # Bump version via add_moment_at_active_path
            with patch("app.controllers.chess_log_controller.encode_path", return_value="0.0"):
                ctrl.add_moment_at_active_path([{"preset": "CLAMP", "cat": "L", "why": "new"}])

            # Exactly one more parse
            ctrl.get_tags_for_current_game()
            self.assertEqual(spy.call_count, 2, "Cache not invalidated after version bump")

    def test_resolved_view_invalidates_on_same_length_pgn_change(self):
        """Blake2b-16 content hash, not len(), drives cache invalidation.

        Replacing Nf3 with Nc3 produces a PGN of identical byte length but
        a different content hash.  The resolved cache must recompute.
        """
        import chess.pgn as _chess_pgn

        game = make_game()
        ChessLogStorageService.store_tags(game, {
            "0": [ChessLogStorageService.make_entry("CLAMP", "C", "hash test")],
        })
        ctrl, gm = make_controller(game)
        gm.active_game = game
        ctrl._load_into_cache(game)

        with patch.object(_chess_pgn, "read_game", wraps=_chess_pgn.read_game) as spy:
            ctrl.get_tags_for_current_game()
            self.assertEqual(spy.call_count, 1)

            # Substitute Nf3 → Nc3 — same byte length, different content
            before = game.pgn
            modified = before.replace("Nf3", "Nc3")
            self.assertEqual(len(before), len(modified), "Precondition: byte length must be identical")
            self.assertNotEqual(before, modified, "Precondition: content must differ")
            game.pgn = modified

            ctrl.get_tags_for_current_game()
            self.assertEqual(spy.call_count, 2, "Cache not invalidated on same-length PGN content change")

    def test_resolved_view_returns_copy_not_reference(self):
        """Mutating the returned dict must not corrupt the memoized resolved view."""
        game = make_game()
        ChessLogStorageService.store_tags(game, {
            "0": [ChessLogStorageService.make_entry("CLAMP", "C", "copy test")],
        })
        ctrl, gm = make_controller(game)
        gm.active_game = game
        ctrl._load_into_cache(game)

        result1 = ctrl.get_tags_for_current_game()
        self.assertIn("0", result1)

        # Mutate the returned dict: add a bogus key and remove the real one
        result1["bogus_key"] = []
        del result1["0"]

        # Second call must return the unmutated view
        result2 = ctrl.get_tags_for_current_game()
        self.assertNotIn("bogus_key", result2)
        self.assertIn("0", result2)


if __name__ == "__main__":
    unittest.main()
