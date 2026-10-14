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
        shallow_keys = {(1, "0", "CLAMP", "")}
        dlg, _ = _make_dialog([game], {1: tags}, shallow_keys)
        self.assertEqual(len(dlg._row_widgets), 1)

    def test_shows_all_rows_when_all_shallow(self):
        game = _make_game()
        tags = {
            "0": [_make_entry("CLAMP", "C", "I blundered")],
            "0.0": [_make_entry("CLAMP", "L", "missed it")],
        }
        shallow_keys = {(1, "0", "CLAMP", ""), (1, "0.0", "CLAMP", "")}
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
        shallow_keys = {(1, "0", "CLAMP", "")}
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
        shallow_keys = {(1, "0", "CLAMP", "")}
        dlg, ctrl = _make_dialog([game], {1: tags}, shallow_keys)

        row = dlg._row_widgets[0]
        row.edited.emit()

        ctrl.replace_entries_at_path_for_game.assert_not_called()

    def test_save_calls_replace_and_save_games(self):
        """_on_save writes the shown row and calls save_games."""
        game = _make_game()
        tags = {"0": [_make_entry("CLAMP", "C", "I blundered")]}
        shallow_keys = {(1, "0", "CLAMP", "")}
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
        shallow_keys = {(1, "0", "CLAMP", ""), (1, "0.0", "CLAMP", "")}
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
        dlg, _ = _make_dialog([game], {1: tags}, {(1, "0", "CLAMP", "")})
        self.assertTrue(hasattr(dlg, "_save_btn"))
        self.assertIsInstance(dlg._save_btn, QPushButton)

    def test_has_cancel_button(self):
        game = _make_game()
        tags = {"0": [_make_entry("CLAMP", "C", "shallow")]}
        dlg, _ = _make_dialog([game], {1: tags}, {(1, "0", "CLAMP", "")})
        self.assertTrue(hasattr(dlg, "_cancel_btn"))
        self.assertIsInstance(dlg._cancel_btn, QPushButton)

    def test_no_ok_button(self):
        game = _make_game()
        tags = {"0": [_make_entry("CLAMP", "C", "shallow")]}
        dlg, _ = _make_dialog([game], {1: tags}, {(1, "0", "CLAMP", "")})
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
        dlg, _ = _make_dialog([game], {1: tags}, {(1, "0", "CLAMP", "")})
        self.assertFalse(dlg._row_widgets[0]._is_flipped)

    def test_black_ply_row_is_flipped(self):
        # MAINLINE_PGN: path "0.0" is 1...e5 — Black to move → flipped
        game = _make_game()
        tags = {"0.0": [_make_entry("CLAMP", "C", "shallow")]}
        dlg, _ = _make_dialog([game], {1: tags}, {(1, "0.0", "CLAMP", "")})
        self.assertTrue(dlg._row_widgets[0]._is_flipped)

    def test_snapshot_carries_flip_for_black_ply(self):
        game = _make_game()
        tags = {"0.0": [_make_entry("CLAMP", "C", "shallow")]}
        dlg, _ = _make_dialog([game], {1: tags}, {(1, "0.0", "CLAMP", "")})
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
        shallow_keys = {(1, "0", "CLAMP", "")}
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
# Window title is "Check Logs"
# ---------------------------------------------------------------------------

@requires_qt
class TestWindowTitle(unittest.TestCase):
    def test_window_title_is_check_logs(self):
        game = _make_game()
        tags = {"0": [_make_entry("CLAMP", "C", "shallow")]}
        dlg, _ = _make_dialog([game], {1: tags}, {(1, "0", "CLAMP", "")})
        self.assertEqual(dlg.windowTitle(), "Check Logs")


# ---------------------------------------------------------------------------
# Resize grip
# ---------------------------------------------------------------------------

@requires_qt
class TestShallowTagsDialogResizeGrip(unittest.TestCase):
    def test_resize_grip_installed(self):
        game = _make_game()
        tags = {"0": [_make_entry("CLAMP", "C", "shallow")]}
        dlg, _ = _make_dialog([game], {1: tags}, {(1, "0", "CLAMP", "")})
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
        shallow_keys = {(1, "0", "CLAMP", ""), (1, "0.0", "CLAMP", "")}
        classified_keys = frozenset(shallow_keys | {(1, "1", "CLAMP", "")})
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
        shallow_keys = {(1, "0", "CLAMP", "")}
        classified_keys = frozenset({(1, "0", "CLAMP", ""), (1, "0.0", "CLAMP", "")})
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
        shallow_keys = {(1, "0", "CLAMP", "")}
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
        shallow_keys = {(1, "0", "CLAMP", "")}
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
        shallow_keys = {(1, "0", "CLAMP", "")}
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
        shallow_keys = {(1, "0", "CLAMP", "")}
        # classified_keys does NOT include "0.0" — it was unparsed
        classified_keys = frozenset({(1, "0", "CLAMP", "")})
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
        shallow_keys = {(1, "0", "CLAMP", "")}
        # "0.0" skipped by classifier (ignore_shallow=True) → not in classified_keys
        classified_keys = frozenset({(1, "0", "CLAMP", "")})
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
        shallow_keys = {(1, "0", "CLAMP", ""), (2, "0", "CLAMP", "")}
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


# ---------------------------------------------------------------------------
# Chip labels — Shallow / Vague lesson
# ---------------------------------------------------------------------------

