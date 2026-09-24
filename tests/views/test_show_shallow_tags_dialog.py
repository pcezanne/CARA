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
# Live-edit: edited signal triggers immediate persist
# ---------------------------------------------------------------------------

@requires_qt
class TestLiveEdit(unittest.TestCase):
    def test_edited_triggers_replace_entries_at_path_for_game(self):
        game = _make_game()
        tags = {"0": [_make_entry("CLAMP", "C", "I blundered")]}
        shallow_keys = {(1, "0", "CLAMP")}
        dlg, ctrl = _make_dialog([game], {1: tags}, shallow_keys)

        row = dlg._row_widgets[0]
        # Emit the edited signal directly (simulates debounce firing)
        row.edited.emit()

        ctrl.replace_entries_at_path_for_game.assert_called_once()
        call_args = ctrl.replace_entries_at_path_for_game.call_args[0]
        self.assertIs(call_args[0], game)
        self.assertEqual(call_args[1], "0")
        self.assertEqual(call_args[2], "CLAMP")

    def test_live_edit_passes_current_entries(self):
        game = _make_game()
        tags = {"0": [_make_entry("CLAMP", "C", "I blundered")]}
        shallow_keys = {(1, "0", "CLAMP")}
        dlg, ctrl = _make_dialog([game], {1: tags}, shallow_keys)

        row = dlg._row_widgets[0]
        row._why_texts["why"].setPlainText("new text")
        row.edited.emit()

        call_args = ctrl.replace_entries_at_path_for_game.call_args[0]
        new_entries = call_args[3]
        self.assertTrue(any(e.get("why") == "new text" for e in new_entries))


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
# Buttons: Close only (no Cancel, no OK)
# ---------------------------------------------------------------------------

@requires_qt
class TestCloseButton(unittest.TestCase):
    def test_has_close_button(self):
        game = _make_game()
        tags = {"0": [_make_entry("CLAMP", "C", "shallow")]}
        dlg, _ = _make_dialog([game], {1: tags}, {(1, "0", "CLAMP")})
        self.assertTrue(hasattr(dlg, "_close_btn"))
        self.assertIsInstance(dlg._close_btn, QPushButton)

    def test_no_cancel_button(self):
        game = _make_game()
        tags = {"0": [_make_entry("CLAMP", "C", "shallow")]}
        dlg, _ = _make_dialog([game], {1: tags}, {(1, "0", "CLAMP")})
        self.assertFalse(hasattr(dlg, "_cancel_btn"))

    def test_no_ok_button(self):
        game = _make_game()
        tags = {"0": [_make_entry("CLAMP", "C", "shallow")]}
        dlg, _ = _make_dialog([game], {1: tags}, {(1, "0", "CLAMP")})
        self.assertFalse(hasattr(dlg, "_ok_btn"))

    def test_empty_shallow_keys_shows_no_rows_but_has_close(self):
        game = _make_game()
        tags = {"0": [_make_entry("CLAMP", "C", "deep note")]}
        dlg, _ = _make_dialog([game], {1: tags}, set())
        self.assertEqual(len(dlg._row_widgets), 0)
        self.assertTrue(hasattr(dlg, "_close_btn"))


# ---------------------------------------------------------------------------
# Mini-board orientation follows the tracked player, not the main board's flip
# ---------------------------------------------------------------------------

@requires_qt
class TestMiniBoardOrientation(unittest.TestCase):
    """Shallow dialog mini boards orient to the tracked player, per row."""

    def _game(self, game_number: int, white: str, black: str):
        from app.models.database_model import GameData
        pgn = (
            f'[Event "T"][Site "?"][Date "2026.01.01"]'
            f'[Round "?"][White "{white}"][Black "{black}"][Result "*"]\n\n'
            "1. e4 e5 *\n"
        )
        return GameData(game_number=game_number, white=white, black=black, pgn=pgn)

    def _open(self, player_name: str, white: str = "Alice", black: str = "Bob"):
        from app.views.dialogs.show_shallow_tags_dialog import ShowShallowTagsDialog
        game = self._game(1, white, black)
        tags = {"0": [_make_entry("CLAMP", "C", "shallow")]}
        ctrl = _make_controller({1: tags})
        return ShowShallowTagsDialog(
            config={},
            games=[game],
            controller=ctrl,
            shallow_keys={(1, "0", "CLAMP")},
            player_name=player_name,
        )

    def test_tracked_player_black_flips_row(self):
        dlg = self._open(player_name="Bob")
        self.assertTrue(dlg._row_widgets[0]._is_flipped)

    def test_tracked_player_white_leaves_row_unflipped(self):
        dlg = self._open(player_name="Alice")
        self.assertFalse(dlg._row_widgets[0]._is_flipped)

    def test_tracked_player_not_in_game_leaves_row_unflipped(self):
        dlg = self._open(player_name="Charlie")
        self.assertFalse(dlg._row_widgets[0]._is_flipped)

    def test_default_player_name_is_empty_and_unflipped(self):
        # Callers that predate player_name kwarg — dialog still constructs.
        from app.views.dialogs.show_shallow_tags_dialog import ShowShallowTagsDialog
        game = self._game(1, "Alice", "Bob")
        tags = {"0": [_make_entry("CLAMP", "C", "shallow")]}
        ctrl = _make_controller({1: tags})
        dlg = ShowShallowTagsDialog(
            config={},
            games=[game],
            controller=ctrl,
            shallow_keys={(1, "0", "CLAMP")},
        )
        self.assertFalse(dlg._row_widgets[0]._is_flipped)

    def test_multi_game_row_orientation_computed_per_game(self):
        """Same tracked player, White in game 1 and Black in game 2."""
        from app.views.dialogs.show_shallow_tags_dialog import ShowShallowTagsDialog
        g1 = self._game(1, "Paul", "Opp1")
        g2 = self._game(2, "Opp2", "Paul")
        tags1 = {"0": [_make_entry("CLAMP", "C", "shallow")]}
        tags2 = {"0": [_make_entry("CLAMP", "C", "shallow")]}
        ctrl = _make_controller({1: tags1, 2: tags2})
        dlg = ShowShallowTagsDialog(
            config={},
            games=[g1, g2],
            controller=ctrl,
            shallow_keys={(1, "0", "CLAMP"), (2, "0", "CLAMP")},
            player_name="Paul",
        )
        self.assertFalse(dlg._row_widgets[0]._is_flipped)
        self.assertTrue(dlg._row_widgets[1]._is_flipped)

    def test_snapshot_carries_is_flipped(self):
        dlg = self._open(player_name="Bob")
        snapshot = dlg._row_widgets[0].snapshot()
        self.assertTrue(snapshot.is_flipped)


if __name__ == "__main__":
    unittest.main()
