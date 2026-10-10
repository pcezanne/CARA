"""Tests for ShowShallowTagsDialog.

Requires a working Qt platform plugin (CI uses QT_QPA_PLATFORM=offscreen).
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, call

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
    from PyQt6.QtWidgets import QApplication, QCheckBox, QPushButton
    _APP = QApplication.instance() or QApplication(sys.argv[:1])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MAINLINE_PGN = (
    '[Event "T"][Site "?"][Date "2026.01.01"]'
    '[Round "?"][White "W"][Black "B"][Result "*"]\n\n'
    "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 *\n"
)


def _make_game(game_number: int = 1, pgn: str = MAINLINE_PGN):
    from app.models.database_model import GameData
    return GameData(game_number=game_number, pgn=pgn)


def _make_entry(preset, cat, why="", ignore_shallow=False):
    from app.services.chess_log_storage_service import ChessLogStorageService
    return ChessLogStorageService.make_entry(preset, cat, why, ignore_shallow=ignore_shallow)


def _make_controller(tags_by_game=None):
    ctrl = MagicMock()
    tags_by_game = tags_by_game or {}

    def _get_tags(game):
        return tags_by_game.get(game.game_number, {})

    ctrl.get_tags_for_game.side_effect = _get_tags
    ctrl.get_custom_categories.return_value = []
    ctrl.replace_entries_at_path_for_game = MagicMock()
    return ctrl


def _make_dialog(games, tags_by_game, shallow_keys):
    from app.views.dialogs.show_shallow_tags_dialog import ShowShallowTagsDialog
    ctrl = _make_controller(tags_by_game)
    return ShowShallowTagsDialog(
        config={},
        games=games,
        controller=ctrl,
        shallow_keys=shallow_keys,
    ), ctrl


def _make_dialog_with_classified(games, tags_by_game, shallow_keys, classified_keys):
    from app.views.dialogs.show_shallow_tags_dialog import ShowShallowTagsDialog
    ctrl = _make_controller(tags_by_game)
    return ShowShallowTagsDialog(
        config={},
        games=games,
        controller=ctrl,
        shallow_keys=shallow_keys,
        classified_keys=classified_keys,
    ), ctrl


# ---------------------------------------------------------------------------
# Row filtering — only shallow_keys rows are shown
# ---------------------------------------------------------------------------

@requires_qt
class TestShallowRowFiltering(unittest.TestCase):
    def test_shows_only_shallow_keyed_rows(self):
        game = _make_game()
        tags = {
            "0": [_make_entry("CLAMP", "C", "I blundered")],
            "0.0": [_make_entry("CLAMP", "L", "deep insight about alignment")],
        }
        # Only ("0", "CLAMP") is shallow
        shallow_keys = {(1, "0", "CLAMP")}
        dlg, _ = _make_dialog([game], {1: tags}, shallow_keys)
        self.assertEqual(len(dlg._row_widgets), 1)

    def test_shows_all_rows_when_all_shallow(self):
        game = _make_game()
        tags = {
            "0": [_make_entry("CLAMP", "C", "I blundered")],
            "0.0": [_make_entry("CLAMP", "L", "missed it")],
        }
        shallow_keys = {(1, "0", "CLAMP"), (1, "0.0", "CLAMP")}
        dlg, _ = _make_dialog([game], {1: tags}, shallow_keys)
        self.assertEqual(len(dlg._row_widgets), 2)

    def test_shows_zero_rows_when_no_shallow_keys(self):
        game = _make_game()
        tags = {"0": [_make_entry("CLAMP", "C", "deep note")]}
        dlg, _ = _make_dialog([game], {1: tags}, set())
        self.assertEqual(len(dlg._row_widgets), 0)

    def test_preset_filter_respected(self):
        game = _make_game()
        tags = {
            "0": [
                _make_entry("CLAMP", "C", "shallow"),
                _make_entry("CCT", "Checks", "also shallow"),
            ],
        }
        # Only CLAMP is shallow
        shallow_keys = {(1, "0", "CLAMP")}
        dlg, _ = _make_dialog([game], {1: tags}, shallow_keys)
        self.assertEqual(len(dlg._row_widgets), 1)
        self.assertEqual(dlg._row_widgets[0]._preset, "CLAMP")


# ---------------------------------------------------------------------------
# Save/Cancel: edits are buffered until Save, not on each edit signal
# ---------------------------------------------------------------------------

@requires_qt
class TestLiveEdit(unittest.TestCase):
    def test_edited_signal_does_not_trigger_immediate_persist(self):
        """Emitting the edited signal must NOT call replace_entries_at_path_for_game.

        The old live-edit model was removed; edits are now buffered until Save.
        """
        game = _make_game()
        tags = {"0": [_make_entry("CLAMP", "C", "I blundered")]}
        shallow_keys = {(1, "0", "CLAMP")}
        dlg, ctrl = _make_dialog([game], {1: tags}, shallow_keys)

        row = dlg._row_widgets[0]
        row.edited.emit()

        ctrl.replace_entries_at_path_for_game.assert_not_called()

    def test_save_calls_replace_and_save_games(self):
        """_on_save writes the shown row and calls save_games."""
        game = _make_game()
        tags = {"0": [_make_entry("CLAMP", "C", "I blundered")]}
        shallow_keys = {(1, "0", "CLAMP")}
        classified_keys = frozenset(shallow_keys)
        dlg, ctrl = _make_dialog_with_classified(
            [game], {1: tags}, shallow_keys, classified_keys
        )
        ctrl.save_games = MagicMock()

        dlg._on_save()

        ctrl.replace_entries_at_path_for_game.assert_called_once()
        call_args = ctrl.replace_entries_at_path_for_game.call_args[0]
        self.assertIs(call_args[0], game)
        self.assertEqual(call_args[1], "0")
        self.assertEqual(call_args[2], "CLAMP")
        ctrl.save_games.assert_called_once()


# ---------------------------------------------------------------------------
# Ignore checkbox present on all rows
# ---------------------------------------------------------------------------

@requires_qt
class TestIgnoreCheckboxPresent(unittest.TestCase):
    def test_all_rows_have_ignore_checkbox(self):
        game = _make_game()
        tags = {
            "0": [_make_entry("CLAMP", "C", "shallow1")],
            "0.0": [_make_entry("CLAMP", "L", "shallow2")],
        }
        shallow_keys = {(1, "0", "CLAMP"), (1, "0.0", "CLAMP")}
        dlg, _ = _make_dialog([game], {1: tags}, shallow_keys)
        for row in dlg._row_widgets:
            self.assertIsNotNone(row._ignore_check)
            self.assertIsInstance(row._ignore_check, QCheckBox)


# ---------------------------------------------------------------------------
# Buttons: Save + Cancel (no Close-only, no OK)
# ---------------------------------------------------------------------------

@requires_qt
class TestCloseButton(unittest.TestCase):
    def test_has_save_button(self):
        game = _make_game()
        tags = {"0": [_make_entry("CLAMP", "C", "shallow")]}
        dlg, _ = _make_dialog([game], {1: tags}, {(1, "0", "CLAMP")})
        self.assertTrue(hasattr(dlg, "_save_btn"))
        self.assertIsInstance(dlg._save_btn, QPushButton)

    def test_has_cancel_button(self):
        game = _make_game()
        tags = {"0": [_make_entry("CLAMP", "C", "shallow")]}
        dlg, _ = _make_dialog([game], {1: tags}, {(1, "0", "CLAMP")})
        self.assertTrue(hasattr(dlg, "_cancel_btn"))
        self.assertIsInstance(dlg._cancel_btn, QPushButton)

    def test_no_ok_button(self):
        game = _make_game()
        tags = {"0": [_make_entry("CLAMP", "C", "shallow")]}
        dlg, _ = _make_dialog([game], {1: tags}, {(1, "0", "CLAMP")})
        self.assertFalse(hasattr(dlg, "_ok_btn"))

    def test_empty_shallow_keys_shows_no_rows_but_has_save(self):
        game = _make_game()
        tags = {"0": [_make_entry("CLAMP", "C", "deep note")]}
        dlg, _ = _make_dialog([game], {1: tags}, set())
        self.assertEqual(len(dlg._row_widgets), 0)
        self.assertTrue(hasattr(dlg, "_save_btn"))


# ---------------------------------------------------------------------------
# Mini-board orientation follows the mover at the tagged ply, per row
# ---------------------------------------------------------------------------

@requires_qt
class TestMiniBoardOrientationMoverAtPly(unittest.TestCase):
    """Shallow dialog row orientation comes from pre_board.turn at the tagged ply."""

    def test_white_ply_row_not_flipped(self):
        # MAINLINE_PGN: path "0" is 1.e4 — White to move → not flipped
        game = _make_game()
        tags = {"0": [_make_entry("CLAMP", "C", "shallow")]}
        dlg, _ = _make_dialog([game], {1: tags}, {(1, "0", "CLAMP")})
        self.assertFalse(dlg._row_widgets[0]._is_flipped)

    def test_black_ply_row_is_flipped(self):
        # MAINLINE_PGN: path "0.0" is 1...e5 — Black to move → flipped
        game = _make_game()
        tags = {"0.0": [_make_entry("CLAMP", "C", "shallow")]}
        dlg, _ = _make_dialog([game], {1: tags}, {(1, "0.0", "CLAMP")})
        self.assertTrue(dlg._row_widgets[0]._is_flipped)

    def test_snapshot_carries_flip_for_black_ply(self):
        game = _make_game()
        tags = {"0.0": [_make_entry("CLAMP", "C", "shallow")]}
        dlg, _ = _make_dialog([game], {1: tags}, {(1, "0.0", "CLAMP")})
        self.assertTrue(dlg._row_widgets[0].snapshot().is_flipped)


# ---------------------------------------------------------------------------
# Font and height wiring — shared _TagRowWidget reads from ui.dialogs.show_tags.*
# ---------------------------------------------------------------------------

@requires_qt
class TestShallowTagsDialogFontAndHeightWiring(unittest.TestCase):
    """ShowShallowTagsDialog rows inherit font/height config from the shared
    _TagRowWidget, which must read from ui.dialogs.show_tags.*, not moment."""

    def _make_shallow_dialog(self, show_tags_cfg: dict):
        from app.views.dialogs.show_shallow_tags_dialog import ShowShallowTagsDialog
        config = {"ui": {"dialogs": {"show_tags": show_tags_cfg}}}
        game = _make_game()
        tags = {"0": [_make_entry("CLAMP", "C", "shallow note")]}
        shallow_keys = {(1, "0", "CLAMP")}
        ctrl = _make_controller({1: tags})
        return ShowShallowTagsDialog(
            config=config,
            games=[game],
            controller=ctrl,
            shallow_keys=shallow_keys,
        )

    def test_input_font_size_from_config(self):
        dlg = self._make_shallow_dialog({"inputs": {"font_size": 14}})
        row = dlg._row_widgets[0]
        self.assertEqual(row._input_font_size, 14)

    def test_why_minimum_lines_from_config(self):
        dlg_small = self._make_shallow_dialog({"why_minimum_lines": 3})
        dlg_large = self._make_shallow_dialog({"why_minimum_lines": 6})
        te_small = dlg_small._row_widgets[0]._why_texts.get("why")
        te_large = dlg_large._row_widgets[0]._why_texts.get("why")
        self.assertIsNotNone(te_small)
        self.assertIsNotNone(te_large)
        self.assertGreater(te_large.minimumHeight(), te_small.minimumHeight())

    def test_defaults_when_config_empty(self):
        dlg = self._make_shallow_dialog({})
        row = dlg._row_widgets[0]
        self.assertEqual(row._input_font_size, 11)
        te = row._why_texts.get("why")
        self.assertIsNotNone(te)
        self.assertGreater(te.minimumHeight(), 0)


# ---------------------------------------------------------------------------
# Resize grip
# ---------------------------------------------------------------------------

@requires_qt
class TestShallowTagsDialogResizeGrip(unittest.TestCase):
    def test_resize_grip_installed(self):
        game = _make_game()
        tags = {"0": [_make_entry("CLAMP", "C", "shallow")]}
        dlg, _ = _make_dialog([game], {1: tags}, {(1, "0", "CLAMP")})
        self.assertTrue(hasattr(dlg, "_cara_themed_resize_grip"))

    def test_resize_grip_installed_empty_dialog(self):
        game = _make_game()
        tags = {"0": [_make_entry("CLAMP", "C", "not shallow")]}
        dlg, _ = _make_dialog([game], {1: tags}, set())
        self.assertTrue(hasattr(dlg, "_cara_themed_resize_grip"))


# ---------------------------------------------------------------------------
# Save model: full suite (plan tests 13-20)
# ---------------------------------------------------------------------------

@requires_qt
class TestSaveModel(unittest.TestCase):

    def test_save_writes_is_shallow_true_for_shown_rows(self):
        """Plan test 13: shown rows get is_shallow=True stamped on Save."""
        game = _make_game()
        tags = {
            "0": [_make_entry("CLAMP", "C", "shallow one")],
            "0.0": [_make_entry("CLAMP", "L", "shallow two")],
            "1": [_make_entry("CLAMP", "A", "not shallow")],
        }
        shallow_keys = {(1, "0", "CLAMP"), (1, "0.0", "CLAMP")}
        classified_keys = frozenset(shallow_keys | {(1, "1", "CLAMP")})
        dlg, ctrl = _make_dialog_with_classified(
            [game], {1: tags}, shallow_keys, classified_keys
        )
        ctrl.save_games = MagicMock()

        dlg._on_save()

        calls = ctrl.replace_entries_at_path_for_game.call_args_list
        shown_calls = {(c[0][1], c[0][2]) for c in calls}
        # Both shallow rows touched; deep-but-not-stale "1" not touched
        self.assertIn(("0", "CLAMP"), shown_calls)
        self.assertIn(("0.0", "CLAMP"), shown_calls)
        for c in calls:
            if c[0][1] in ("0", "0.0"):
                self.assertTrue(all(e.get("is_shallow") for e in c[0][3]))

    def test_save_clears_stale_is_shallow_for_non_shown_entries(self):
        """Plan test 14: DEEP entry with stale is_shallow=True gets cleared on Save."""
        game = _make_game()
        stale_entry = dict(_make_entry("CLAMP", "C", "deep now"), is_shallow=True)
        tags = {
            "0": [_make_entry("CLAMP", "L", "still shallow")],
            "0.0": [stale_entry],
        }
        shallow_keys = {(1, "0", "CLAMP")}
        classified_keys = frozenset({(1, "0", "CLAMP"), (1, "0.0", "CLAMP")})
        dlg, ctrl = _make_dialog_with_classified(
            [game], {1: tags}, shallow_keys, classified_keys
        )
        ctrl.save_games = MagicMock()

        dlg._on_save()

        # "0.0" is deep-classified and has stale flag → must be cleared
        deep_call = None
        for c in ctrl.replace_entries_at_path_for_game.call_args_list:
            if c[0][1] == "0.0":
                deep_call = c
        self.assertIsNotNone(deep_call, "Expected replace call for 0.0")
        self.assertFalse(any(e.get("is_shallow") for e in deep_call[0][3]))
        ctrl.save_games.assert_called_once()

    def test_cancel_discards_pending_shallow_results(self):
        """Plan test 15: Cancel makes no writes."""
        game = _make_game()
        tags = {"0": [_make_entry("CLAMP", "C", "shallow")]}
        shallow_keys = {(1, "0", "CLAMP")}
        classified_keys = frozenset(shallow_keys)
        dlg, ctrl = _make_dialog_with_classified(
            [game], {1: tags}, shallow_keys, classified_keys
        )
        ctrl.save_games = MagicMock()

        dlg.reject()

        ctrl.replace_entries_at_path_for_game.assert_not_called()
        ctrl.save_games.assert_not_called()

    def test_close_button_discards(self):
        """Plan test 16: close() routes to reject, making no writes."""
        game = _make_game()
        tags = {"0": [_make_entry("CLAMP", "C", "shallow")]}
        shallow_keys = {(1, "0", "CLAMP")}
        classified_keys = frozenset(shallow_keys)
        dlg, ctrl = _make_dialog_with_classified(
            [game], {1: tags}, shallow_keys, classified_keys
        )
        ctrl.save_games = MagicMock()

        dlg.close()

        ctrl.replace_entries_at_path_for_game.assert_not_called()
        ctrl.save_games.assert_not_called()

    def test_ignore_toggle_persists_only_on_save(self):
        """Plan test 17: Ignore toggle saved on Save, discarded on Cancel."""
        game = _make_game()
        tags = {"0": [_make_entry("CLAMP", "C", "shallow", ignore_shallow=False)]}
        shallow_keys = {(1, "0", "CLAMP")}
        classified_keys = frozenset(shallow_keys)

        # Cancel: toggle, then cancel → not persisted
        dlg_c, ctrl_c = _make_dialog_with_classified(
            [game], {1: tags}, shallow_keys, classified_keys
        )
        ctrl_c.save_games = MagicMock()
        dlg_c._row_widgets[0]._ignore_check.setChecked(True)
        dlg_c.reject()
        ctrl_c.replace_entries_at_path_for_game.assert_not_called()

        # Save: toggle, then save → persisted with ignore_shallow=True
        dlg_s, ctrl_s = _make_dialog_with_classified(
            [game], {1: tags}, shallow_keys, classified_keys
        )
        ctrl_s.save_games = MagicMock()
        dlg_s._row_widgets[0]._ignore_check.setChecked(True)
        dlg_s._on_save()
        calls = ctrl_s.replace_entries_at_path_for_game.call_args_list
        self.assertTrue(len(calls) > 0)
        saved_entries = calls[0][0][3]
        self.assertTrue(any(e.get("ignore_shallow") for e in saved_entries))

    def test_save_leaves_unparsed_entry_is_shallow_untouched(self):
        """Plan test 19: entry not in classified_keys keeps is_shallow=True after Save."""
        game = _make_game()
        # Entry at "0.0" was not classified this run (unparsed) → must not be touched
        prior_shallow = dict(_make_entry("CLAMP", "A", "hard to parse"), is_shallow=True)
        tags = {
            "0": [_make_entry("CLAMP", "C", "shallow")],
            "0.0": [prior_shallow],
        }
        shallow_keys = {(1, "0", "CLAMP")}
        # classified_keys does NOT include "0.0" — it was unparsed
        classified_keys = frozenset({(1, "0", "CLAMP")})
        dlg, ctrl = _make_dialog_with_classified(
            [game], {1: tags}, shallow_keys, classified_keys
        )
        ctrl.save_games = MagicMock()

        dlg._on_save()

        for c in ctrl.replace_entries_at_path_for_game.call_args_list:
            self.assertNotEqual(c[0][1], "0.0",
                "replace must not be called for unparsed entry at 0.0")

    def test_save_leaves_ignored_entry_flags_untouched(self):
        """Plan test 20: entry with ignore_shallow=True keeps its flags after Save."""
        game = _make_game()
        ignored_entry = dict(
            _make_entry("CLAMP", "L", "ignored", ignore_shallow=True),
            is_shallow=True,
        )
        tags = {
            "0": [_make_entry("CLAMP", "C", "shallow")],
            "0.0": [ignored_entry],
        }
        shallow_keys = {(1, "0", "CLAMP")}
        # "0.0" skipped by classifier (ignore_shallow=True) → not in classified_keys
        classified_keys = frozenset({(1, "0", "CLAMP")})
        dlg, ctrl = _make_dialog_with_classified(
            [game], {1: tags}, shallow_keys, classified_keys
        )
        ctrl.save_games = MagicMock()

        dlg._on_save()

        for c in ctrl.replace_entries_at_path_for_game.call_args_list:
            self.assertNotEqual(c[0][1], "0.0",
                "replace must not be called for ignore_shallow entry at 0.0")

    def test_save_marks_both_databases_in_mixed_scope(self):
        """Plan test 18: Save on games from two DBs calls save_games once with both."""
        from unittest.mock import call as mock_call
        game_a = _make_game(game_number=1)
        game_b = _make_game(game_number=2)
        tags_a = {"0": [_make_entry("CLAMP", "C", "shallow a")]}
        tags_b = {"0": [_make_entry("CLAMP", "C", "shallow b")]}
        shallow_keys = {(1, "0", "CLAMP"), (2, "0", "CLAMP")}
        classified_keys = frozenset(shallow_keys)

        from app.views.dialogs.show_shallow_tags_dialog import ShowShallowTagsDialog
        ctrl = _make_controller({1: tags_a, 2: tags_b})
        ctrl.save_games = MagicMock()
        dlg = ShowShallowTagsDialog(
            config={},
            games=[game_a, game_b],
            controller=ctrl,
            shallow_keys=shallow_keys,
            classified_keys=classified_keys,
        )

        dlg._on_save()

        ctrl.save_games.assert_called_once()
        saved_games = set(ctrl.save_games.call_args[0][0])
        self.assertIn(game_a, saved_games)
        self.assertIn(game_b, saved_games)


if __name__ == "__main__":
    unittest.main()