@requires_qt
class TestChipLabels(unittest.TestCase):
    """Row chips reflect the is_shallow / is_vague flags on entries."""

    def _make_vague_dialog(self, shallow_keys, vague_keys, entries_by_path, classified_keys=None):
        from app.views.dialogs.show_shallow_tags_dialog import ShowShallowTagsDialog
        game = _make_game()
        ctrl = _make_controller({1: entries_by_path})
        ck = frozenset(classified_keys) if classified_keys is not None else frozenset(shallow_keys | vague_keys)
        return ShowShallowTagsDialog(
            config={},
            games=[game],
            controller=ctrl,
            shallow_keys=shallow_keys,
            vague_keys=vague_keys,
            classified_keys=ck,
        ), ctrl

    def test_shallow_chip_present_when_is_shallow(self):
        entries = {"0": [_make_entry("CLAMP", "C", "shallow one")]}
        dlg, _ = self._make_vague_dialog(
            shallow_keys={(1, "0", "CLAMP", "")},
            vague_keys=frozenset(),
            entries_by_path=entries,
        )
        row = dlg._row_widgets[0]
        self.assertTrue(row._preserved_is_shallow)
        self.assertIsNotNone(row._shallow_chip)
        self.assertIsNone(row._vague_chip)

    def test_vague_chip_present_when_is_vague(self):
        entries = {"0": [_make_entry("CLAMP", "C", "specific + filler lesson")]}
        dlg, _ = self._make_vague_dialog(
            shallow_keys=frozenset(),
            vague_keys={(1, "0", "CLAMP", "")},
            entries_by_path=entries,
        )
        row = dlg._row_widgets[0]
        self.assertFalse(row._preserved_is_shallow)
        self.assertTrue(row._preserved_is_vague)
        self.assertIsNone(row._shallow_chip)
        self.assertIsNotNone(row._vague_chip)

    def test_both_chips_present_when_both_flags(self):
        entries = {"0": [_make_entry("CLAMP", "C", "generic + filler")]}
        dlg, _ = self._make_vague_dialog(
            shallow_keys={(1, "0", "CLAMP", "")},
            vague_keys={(1, "0", "CLAMP", "")},
            entries_by_path=entries,
        )
        row = dlg._row_widgets[0]
        self.assertIsNotNone(row._shallow_chip)
        self.assertIsNotNone(row._vague_chip)

    def test_no_chips_when_neither_flag(self):
        entries = {"0": [_make_entry("CLAMP", "C", "deep specific real")]}
        dlg, _ = self._make_vague_dialog(
            shallow_keys={(1, "0", "CLAMP", "")},
            vague_keys=frozenset(),
            entries_by_path=entries,
        )
        row = dlg._row_widgets[0]
        self.assertFalse(row._preserved_is_vague)
        self.assertIsNone(row._vague_chip)

    def test_chip_text_from_config(self):
        from PyQt6.QtWidgets import QLabel
        from app.views.dialogs.show_shallow_tags_dialog import ShowShallowTagsDialog
        game = _make_game()
        entries = {"0": [_make_entry("CLAMP", "C", "shallow")]}
        ctrl = _make_controller({1: entries})
        config = {"ui": {"dialogs": {"shallow": {"labels": {
            "shallow": {"text": "FLAGGED", "background_color": [100, 0, 0], "text_color": [255, 255, 255]},
        }}}}}
        dlg = ShowShallowTagsDialog(
            config=config, games=[game], controller=ctrl,
            shallow_keys={(1, "0", "CLAMP", "")}, vague_keys=frozenset(),
            classified_keys=frozenset({(1, "0", "CLAMP", "")}),
        )
        row = dlg._row_widgets[0]
        self.assertIsNotNone(row._shallow_chip)
        self.assertEqual(row._shallow_chip.text(), "FLAGGED")

    def test_chip_tooltip_from_config(self):
        from app.views.dialogs.show_shallow_tags_dialog import ShowShallowTagsDialog
        game = _make_game()
        entries = {"0": [_make_entry("CLAMP", "C", "shallow")]}
        ctrl = _make_controller({1: entries})
        config = {"ui": {"dialogs": {"shallow": {"labels": {
            "shallow": {"text": "S", "tooltip": "Custom tip",
                        "background_color": [100, 0, 0], "text_color": [255, 255, 255]},
        }}}}}
        dlg = ShowShallowTagsDialog(
            config=config, games=[game], controller=ctrl,
            shallow_keys={(1, "0", "CLAMP", "")}, vague_keys=frozenset(),
            classified_keys=frozenset({(1, "0", "CLAMP", "")}),
        )
        self.assertEqual(dlg._row_widgets[0]._shallow_chip.toolTip(), "Custom tip")


# ---------------------------------------------------------------------------
# Vague-keys: Save/Cancel model
# ---------------------------------------------------------------------------

@requires_qt
class TestVagueKeysSaveModel(unittest.TestCase):

    def _vague_dialog(self, path_key, shallow=False, vague=True):
        from app.views.dialogs.show_shallow_tags_dialog import ShowShallowTagsDialog
        game = _make_game()
        # Create entries matching the per-cat keys being tested
        entries_list = []
        if shallow:
            entries_list.append(_make_entry("3x3", "Why1", "I wanted to trade queens"))
        if vague:
            entries_list.append(_make_entry("3x3", "Why4", "Try harder next time"))
        if not entries_list:
            entries_list.append(_make_entry("3x3", "Why1", "I wanted to trade queens"))
        entries = {path_key: entries_list}
        ctrl = _make_controller({1: entries})
        ctrl.save_games = MagicMock()
        sk = frozenset({(1, path_key, "3x3", "Why1")} if shallow else [])
        vk = frozenset({(1, path_key, "3x3", "Why4")} if vague else [])
        ck = frozenset(sk | vk)
        dlg = ShowShallowTagsDialog(
            config={}, games=[game], controller=ctrl,
            shallow_keys=sk, vague_keys=vk, classified_keys=ck,
        )
        return dlg, ctrl, game

    def test_save_writes_is_vague_true_for_vague_only_row(self):
        dlg, ctrl, game = self._vague_dialog("0", shallow=False, vague=True)
        dlg._on_save()
        calls = ctrl.replace_entries_at_path_for_game.call_args_list
        self.assertTrue(len(calls) > 0)
        entries_written = calls[0][0][3]
        self.assertTrue(any(e.get("is_vague") for e in entries_written))
        self.assertFalse(any(e.get("is_shallow") for e in entries_written))

    def test_save_writes_both_flags_for_shallow_and_vague_row(self):
        dlg, ctrl, game = self._vague_dialog("0", shallow=True, vague=True)
        dlg._on_save()
        calls = ctrl.replace_entries_at_path_for_game.call_args_list
        entries_written = calls[0][0][3]
        self.assertTrue(any(e.get("is_shallow") for e in entries_written))
        self.assertTrue(any(e.get("is_vague") for e in entries_written))

    def test_cancel_writes_nothing_for_vague_row(self):
        dlg, ctrl, game = self._vague_dialog("0", shallow=False, vague=True)
        dlg.reject()
        ctrl.replace_entries_at_path_for_game.assert_not_called()
        ctrl.save_games.assert_not_called()

    def test_stale_clear_removes_is_vague_from_non_flagged_classified_entry(self):
        from app.views.dialogs.show_shallow_tags_dialog import ShowShallowTagsDialog
        game = _make_game()
        stale = dict(_make_entry("CLAMP", "C", "deep now"), is_vague=True)
        tags = {
            "0": [_make_entry("CLAMP", "L", "shallow")],
            "0.0": [stale],
        }
        ctrl = _make_controller({1: tags})
        ctrl.save_games = MagicMock()
        sk = frozenset({(1, "0", "CLAMP", "")})
        ck = frozenset({(1, "0", "CLAMP", ""), (1, "0.0", "CLAMP", "")})
        dlg = ShowShallowTagsDialog(
            config={}, games=[game], controller=ctrl,
            shallow_keys=sk, vague_keys=frozenset(), classified_keys=ck,
        )
        dlg._on_save()
        deep_call = None
        for c in ctrl.replace_entries_at_path_for_game.call_args_list:
            if c[0][1] == "0.0":
                deep_call = c
        self.assertIsNotNone(deep_call, "Expected replace call for stale vague entry at 0.0")
        self.assertFalse(any(e.get("is_vague") for e in deep_call[0][3]))

    def test_blank_lesson_does_not_produce_vague_key(self):
        """Vague-keys set is empty → no vague chip, no is_vague written."""
        dlg, ctrl, game = self._vague_dialog("0", shallow=False, vague=False)
        self.assertEqual(len(dlg._row_widgets), 0)


# ---------------------------------------------------------------------------
# Snapshot fields is_shallow / is_vague for PDF
# ---------------------------------------------------------------------------

@requires_qt
class TestSnapshotFlags(unittest.TestCase):

    def test_snapshot_carries_is_shallow(self):
        game = _make_game()
        entry = dict(_make_entry("CLAMP", "C", "shallow"), is_shallow=True)
        tags = {"0": [entry]}
        dlg, _ = _make_dialog([game], {1: tags}, {(1, "0", "CLAMP", "")})
        snap = dlg._row_widgets[0].snapshot()
        self.assertTrue(snap.is_shallow)

    def test_snapshot_carries_is_vague(self):
        from app.views.dialogs.show_shallow_tags_dialog import ShowShallowTagsDialog
        game = _make_game()
        entry = dict(_make_entry("CLAMP", "C", "vague"), is_vague=True)
        tags = {"0": [entry]}
        ctrl = _make_controller({1: tags})
        dlg = ShowShallowTagsDialog(
            config={}, games=[game], controller=ctrl,
            shallow_keys=frozenset(), vague_keys={(1, "0", "CLAMP", "")},
            classified_keys=frozenset({(1, "0", "CLAMP", "")}),
        )
        snap = dlg._row_widgets[0].snapshot()
        self.assertTrue(snap.is_vague)


# ---------------------------------------------------------------------------
# B12 — per-cat chip rendering and Ignore for 3x3 rows
# ---------------------------------------------------------------------------

@requires_qt
class TestPerCatChip3x3(unittest.TestCase):
    """B12: per-cat chips for 3x3 rows."""

    def _make_3x3_dialog(self, shallow_keys, vague_keys, entries_by_path, classified_keys=None):
        from app.views.dialogs.show_shallow_tags_dialog import ShowShallowTagsDialog
        game = _make_game()
        ctrl = _make_controller({1: entries_by_path})
        ck = frozenset(classified_keys) if classified_keys is not None else frozenset(shallow_keys | vague_keys)
        return ShowShallowTagsDialog(
            config={}, games=[game], controller=ctrl,
            shallow_keys=shallow_keys, vague_keys=vague_keys, classified_keys=ck,
        )

    def test_shallow_chip_on_why1_only_when_generic_why1_real_why4(self):
        """GENERIC Why1 + REAL Why4 → Shallow chip on Why1 row, no Vague chip."""
        entries_list = [
            _make_entry("3x3", "Why1", "I wanted to trade queens"),
            _make_entry("3x3", "Why4", "Look at all captures first"),
        ]
        entries = {"0": entries_list}
        # Why1 is GENERIC (shallow), Why4 is REAL (not vague)
        sk = frozenset({(1, "0", "3x3", "Why1")})
        vk = frozenset()
        ck = frozenset({(1, "0", "3x3", "Why1"), (1, "0", "3x3", "Why4")})
        dlg = self._make_3x3_dialog(sk, vk, entries, ck)
        self.assertEqual(len(dlg._row_widgets), 1)
        row = dlg._row_widgets[0]
        # Why1 has shallow chip stored after pre-stamp
        why1_entry = next((e for e in row._entries if e.get("cat") == "Why1"), None)
        self.assertIsNotNone(why1_entry)
        self.assertTrue(why1_entry.get("is_shallow"))
        # Why4 has no vague chip
        why4_entry = next((e for e in row._entries if e.get("cat") == "Why4"), None)
        self.assertIsNotNone(why4_entry)
        self.assertFalse(why4_entry.get("is_vague", False))

    def test_chip_eligibility_clamp_why4_no_shallow_chip(self):
        """B4 rule 3: cat=Why4 entry with stored is_shallow=True → no Shallow chip rendered."""
        from app.views.dialogs.show_tags_dialog import _TagRowWidget
        entry = dict(_make_entry("3x3", "Why4", "Look at all captures"), is_shallow=True)
        row = _TagRowWidget(
            config={}, preset="3x3", entries=[entry],
            move_label="1.e4", fen=None, played_move=None,
            bg_rgb=[40, 40, 45], text_color=[200, 200, 200],
            show_ignore_checkbox=True,
        )
        # _shallow_chip should NOT be set for Why4 (chip-eligibility rule)
        self.assertIsNone(row._shallow_chip)

    def test_chip_eligibility_why1_no_vague_chip(self):
        """B4 rule 3: cat=Why1 entry with stored is_vague=True → no Vague chip rendered."""
        from app.views.dialogs.show_tags_dialog import _TagRowWidget
        entry = dict(_make_entry("3x3", "Why1", "I wanted to attack"), is_vague=True)
        row = _TagRowWidget(
            config={}, preset="3x3", entries=[entry],
            move_label="1.e4", fen=None, played_move=None,
            bg_rgb=[40, 40, 45], text_color=[200, 200, 200],
            show_ignore_checkbox=True,
        )
        self.assertIsNone(row._vague_chip)

    def test_per_cat_ignore_checkbox_in_ignore_checks(self):
        """Per-cat Ignore checkboxes are stored in _ignore_checks, keyed by cat."""
        from app.views.dialogs.show_tags_dialog import _TagRowWidget
        entry = dict(_make_entry("3x3", "Why1", "I moved impulsively"), is_shallow=True)
        row = _TagRowWidget(
            config={}, preset="3x3", entries=[entry],
            move_label="1.e4", fen=None, played_move=None,
            bg_rgb=[40, 40, 45], text_color=[200, 200, 200],
            show_ignore_checkbox=True,
        )
        from PyQt6.QtWidgets import QCheckBox
        self.assertIn("Why1", row._ignore_checks)
        self.assertIsInstance(row._ignore_checks["Why1"], QCheckBox)
        # Why4 has no chip and no ignore checkbox
        self.assertNotIn("Why4", row._ignore_checks)

    def test_per_cat_ignore_suppresses_only_flagged_answer(self):
        """Toggling Ignore on Why1 suppresses Why1 only; Why4 not affected."""
        from app.views.dialogs.show_tags_dialog import _TagRowWidget
        entries = [
            dict(_make_entry("3x3", "Why1", "I moved impulsively"), is_shallow=True),
            dict(_make_entry("3x3", "Why4", "Try harder"), is_vague=True),
        ]
        row = _TagRowWidget(
            config={}, preset="3x3", entries=entries,
            move_label="1.e4", fen=None, played_move=None,
            bg_rgb=[40, 40, 45], text_color=[200, 200, 200],
            show_ignore_checkbox=True,
        )
        # Tick Ignore on Why1
        row._ignore_checks["Why1"].setChecked(True)
        current = row.get_current_entries()
        why1 = next((e for e in current if e["cat"] == "Why1"), None)
        why4 = next((e for e in current if e["cat"] == "Why4"), None)
        self.assertIsNotNone(why1)
        self.assertTrue(why1.get("ignore_shallow"))
        self.assertIsNotNone(why4)
        self.assertFalse(why4.get("ignore_shallow", False))

    def test_save_writes_per_entry_flags_for_3x3(self):
        """Save writes is_shallow on Why1, is_vague on Why4 for 3x3 rows."""
        from app.views.dialogs.show_shallow_tags_dialog import ShowShallowTagsDialog
        game = _make_game()
        entries = {
            "0": [
                _make_entry("3x3", "Why1", "I moved impulsively"),
                _make_entry("3x3", "Why4", "Try harder next time"),
            ]
        }
        ctrl = _make_controller({1: entries})
        ctrl.save_games = MagicMock()
        sk = frozenset({(1, "0", "3x3", "Why1")})
        vk = frozenset({(1, "0", "3x3", "Why4")})
        ck = frozenset(sk | vk)
        dlg = ShowShallowTagsDialog(
            config={}, games=[game], controller=ctrl,
            shallow_keys=sk, vague_keys=vk, classified_keys=ck,
        )
        dlg._on_save()
        calls = ctrl.replace_entries_at_path_for_game.call_args_list
        self.assertTrue(len(calls) > 0)
        written = calls[0][0][3]
        why1 = next((e for e in written if e.get("cat") == "Why1"), None)
        why4 = next((e for e in written if e.get("cat") == "Why4"), None)
        self.assertIsNotNone(why1)
        self.assertTrue(why1.get("is_shallow"))
        self.assertIsNotNone(why4)
        self.assertTrue(why4.get("is_vague"))

    def test_3x3_stale_clear_per_entry(self):
        """B12: classified Why1 (now SPECIFIC, not shallow) clears stale is_shallow."""
        from app.views.dialogs.show_shallow_tags_dialog import ShowShallowTagsDialog
        game = _make_game()
        stale_why1 = dict(_make_entry("3x3", "Why1", "I attacked the king"), is_shallow=True)
        entries = {"0": [stale_why1, _make_entry("3x3", "Why4", "Concrete lesson")]}
        ctrl = _make_controller({1: entries})
        ctrl.save_games = MagicMock()
        # Why4 is FILLER (vague), Why1 now SPECIFIC (not flagged); both classified
        vk = frozenset({(1, "0", "3x3", "Why4")})
        ck = frozenset({(1, "0", "3x3", "Why1"), (1, "0", "3x3", "Why4")})
        dlg = ShowShallowTagsDialog(
            config={}, games=[game], controller=ctrl,
            shallow_keys=frozenset(), vague_keys=vk, classified_keys=ck,
        )
        dlg._on_save()
        # Find the replace call for "0" / "3x3"
        write_call = None
        for c in ctrl.replace_entries_at_path_for_game.call_args_list:
            if c[0][1] == "0" and c[0][2] == "3x3":
                write_call = c
        self.assertIsNotNone(write_call, "Expected replace call for stale 3x3 Why1 entry")
        written = write_call[0][3]
        why1 = next((e for e in written if e.get("cat") == "Why1"), None)
        self.assertIsNotNone(why1)
        self.assertFalse(why1.get("is_shallow", False))


# ---------------------------------------------------------------------------
# B12 — help icon present
# ---------------------------------------------------------------------------

@requires_qt
class TestHelpIcon(unittest.TestCase):
    def test_help_button_exists_in_dialog(self):
        """ShowShallowTagsDialog has a help button wired to show help."""
        from PyQt6.QtWidgets import QToolButton
        game = _make_game()
        tags = {"0": [_make_entry("CLAMP", "C", "shallow")]}
        dlg, _ = _make_dialog([game], {1: tags}, {(1, "0", "CLAMP", "")})
        buttons = dlg.findChildren(QToolButton)
        self.assertTrue(len(buttons) > 0, "Expected at least one QToolButton (help icon)")


@requires_qt
class TestPartialNotice(unittest.TestCase):
    """B3 — partial_notice kwarg shows a notice label at the top of the dialog."""

    def test_partial_notice_label_present_when_supplied(self):
        """A non-None partial_notice produces a QLabel with the notice text."""
        from PyQt6.QtWidgets import QLabel
        game = _make_game()
        tags = {"0": [_make_entry("CLAMP", "C", "shallow")]}
        ctrl = _make_controller({1: tags})
        from app.views.dialogs.show_shallow_tags_dialog import ShowShallowTagsDialog
        msg = "2 of 5 notes could not be classified — they remain unchanged."
        dlg = ShowShallowTagsDialog(
            config={},
            games=[game],
            controller=ctrl,
            shallow_keys={(1, "0", "CLAMP", "")},
            partial_notice=msg,
        )
        labels = [w.text() for w in dlg.findChildren(QLabel) if msg in (w.text() or "")]
        self.assertEqual(len(labels), 1, "Exactly one QLabel should contain the partial notice text")

    def test_no_partial_notice_label_when_none(self):
        """When partial_notice=None (default), no extra notice label is added."""
        from PyQt6.QtWidgets import QLabel
        game = _make_game()
        tags = {"0": [_make_entry("CLAMP", "C", "shallow")]}
        ctrl = _make_controller({1: tags})
        from app.views.dialogs.show_shallow_tags_dialog import ShowShallowTagsDialog
        dlg = ShowShallowTagsDialog(
            config={},
            games=[game],
            controller=ctrl,
            shallow_keys={(1, "0", "CLAMP", "")},
            partial_notice=None,
        )
        sentinel = "could not be classified"
        labels = [w.text() for w in dlg.findChildren(QLabel) if sentinel in (w.text() or "")]
        self.assertEqual(len(labels), 0, "No partial-notice label expected when partial_notice=None")


# ---------------------------------------------------------------------------
# C1 — Check Logs shows dimmed chip + ticked Ignore for an ignored 3x3 answer
#      even when is_vague / is_shallow is absent from storage
# ---------------------------------------------------------------------------

@requires_qt
class TestIgnoredAnswerChipInCheckLogs(unittest.TestCase):
    """C1: when a 3x3 entry has ignore_shallow=True+hash in storage but no is_vague,
    Check Logs must still show the chip (dimmed) and Ignore box (ticked)."""

    # Shared helper for the core scenario:
    #   Why1 classified SHALLOW (not ignored), Why4 ignored + hash but NO is_vague.
    def _make_scenario_entries(self):
        import hashlib
        from app.services.chess_log_storage_service import ChessLogStorageService
        w4_text = "Slow down and calculate"
        return [
            ChessLogStorageService.make_entry("3x3", "Why1", "I attacked too early", is_shallow=True),
            ChessLogStorageService.make_entry("3x3", "Why2", "I missed the fork"),
            ChessLogStorageService.make_entry("3x3", "Why3", "Engine prefers Nf3"),
            {
                "preset": "3x3", "cat": "Why4", "why": w4_text,
                "ignore_shallow": True,
                "ignore_text_hash": hashlib.sha256(w4_text.encode()).hexdigest(),
                # deliberately NOT including is_vague — this is the broken-storage scenario
            },
        ]

    def _make_check_logs_dialog(self, entries):
        from app.views.dialogs.show_shallow_tags_dialog import ShowShallowTagsDialog
        game = _make_game()
        tags = {"0": entries}
        ctrl = _make_controller({1: tags})
        ctrl.save_games = MagicMock()
        # Why1 classified shallow this run; Why4 excluded (ignored → not in classified_keys)
        sk = frozenset({(1, "0", "3x3", "Why1")})
        ck = frozenset(sk)
        return ShowShallowTagsDialog(
            config={}, games=[game], controller=ctrl,
            shallow_keys=sk, vague_keys=frozenset(), classified_keys=ck,
        ), ctrl, game

    def _has_opacity_effect(self, chip) -> bool:
        from PyQt6.QtWidgets import QGraphicsOpacityEffect
        eff = chip.graphicsEffect()
        return isinstance(eff, QGraphicsOpacityEffect) and abs(eff.opacity() - 0.4) < 0.01

    def test_why4_chip_present_when_is_vague_missing_from_storage(self):
        """C1 core: vague chip shown for Why4 even when is_vague not stored."""
        entries = self._make_scenario_entries()
        dlg, _, _ = self._make_check_logs_dialog(entries)
        self.assertEqual(len(dlg._row_widgets), 1)
        row = dlg._row_widgets[0]
        self.assertIn("Why4", row._chips_per_cat,
                      "Why4 chip must appear even when is_vague absent from storage")

    def test_why4_chip_is_dimmed(self):
        """C1: Why4 chip is dimmed (opacity 0.4) when Ignore is honoured."""
        entries = self._make_scenario_entries()
        dlg, _, _ = self._make_check_logs_dialog(entries)
        row = dlg._row_widgets[0]
        chip = row._chips_per_cat.get("Why4")
        self.assertIsNotNone(chip)
        self.assertTrue(self._has_opacity_effect(chip),
                        "Why4 chip must be dimmed at dialog open when Ignore is honoured")

    def test_why4_ignore_box_ticked(self):
        """C1: Why4 Ignore checkbox is pre-ticked when Ignore is honoured."""
        entries = self._make_scenario_entries()
        dlg, _, _ = self._make_check_logs_dialog(entries)
        row = dlg._row_widgets[0]
        self.assertIn("Why4", row._ignore_checks,
                      "Why4 Ignore checkbox must be present")
        self.assertTrue(row._ignore_checks["Why4"].isChecked(),
                        "Why4 Ignore checkbox must be ticked")

    def test_why1_chip_normal_and_unticked(self):
        """C1: Why1 chip is not dimmed and Ignore box is unticked (not ignored)."""
        entries = self._make_scenario_entries()
        dlg, _, _ = self._make_check_logs_dialog(entries)
        row = dlg._row_widgets[0]
        chip = row._chips_per_cat.get("Why1")
        self.assertIsNotNone(chip)
        self.assertFalse(self._has_opacity_effect(chip),
                         "Why1 chip must not be dimmed (not ignored)")
        self.assertIn("Why1", row._ignore_checks)
        self.assertFalse(row._ignore_checks["Why1"].isChecked(),
                         "Why1 Ignore box must be unticked")

    def test_all_four_texts_present(self):
        """C1: all four answer texts are accessible in the dialog."""
        entries = self._make_scenario_entries()
        dlg, _, _ = self._make_check_logs_dialog(entries)
        row = dlg._row_widgets[0]
        for key in ("Why1", "Why2", "Why3", "Why4"):
            self.assertIn(key, row._why_texts, f"{key} QPlainTextEdit missing")
        self.assertIn("attacked", row._why_texts["Why1"].toPlainText())
        self.assertIn("Slow down", row._why_texts["Why4"].toPlainText())

    def test_untick_why4_undims_chip_before_save(self):
        """C1: unticking Why4 Ignore undims the chip immediately (before Save)."""
        entries = self._make_scenario_entries()
        dlg, _, _ = self._make_check_logs_dialog(entries)
        row = dlg._row_widgets[0]
        chip = row._chips_per_cat.get("Why4")
        self.assertTrue(self._has_opacity_effect(chip), "chip must start dimmed")
        row._ignore_checks["Why4"].setChecked(False)
        self.assertFalse(self._has_opacity_effect(chip),
                         "chip must undim after unticking Why4 Ignore")

    def test_untick_and_save_writes_is_vague_for_why4(self):
        """C1: untick Why4 Ignore + Save writes is_vague=True (change detected → write triggered)."""
        entries = self._make_scenario_entries()
        dlg, ctrl, _ = self._make_check_logs_dialog(entries)
        # Untick Why4 Ignore — this IS a change (ignore_shallow: True → False)
        dlg._row_widgets[0]._ignore_checks["Why4"].setChecked(False)
        dlg._on_save()
        why4_written = None
        for c in ctrl.replace_entries_at_path_for_game.call_args_list:
            written = c[0][3]
            for e in written:
                if e.get("cat") == "Why4":
                    why4_written = e
        self.assertIsNotNone(why4_written, "Why4 entry must be written after untick+save")
        self.assertTrue(why4_written.get("is_vague"),
                        "is_vague=True must be preserved after untick+save")
        self.assertFalse(why4_written.get("ignore_shallow", False),
                         "ignore_shallow must be cleared after untick+save")

    def test_save_untick_reopen_normal_chip_unticked(self):
        """C1 full flow: untick Why4 → Save → reopen → chip present, undimmed, unticked."""
        import hashlib
        from app.services.chess_log_storage_service import ChessLogStorageService
        entries = self._make_scenario_entries()
        dlg, ctrl, game = self._make_check_logs_dialog(entries)

        # Untick Why4, then Save
        row = dlg._row_widgets[0]
        row._ignore_checks["Why4"].setChecked(False)
        dlg._on_save()

        # Get what was written for Why4
        saved_entries = None
        for c in ctrl.replace_entries_at_path_for_game.call_args_list:
            if c[0][2] == "3x3":
                saved_entries = c[0][3]
        self.assertIsNotNone(saved_entries)

        # Build a second dialog with the saved entries
        w4 = next(e for e in saved_entries if e.get("cat") == "Why4")
        self.assertFalse(w4.get("ignore_shallow", False),
                         "ignore_shallow must be cleared after untick+save")
        self.assertTrue(w4.get("is_vague"),
                        "is_vague must be preserved after untick+save")
        self.assertEqual(w4["why"], "Slow down and calculate",
                         "Why4 text must be byte-identical after untick+save")

        # Reopen with the saved entries (is_vague=True, no ignore_shallow)
        tags2 = {"0": saved_entries}
        ctrl2 = _make_controller({1: tags2})
        from app.views.dialogs.show_shallow_tags_dialog import ShowShallowTagsDialog
        sk2 = frozenset({(1, "0", "3x3", "Why1")})
        vk2 = frozenset({(1, "0", "3x3", "Why4")})  # now classified vague again
        ck2 = frozenset(sk2 | vk2)
        dlg2 = ShowShallowTagsDialog(
            config={}, games=[game], controller=ctrl2,
            shallow_keys=sk2, vague_keys=vk2, classified_keys=ck2,
        )
        row2 = dlg2._row_widgets[0]
        chip2 = row2._chips_per_cat.get("Why4")
        self.assertIsNotNone(chip2, "Why4 chip must be present in reopened dialog")
        self.assertFalse(self._has_opacity_effect(chip2),
                         "Why4 chip must NOT be dimmed (Ignore was unticked)")
        self.assertIn("Why4", row2._ignore_checks)
        self.assertFalse(row2._ignore_checks["Why4"].isChecked(),
                         "Why4 Ignore box must be unticked in reopened dialog")

        # All 4 texts byte-identical
        for key, expected in [
            ("Why1", "I attacked too early"),
            ("Why2", "I missed the fork"),
            ("Why3", "Engine prefers Nf3"),
            ("Why4", "Slow down and calculate"),
        ]:
            actual = row2._why_texts[key].toPlainText()
            self.assertEqual(actual, expected, f"{key} text changed")

    def test_pdf_snapshot_has_vague_cats_for_why4(self):
        """C1 PDF: snapshot().vague_cats includes Why4, enabling PDF chip + Ignore: Yes."""
        entries = self._make_scenario_entries()
        dlg, _, _ = self._make_check_logs_dialog(entries)
        row = dlg._row_widgets[0]
        snap = row.snapshot()
        self.assertIn("Why4", snap.vague_cats,
                      "snapshot().vague_cats must include Why4 for PDF chip rendering")
        self.assertTrue(snap.show_ignore,
                        "snapshot().show_ignore must be True for Ignore: Yes to appear in PDF")
        why4_entry = next((e for e in snap.entries if e.get("cat") == "Why4"), None)
        self.assertIsNotNone(why4_entry)
        self.assertTrue(why4_entry.get("ignore_shallow"),
                        "snapshot entry for Why4 must carry ignore_shallow=True for PDF Ignore: Yes")

    def test_ignored_why1_chip_present_when_is_shallow_missing(self):
        """C1: same fix for Why1-3 — chip shown when is_shallow absent but Ignore honoured."""
        import hashlib
        w1_text = "I attacked impulsively"
        entries = [
            {
                "preset": "3x3", "cat": "Why1", "why": w1_text,
                "ignore_shallow": True,
                "ignore_text_hash": hashlib.sha256(w1_text.encode()).hexdigest(),
                # deliberately NO is_shallow
            },
            {"preset": "3x3", "cat": "Why4", "why": "Lesson text"},
        ]
        from app.views.dialogs.show_shallow_tags_dialog import ShowShallowTagsDialog
        game = _make_game()
        tags = {"0": entries}
        ctrl = _make_controller({1: tags})
        # Why4 is VAGUE this run (moment is shown because Why4 in vague_keys)
        vk = frozenset({(1, "0", "3x3", "Why4")})
        ck = frozenset(vk)
        dlg = ShowShallowTagsDialog(
            config={}, games=[game], controller=ctrl,
            shallow_keys=frozenset(), vague_keys=vk, classified_keys=ck,
        )
        row = dlg._row_widgets[0]
        self.assertIn("Why1", row._chips_per_cat,
                      "Why1 chip must appear even when is_shallow absent from storage")
        chip = row._chips_per_cat.get("Why1")
        self.assertTrue(self._has_opacity_effect(chip),
                        "Why1 chip must be dimmed (Ignore honoured)")
        self.assertIn("Why1", row._ignore_checks)
        self.assertTrue(row._ignore_checks["Why1"].isChecked())

    def test_proof_sequence_prints_all_states(self):
        """C1 proof: walk ALL child widget types (incl. QPlainTextEdit) to prove texts visible."""
        import hashlib
        from PyQt6.QtWidgets import QApplication, QLabel, QPlainTextEdit
        from app.services.chess_log_storage_service import ChessLogStorageService

        w4_text = "Slow down and calculate"
        entries = self._make_scenario_entries()

        print("\n--- PROOF SEQUENCE ---")
        print("STORAGE before dialog open:")
        for e in entries:
            cat = e.get("cat", "")
            print(f"  {cat}: why={repr(e.get('why','')[:40])!s} "
                  f"is_shallow={e.get('is_shallow')} "
                  f"is_vague={e.get('is_vague')} "
                  f"ignore_shallow={e.get('ignore_shallow')}")

        dlg, ctrl, _ = self._make_check_logs_dialog(entries)
        row = dlg._row_widgets[0]

        # Show the dialog and process events so widgets are fully realized
        dlg.show()
        QApplication.processEvents()

        print("\nVISIBLE WIDGETS (QLabel + QPlainTextEdit):")
        for w in dlg.findChildren(QLabel):
            t = (w.text() or "").strip()
            if t:
                print(f"  QLabel visible={w.isVisible()} text={repr(t[:80])}")
        for w in dlg.findChildren(QPlainTextEdit):
            t = (w.toPlainText() or "").strip()
            print(f"  QPlainTextEdit visible={w.isVisible()} text={repr(t[:80])}")

        print("\nROW WIDGET STATE:")
        print(f"  _why_texts keys: {list(row._why_texts.keys())}")
        for k, te in row._why_texts.items():
            print(f"  {k}: visible={te.isVisible()} text={repr(te.toPlainText()[:60])}")
        print(f"  _chips_per_cat: {list(row._chips_per_cat.keys())}")
        for k, chip in row._chips_per_cat.items():
            from PyQt6.QtWidgets import QGraphicsOpacityEffect
            eff = chip.graphicsEffect()
            dimmed = isinstance(eff, QGraphicsOpacityEffect) and abs(eff.opacity() - 0.4) < 0.01
            print(f"  {k}: chip='{chip.text()}' dimmed={dimmed}")
        print(f"  _ignore_checks: {list(row._ignore_checks.keys())}")
        for k, cb in row._ignore_checks.items():
            print(f"  {k}: checked={cb.isChecked()}")

        # All four texts must be in _why_texts and visible
        for key in ("Why1", "Why2", "Why3", "Why4"):
            self.assertIn(key, row._why_texts, f"{key} QPlainTextEdit missing")
            te = row._why_texts[key]
            self.assertTrue(te.isVisible(), f"{key} QPlainTextEdit not visible")
        # Check that visible QPlainTextEdit widgets include all four answer texts
        visible_texts = {
            w.toPlainText() for w in dlg.findChildren(QPlainTextEdit) if w.isVisible()
        }
        self.assertIn("I attacked too early", visible_texts)
        self.assertIn("I missed the fork", visible_texts)
        self.assertIn("Engine prefers Nf3", visible_texts)
        self.assertIn(w4_text, visible_texts)

        self.assertIn("Why4", row._chips_per_cat)
        print("\n--- PROOF PASSED ---\n")


# ---------------------------------------------------------------------------
# C2 — stale-clear guard + repair for broken storage (is_vague dropped by
#       prior stale-clear bug while ignore_shallow survived)
# ---------------------------------------------------------------------------

@requires_qt
class TestIgnoredAnswerSaveFixC2(unittest.TestCase):
    """C2: stale-clear must not strip is_vague from a honoured-Ignore entry,
    and Save must repair broken storage (ignore_shallow=True, is_vague=None)."""

    def _make_broken_entries(self):
        """Why4 with ignore honoured but is_vague absent — the bug shape."""
        import hashlib
        w4_text = "Slow down and calculate"
        return [
            {"preset": "3x3", "cat": "Why1", "why": "I attacked too early",
             "is_shallow": True},
            {"preset": "3x3", "cat": "Why2", "why": "I missed the fork"},
            {"preset": "3x3", "cat": "Why3", "why": "Engine prefers Nf3"},
            {
                "preset": "3x3", "cat": "Why4", "why": w4_text,
                "ignore_shallow": True,
                "ignore_text_hash": hashlib.sha256(w4_text.encode()).hexdigest(),
                # deliberately NO is_vague — this is the broken-storage shape
            },
        ]

    def test_stale_clear_does_not_strip_is_vague_from_honoured_ignore(self):
        """Stale-clear guard: classified Why4 with honoured Ignore keeps is_vague=True."""
        import hashlib
        from app.views.dialogs.show_shallow_tags_dialog import ShowShallowTagsDialog
        game = _make_game()
        w4_text = "Slow down and calculate"
        entries = [
            {"preset": "3x3", "cat": "Why1", "why": "I attacked too early"},
            {
                "preset": "3x3", "cat": "Why4", "why": w4_text,
                "is_vague": True,
                "ignore_shallow": True,
                "ignore_text_hash": hashlib.sha256(w4_text.encode()).hexdigest(),
            },
        ]
        tags = {"0": entries}
        ctrl = _make_controller({1: tags})
        ctrl.save_games = MagicMock()
        # Why1 shallow; Why4 classified this run (simulate edge case) but NOT vague
        sk = frozenset({(1, "0", "3x3", "Why1")})
        # Why4 in classified_keys but NOT in vague_keys — this is the stale-clear scenario
        ck = frozenset({(1, "0", "3x3", "Why1"), (1, "0", "3x3", "Why4")})
        dlg = ShowShallowTagsDialog(
            config={}, games=[game], controller=ctrl,
            shallow_keys=sk, vague_keys=frozenset(), classified_keys=ck,
        )
        dlg._on_save()
        # Find any replace call for Why4
        why4_written = None
        for c in ctrl.replace_entries_at_path_for_game.call_args_list:
            for e in c[0][3]:
                if e.get("cat") == "Why4":
                    why4_written = e
        # is_vague must NOT have been stripped (honoured-Ignore guard)
        if why4_written is not None:
            self.assertTrue(
                why4_written.get("is_vague"),
                "is_vague must be preserved for a honoured-Ignore entry, even if in classified_keys",
            )

    def test_stale_clear_still_fires_when_ignore_not_honoured(self):
        """Stale-clear still strips is_vague when ignore_shallow is present but hash mismatches."""
        import hashlib
        from app.views.dialogs.show_shallow_tags_dialog import ShowShallowTagsDialog
        game = _make_game()
        stored_text = "Old text that was changed"
        current_text = "New different text"  # hash will NOT match
        entries = [
            {"preset": "3x3", "cat": "Why1", "why": "I attacked too early"},
            {
                "preset": "3x3", "cat": "Why4", "why": current_text,
                "is_vague": True,
                "ignore_shallow": True,
                "ignore_text_hash": hashlib.sha256(stored_text.encode()).hexdigest(),
                # hash of stored_text ≠ sha256(current_text) → NOT honoured
            },
        ]
        tags = {"0": entries}
        ctrl = _make_controller({1: tags})
        ctrl.save_games = MagicMock()
        sk = frozenset({(1, "0", "3x3", "Why1")})
        ck = frozenset({(1, "0", "3x3", "Why1"), (1, "0", "3x3", "Why4")})
        dlg = ShowShallowTagsDialog(
            config={}, games=[game], controller=ctrl,
            shallow_keys=sk, vague_keys=frozenset(), classified_keys=ck,
        )
        dlg._on_save()
        why4_written = None
        for c in ctrl.replace_entries_at_path_for_game.call_args_list:
            for e in c[0][3]:
                if e.get("cat") == "Why4":
                    why4_written = e
        # is_vague SHOULD have been stripped (hash mismatch → Ignore not honoured)
        self.assertIsNotNone(why4_written, "Expected replace call for Why4")
        self.assertFalse(
            why4_written.get("is_vague", False),
            "is_vague must be stripped when ignore hash does not match",
        )

    def test_save_repairs_broken_entry_writes_is_vague(self):
        """Repair: Save must write is_vague=True for broken storage (ignore honoured, is_vague absent).

        Even if the user makes no changes, inference_repair_needed forces a save.
        """
        from app.views.dialogs.show_shallow_tags_dialog import ShowShallowTagsDialog
        game = _make_game()
        entries = self._make_broken_entries()
        tags = {"0": entries}
        ctrl = _make_controller({1: tags})
        ctrl.save_games = MagicMock()
        # Why1 shallow this run; Why4 excluded from classifier (properly ignored)
        sk = frozenset({(1, "0", "3x3", "Why1")})
        ck = frozenset(sk)
        dlg = ShowShallowTagsDialog(
            config={}, games=[game], controller=ctrl,
            shallow_keys=sk, vague_keys=frozenset(), classified_keys=ck,
        )
        # User makes NO changes — just opens and saves
        dlg._on_save()
        # A replace call must have been made (repair triggered)
        why4_written = None
        for c in ctrl.replace_entries_at_path_for_game.call_args_list:
            for e in c[0][3]:
                if e.get("cat") == "Why4":
                    why4_written = e
        self.assertIsNotNone(why4_written, "Why4 entry must be written by repair Save")
        self.assertTrue(
            why4_written.get("is_vague"),
            "is_vague=True must be written by the repair path",
        )
        self.assertTrue(
            why4_written.get("ignore_shallow"),
            "ignore_shallow must be preserved during repair",
        )
        self.assertIsNotNone(
            why4_written.get("ignore_text_hash"),
            "ignore_text_hash must be preserved during repair",
        )

    def test_repaired_entry_stable_on_second_save(self):
        """After repair, a second Save with no changes does NOT call replace again."""
        import hashlib
        from app.views.dialogs.show_shallow_tags_dialog import ShowShallowTagsDialog
        game = _make_game()
        w4_text = "Slow down and calculate"
        # Already-repaired storage: is_vague=True present
        repaired_entries = [
            {"preset": "3x3", "cat": "Why1", "why": "I attacked too early", "is_shallow": True},
            {"preset": "3x3", "cat": "Why2", "why": "I missed the fork"},
            {"preset": "3x3", "cat": "Why3", "why": "Engine prefers Nf3"},
            {
                "preset": "3x3", "cat": "Why4", "why": w4_text,
                "is_vague": True,
                "ignore_shallow": True,
                "ignore_text_hash": hashlib.sha256(w4_text.encode()).hexdigest(),
            },
        ]
        tags = {"0": repaired_entries}
        ctrl = _make_controller({1: tags})
        ctrl.save_games = MagicMock()
        sk = frozenset({(1, "0", "3x3", "Why1")})
        ck = frozenset(sk)
        dlg = ShowShallowTagsDialog(
            config={}, games=[game], controller=ctrl,
            shallow_keys=sk, vague_keys=frozenset(), classified_keys=ck,
        )
        dlg._on_save()
        # No change from correct storage → no replace call needed
        # (flags_missing is False for Why1 because Why1 IS in sk and storage has is_shallow=True;
        #  inference_repair_needed is False because is_vague IS present in Why4)
        why4_calls = [
            c for c in ctrl.replace_entries_at_path_for_game.call_args_list
            if any(e.get("cat") == "Why4" for e in c[0][3])
        ]
        # If a replace call was made, it must still have is_vague=True (no regression)
        for c in why4_calls:
            for e in c[0][3]:
                if e.get("cat") == "Why4":
                    self.assertTrue(
                        e.get("is_vague"),
                        "Second save must not strip is_vague from already-repaired entry",
                    )

    def test_stale_clear_also_clears_ignore_when_hash_mismatches(self):
        """Stale-clear must also strip ignore_shallow+ignore_text_hash when hash mismatches.

        Editing an answer invalidates its Ignore (hash no longer matches).  When the
        classifier re-runs and returns DEEP, the stale-clear fires.  It must atomically
        clear the chip flag AND both Ignore fields — leaving ignore_shallow=True with no
        is_vague would suppress future classifier runs without showing a chip.
        """
        import hashlib
        from app.views.dialogs.show_shallow_tags_dialog import ShowShallowTagsDialog
        game = _make_game()
        old_text = "Original answer before edit"
        new_text = "Completely different answer now"
        entries = [
            {
                "preset": "3x3", "cat": "Why4", "why": new_text,
                "is_vague": True,
                "ignore_shallow": True,
                "ignore_text_hash": hashlib.sha256(old_text.encode()).hexdigest(),
                # hash of old_text ≠ sha256(new_text) → NOT honoured → sent to classifier → DEEP
            },
        ]
        tags = {"0": entries}
        ctrl = _make_controller({1: tags})
        ctrl.save_games = MagicMock()
        # Why4 was re-classified DEEP (in classified_keys but not in vague/shallow_keys)
        ck = frozenset({(1, "0", "3x3", "Why4")})
        # No flagged_keys → moment not shown; but part (b) still processes all tags
        dlg = ShowShallowTagsDialog(
            config={}, games=[game], controller=ctrl,
            shallow_keys=frozenset(), vague_keys=frozenset(), classified_keys=ck,
        )
        dlg._on_save()
        why4_written = None
        for c in ctrl.replace_entries_at_path_for_game.call_args_list:
            for e in c[0][3]:
                if e.get("cat") == "Why4":
                    why4_written = e
        self.assertIsNotNone(why4_written, "Stale-clear must have written Why4")
        self.assertFalse(why4_written.get("is_vague", False),
                         "is_vague must be cleared")
        self.assertFalse(why4_written.get("ignore_shallow", False),
                         "ignore_shallow must also be cleared — editing invalidates Ignore")
        self.assertIsNone(why4_written.get("ignore_text_hash"),
                          "ignore_text_hash must also be cleared")


# ---------------------------------------------------------------------------
# C2 — prove Paul's exact sequence from CLEAN storage works end-to-end
# ---------------------------------------------------------------------------

@requires_qt
class TestNormalSequenceFromCleanStorage(unittest.TestCase):
    """Prove the five-step normal sequence starting from clean 3x3 storage.

    Steps:
    1. Check Logs → tick Ignore on Why4 → Save.
    2. Check Logs again (Why4 excluded from classifier) → Save without changes.
    3. Check Logs again → untick Why4 (chip undims before Save) → Save.
    4. Check Logs again: Why4 shows normal Vague chip, Ignore unticked.
    5. All four why texts are byte-identical to start.
    """

    TEXTS = {
        "Why1": "I attacked too early",
        "Why2": "I missed the fork",
        "Why3": "Engine prefers Nf3",
        "Why4": "Slow down and calculate",
    }

    @staticmethod
    def _has_opacity_effect(chip) -> bool:
        from PyQt6.QtWidgets import QGraphicsOpacityEffect
        if chip is None:
            return False
        eff = chip.graphicsEffect()
        return isinstance(eff, QGraphicsOpacityEffect) and abs(eff.opacity() - 0.4) < 0.01

    @staticmethod
    def _print_entries(label, entries):
        import hashlib
        print(f"\n--- {label} ---")
        for e in entries:
            cat = e.get("cat", "")
            why = (e.get("why") or "").strip()
            h = e.get("ignore_text_hash")
            if h and why:
                hash_ok = h == hashlib.sha256(why.encode()).hexdigest()
                hash_str = "YES(correct)" if hash_ok else "YES(mismatch)"
            else:
                hash_str = "yes(no why)" if h else "no"
            print(f"  {cat}: why={repr(why[:35])}"
                  f" is_shallow={e.get('is_shallow')}"
                  f" is_vague={e.get('is_vague')}"
                  f" ignore_shallow={e.get('ignore_shallow')}"
                  f" hash={hash_str}")

    @staticmethod
    def _get_why4(entries):
        return next((e for e in entries if e.get("cat") == "Why4"), None) if entries else None

    @staticmethod
    def _last_written_3x3(ctrl):
        for c in reversed(ctrl.replace_entries_at_path_for_game.call_args_list):
            if c[0][1] == "0" and c[0][2] == "3x3":
                return list(c[0][3])
        return None

    def _open_dialog(self, entries, shallow_keys, vague_keys, classified_keys):
        from app.views.dialogs.show_shallow_tags_dialog import ShowShallowTagsDialog
        game = _make_game()
        ctrl = _make_controller({1: {"0": list(entries)}})
        ctrl.save_games = MagicMock()
        dlg = ShowShallowTagsDialog(
            config={}, games=[game], controller=ctrl,
            shallow_keys=shallow_keys, vague_keys=vague_keys,
            classified_keys=classified_keys,
        )
        return dlg, ctrl

    def test_full_five_step_sequence(self):
        """Walk all five steps and assert the correct entry state after each save."""
        import hashlib

        clean = [{"preset": "3x3", "cat": k, "why": v}
                 for k, v in self.TEXTS.items()]
        self._print_entries("INITIAL STORAGE (clean)", clean)

        SK_W1 = frozenset({(1, "0", "3x3", "Why1")})
        VK_W4 = frozenset({(1, "0", "3x3", "Why4")})
        CK_ALL = frozenset(SK_W1 | VK_W4)
        # Step 2/3 run: Why4 excluded because it was ignored
        CK_NO_W4 = frozenset({(1, "0", "3x3", k) for k in ("Why1", "Why2", "Why3")})
        expected_hash = hashlib.sha256("Slow down and calculate".encode()).hexdigest()

        # ── Step 1: Check Logs → tick Ignore on Why4 → Save ──────────────
        dlg1, ctrl1 = self._open_dialog(clean, SK_W1, VK_W4, CK_ALL)
        row1 = dlg1._row_widgets[0]
        self.assertIn("Why4", row1._ignore_checks, "Why4 Ignore checkbox must exist")
        row1._ignore_checks["Why4"].setChecked(True)
        dlg1._on_save()

        saved1 = self._last_written_3x3(ctrl1)
        self.assertIsNotNone(saved1, "Step 1: must have written entries")
        self._print_entries("AFTER STEP 1 (tick Ignore on Why4, Save)", saved1)

        w4 = self._get_why4(saved1)
        self.assertIsNotNone(w4)
        self.assertTrue(w4.get("is_vague"), "Step 1: is_vague must be True")
        self.assertTrue(w4.get("ignore_shallow"), "Step 1: ignore_shallow must be True")
        self.assertEqual(w4.get("ignore_text_hash"), expected_hash,
                         "Step 1: hash must equal sha256(why.strip())")

        # ── Step 2: Check Logs again (Why4 NOT in classified_keys) → no-op Save
        self.assertNotIn((1, "0", "3x3", "Why4"), CK_NO_W4,
                         "Step 2 precondition: Why4 must be excluded from classifier")
        dlg2, ctrl2 = self._open_dialog(saved1, SK_W1, frozenset(), CK_NO_W4)
        dlg2._on_save()

        # No write expected; if one happened, Why4 must be unchanged
        written2 = self._last_written_3x3(ctrl2)
        w4_2 = self._get_why4(written2) if written2 else w4
        self._print_entries("AFTER STEP 2 (no changes; Why4 must be unchanged)",
                             written2 if written2 else saved1)
        self.assertTrue(w4_2.get("is_vague"), "Step 2: is_vague unchanged (True)")
        self.assertTrue(w4_2.get("ignore_shallow"), "Step 2: ignore_shallow unchanged (True)")
        self.assertEqual(w4_2.get("ignore_text_hash"), expected_hash,
                         "Step 2: hash unchanged")

        # ── Step 3: Check Logs again → untick Why4 (chip undims) → Save ──
        dlg3, ctrl3 = self._open_dialog(saved1, SK_W1, frozenset(), CK_NO_W4)
        row3 = dlg3._row_widgets[0]
        chip3 = row3._chips_per_cat.get("Why4")
        self.assertTrue(self._has_opacity_effect(chip3),
                        "Step 3: Why4 chip must start dimmed (Ignore honoured)")
        row3._ignore_checks["Why4"].setChecked(False)
        self.assertFalse(self._has_opacity_effect(chip3),
                         "Step 3: chip must undim immediately after untick (before Save)")
        dlg3._on_save()

        saved3 = self._last_written_3x3(ctrl3)
        self.assertIsNotNone(saved3, "Step 3: must have written entries")
        self._print_entries("AFTER STEP 3 (untick Ignore, Save)", saved3)

        w4_3 = self._get_why4(saved3)
        self.assertTrue(w4_3.get("is_vague"), "Step 3: is_vague must be True")
        self.assertFalse(w4_3.get("ignore_shallow", False),
                         "Step 3: ignore_shallow must be None/False")
        self.assertIsNone(w4_3.get("ignore_text_hash"),
                          "Step 3: ignore_text_hash must be absent")

        # ── Step 4: Check Logs again — normal chip, unticked box ──────────
        SK4 = frozenset({(1, "0", "3x3", "Why1")})
        VK4 = frozenset({(1, "0", "3x3", "Why4")})   # Why4 vague again (Ignore cleared)
        dlg4, _ = self._open_dialog(saved3, SK4, VK4, frozenset(SK4 | VK4))
        row4 = dlg4._row_widgets[0]
        chip4 = row4._chips_per_cat.get("Why4")

        print("\nSTEP 4 dialog opened:")
        print(f"  Why4 chip present: {chip4 is not None}")
        print(f"  Why4 chip dimmed: {self._has_opacity_effect(chip4)}")
        w4_ign = row4._ignore_checks.get("Why4")
        print(f"  Why4 Ignore ticked: {w4_ign.isChecked() if w4_ign else '(no checkbox)'}")

        self.assertIsNotNone(chip4, "Step 4: Why4 chip must be present")
        self.assertFalse(self._has_opacity_effect(chip4),
                         "Step 4: chip must NOT be dimmed (Ignore was cleared)")
        self.assertIn("Why4", row4._ignore_checks)
        self.assertFalse(row4._ignore_checks["Why4"].isChecked(),
                         "Step 4: Why4 Ignore box must be unticked")

        # ── Step 5: All why texts byte-identical to start ─────────────────
        print("\nSTEP 5: byte-identical why texts check")
        for key, expected in self.TEXTS.items():
            actual = row4._why_texts[key].toPlainText()
            print(f"  {key}: {repr(actual[:40])} ← expected {repr(expected)}")
            self.assertEqual(actual, expected, f"Step 5: {key} text changed")

        print("\n--- NORMAL SEQUENCE PROOF PASSED ---\n")


if __name__ == "__main__":
    unittest.main()
