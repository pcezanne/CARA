"""Tests for ShowTagsDialog.

Requires a working Qt platform plugin (CI uses QT_QPA_PLATFORM=offscreen).
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


_QT_OK = _qt_starts_cleanly()
requires_qt = unittest.skipUnless(_QT_OK, "Qt platform plugin unavailable")

if _QT_OK:
    from PyQt6.QtWidgets import QApplication, QCheckBox, QLabel, QPlainTextEdit, QScrollArea
    _APP = QApplication.instance() or QApplication(sys.argv[:1])

# ---------------------------------------------------------------------------
# Minimal PGN helpers
# ---------------------------------------------------------------------------

MAINLINE_PGN = (
    '[Event "T"][Site "?"][Date "2026.01.01"]'
    '[Round "?"][White "W"][Black "B"][Result "*"]\n\n'
    "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 *\n"
)

SECOND_PGN = (
    '[Event "T"][Site "?"][Date "2026.02.01"]'
    '[Round "?"][White "X"][Black "Y"][Result "1-0"]\n\n'
    "1. d4 d5 *\n"
)


def _make_game_data(pgn: str = MAINLINE_PGN, game_number: int = 1):
    from app.models.database_model import GameData
    return GameData(game_number=game_number, pgn=pgn)


def _make_controller(paths_data: dict):
    ctrl = MagicMock()
    ctrl.get_tags_for_game.return_value = paths_data
    ctrl.game_has_any_tags.return_value = bool(paths_data)
    ctrl.replace_entries_at_path_for_game = MagicMock()
    return ctrl


def _make_entry(preset, cat, why="", ignore_shallow=False):
    from app.services.chess_log_storage_service import ChessLogStorageService
    return ChessLogStorageService.make_entry(preset, cat, why, ignore_shallow=ignore_shallow)


def _make_dialog(paths_data: dict, pgn: str = MAINLINE_PGN):
    from app.views.dialogs.show_tags_dialog import ShowTagsDialog
    game_data = _make_game_data(pgn)
    ctrl = _make_controller(paths_data)
    return ShowTagsDialog({}, [game_data], ctrl), ctrl


# ---------------------------------------------------------------------------
# Row count and ordering
# ---------------------------------------------------------------------------

@requires_qt
class TestRowCount(unittest.TestCase):
    def test_one_row_per_move_preset_pair(self):
        # Move at path "0" has CLAMP, move at "0.0" has CLAMP+CCT → 3 rows
        paths_data = {
            "0": [_make_entry("CLAMP", "C")],
            "0.0": [
                _make_entry("CLAMP", "L"),
                _make_entry("CCT", "Threats"),
            ],
        }
        dlg, _ = _make_dialog(paths_data)
        # "0" → 1 row (CLAMP); "0.0" → 2 rows (CLAMP + CCT)
        self.assertEqual(len(dlg._row_widgets), 3)

    def test_three_clamp_rows_plus_one_cct(self):
        paths_data = {
            "0": [_make_entry("CLAMP", "C")],
            "0.0": [_make_entry("CLAMP", "L")],
            "0.0.0": [
                _make_entry("CLAMP", "M"),
                _make_entry("CCT", "Checks"),
            ],
        }
        dlg, _ = _make_dialog(paths_data)
        self.assertEqual(len(dlg._row_widgets), 4)

    def test_empty_tags_means_zero_rows(self):
        dlg, _ = _make_dialog({})
        self.assertEqual(len(dlg._row_widgets), 0)


@requires_qt
class TestRowOrdering(unittest.TestCase):
    def test_rows_sorted_by_ply_ascending(self):
        # "0" = ply 1 (White's first move), "0.0.0" = ply 3
        paths_data = {
            "0.0.0": [_make_entry("CLAMP", "A")],
            "0": [_make_entry("CLAMP", "C")],
            "0.0": [_make_entry("CLAMP", "L")],
        }
        dlg, _ = _make_dialog(paths_data)
        preset_labels = [rw._preset for rw in dlg._row_widgets]
        # All CLAMP rows sorted by ply — label is CLAMP for all; check via rows_data paths
        paths = [r[0] for r in dlg._rows_data]
        self.assertEqual(paths, ["0", "0.0", "0.0.0"])

    def test_preset_order_within_same_ply(self):
        # One move ("0") tagged with CLAMP and CCT
        paths_data = {
            "0": [
                _make_entry("CCT", "Threats"),
                _make_entry("CLAMP", "C"),
            ],
        }
        dlg, _ = _make_dialog(paths_data)
        presets = [r[1] for r in dlg._rows_data]
        # Should be CLAMP first, CCT second
        self.assertEqual(presets, ["CLAMP", "CCT"])


# ---------------------------------------------------------------------------
# 3x3 rows
# ---------------------------------------------------------------------------

@requires_qt
class TestThreeXThreeRow(unittest.TestCase):
    def test_3x3_row_counts_as_one_row(self):
        paths_data = {
            "0": [
                _make_entry("3x3", "Why1", "I wanted to develop"),
                _make_entry("3x3", "Why2", "It lost tempo"),
                _make_entry("3x3", "Why3", "Engine prefers Nf3"),
            ],
        }
        dlg, _ = _make_dialog(paths_data)
        self.assertEqual(len(dlg._row_widgets), 1)

    def test_3x3_row_has_no_checkboxes(self):
        paths_data = {
            "0": [_make_entry("3x3", "Why1", "text")],
        }
        dlg, _ = _make_dialog(paths_data)
        row = dlg._row_widgets[0]
        self.assertEqual(len(row._checkboxes), 0)

    def test_3x3_row_text_contains_all_four_sentences(self):
        paths_data = {
            "0": [
                _make_entry("3x3", "Why1", "I wanted to develop"),
                _make_entry("3x3", "Why2", "It lost tempo"),
                _make_entry("3x3", "Why3", "Engine prefers Nf3"),
                _make_entry("3x3", "Why4", "Slow down next time"),
            ],
        }
        dlg, _ = _make_dialog(paths_data)
        row = dlg._row_widgets[0]
        self.assertIn("Why1", row._why_texts)
        self.assertIn("Why2", row._why_texts)
        self.assertIn("Why3", row._why_texts)
        self.assertIn("Why4", row._why_texts)
        self.assertIn("develop", row._why_texts["Why1"].toPlainText())
        self.assertIn("tempo", row._why_texts["Why2"].toPlainText())
        self.assertIn("Nf3", row._why_texts["Why3"].toPlainText())
        self.assertIn("Slow down", row._why_texts["Why4"].toPlainText())


# ---------------------------------------------------------------------------
# Always-editable: checkboxes and text are editable on open
# ---------------------------------------------------------------------------

@requires_qt
class TestAlwaysEditable(unittest.TestCase):
    def test_checkboxes_enabled_on_open(self):
        paths_data = {"0": [_make_entry("CLAMP", "C")]}
        dlg, _ = _make_dialog(paths_data)
        row = dlg._row_widgets[0]
        for cb in row._checkboxes.values():
            self.assertTrue(cb.isEnabled())

    def test_text_editable_on_open(self):
        paths_data = {"0": [_make_entry("CLAMP", "C", "missed it")]}
        dlg, _ = _make_dialog(paths_data)
        row = dlg._row_widgets[0]
        for te in row._why_texts.values():
            self.assertFalse(te.isReadOnly())

    def test_no_edit_button(self):
        paths_data = {"0": [_make_entry("CLAMP", "C")]}
        dlg, _ = _make_dialog(paths_data)
        self.assertFalse(hasattr(dlg, "_edit_btn"))

    def test_tag_row_widget_has_no_set_flagged(self):
        from app.views.dialogs.show_tags_dialog import _TagRowWidget
        paths_data = {"0": [_make_entry("CLAMP", "C")]}
        dlg, _ = _make_dialog(paths_data)
        row = dlg._row_widgets[0]
        self.assertFalse(hasattr(row, "set_flagged"))


# ---------------------------------------------------------------------------
# OK and Cancel persistence
# ---------------------------------------------------------------------------

@requires_qt
class TestPersistence(unittest.TestCase):
    def test_ok_with_no_changes_does_not_write(self):
        paths_data = {"0": [_make_entry("CLAMP", "C")]}
        dlg, ctrl = _make_dialog(paths_data)
        dlg._ok_btn.click()
        ctrl.replace_entries_at_path_for_game.assert_not_called()

    def test_ok_after_edit_persists_changed_row(self):
        paths_data = {"0": [_make_entry("CLAMP", "C", "old why")]}
        dlg, ctrl = _make_dialog(paths_data)
        # Change the why text (fields always editable — no edit button needed)
        row = dlg._row_widgets[0]
        row._why_texts["why"].setPlainText("new why")
        dlg._ok_btn.click()
        ctrl.replace_entries_at_path_for_game.assert_called_once()
        call_args = ctrl.replace_entries_at_path_for_game.call_args
        _game, path_key, preset, new_entries = call_args[0]
        self.assertEqual(path_key, "0")
        self.assertEqual(preset, "CLAMP")
        self.assertTrue(any(e.get("why") == "new why" for e in new_entries))

    def test_ok_writes_only_changed_rows(self):
        paths_data = {
            "0": [_make_entry("CLAMP", "C", "unchanged")],
            "0.0": [_make_entry("CLAMP", "L", "will change")],
        }
        dlg, ctrl = _make_dialog(paths_data)
        # Modify only the second row
        dlg._row_widgets[1]._why_texts["why"].setPlainText("changed!")
        dlg._ok_btn.click()
        self.assertEqual(ctrl.replace_entries_at_path_for_game.call_count, 1)
        call_args = ctrl.replace_entries_at_path_for_game.call_args
        self.assertEqual(call_args[0][1], "0.0")

    def test_ok_preserves_other_preset_at_same_path(self):
        """Editing CLAMP row must NOT write to the CCT preset at the same path."""
        paths_data = {
            "0": [
                _make_entry("CLAMP", "C", "clamp why"),
                _make_entry("CCT", "Threats", "cct why"),
            ],
        }
        dlg, ctrl = _make_dialog(paths_data)
        # Edit only the CLAMP row
        clamp_row_idx = next(
            i for i, r in enumerate(dlg._rows_data) if r[1] == "CLAMP"
        )
        dlg._row_widgets[clamp_row_idx]._why_texts["why"].setPlainText("new clamp")
        dlg._ok_btn.click()
        # Only one replace call (for CLAMP)
        self.assertEqual(ctrl.replace_entries_at_path_for_game.call_count, 1)
        call_args = ctrl.replace_entries_at_path_for_game.call_args
        self.assertEqual(call_args[0][2], "CLAMP")

    def test_cancel_after_edit_does_not_write(self):
        paths_data = {"0": [_make_entry("CLAMP", "C", "original")]}
        dlg, ctrl = _make_dialog(paths_data)
        dlg._row_widgets[0]._why_texts["why"].setPlainText("changed but cancelled")
        dlg._cancel_btn.click()
        ctrl.replace_entries_at_path_for_game.assert_not_called()


# ---------------------------------------------------------------------------
# Scrollability
# ---------------------------------------------------------------------------

@requires_qt
class TestScrollability(unittest.TestCase):
    def test_dialog_has_scroll_area_for_many_rows(self):
        paths_data = {}
        for i in range(40):
            path = ".".join(["0"] * (i + 1))
            paths_data[path] = [_make_entry("CLAMP", "C", f"moment {i}")]
        dlg, _ = _make_dialog(paths_data)
        scroll_areas = dlg.findChildren(QScrollArea)
        self.assertTrue(len(scroll_areas) >= 1)


# ---------------------------------------------------------------------------
# Checkbox state reflects saved data
# ---------------------------------------------------------------------------

@requires_qt
class TestCheckboxState(unittest.TestCase):
    def test_clamp_checkbox_ticks_reflect_saved_cat(self):
        paths_data = {
            "0": [_make_entry("CLAMP", "C")],
        }
        dlg, _ = _make_dialog(paths_data)
        row = dlg._row_widgets[0]
        self.assertTrue(row._checkboxes["C"].isChecked())
        for cat in ("L", "A", "M", "P"):
            self.assertFalse(row._checkboxes[cat].isChecked())

    def test_multiple_clamp_cats_all_ticked(self):
        paths_data = {
            "0": [
                _make_entry("CLAMP", "C"),
                _make_entry("CLAMP", "L"),
            ],
        }
        dlg, _ = _make_dialog(paths_data)
        row = dlg._row_widgets[0]
        self.assertTrue(row._checkboxes["C"].isChecked())
        self.assertTrue(row._checkboxes["L"].isChecked())
        for cat in ("A", "M", "P"):
            self.assertFalse(row._checkboxes[cat].isChecked())


# ---------------------------------------------------------------------------
# Zero-category round-trip (cat="" legitimate saves must not be deleted on OK)
# ---------------------------------------------------------------------------

@requires_qt
class TestZeroCategoryRoundtrip(unittest.TestCase):
    def test_zero_category_moment_edit_preserves_entry(self):
        """A moment stored with cat='' survives OK when why text is edited."""
        paths_data = {"0": [_make_entry("CLAMP", "", "original note")]}
        dlg, ctrl = _make_dialog(paths_data)
        dlg._row_widgets[0]._why_texts["why"].setPlainText("updated note")
        dlg._ok_btn.click()
        ctrl.replace_entries_at_path_for_game.assert_called_once()
        _, _, _, new_entries = ctrl.replace_entries_at_path_for_game.call_args[0]
        self.assertEqual(len(new_entries), 1)
        self.assertEqual(new_entries[0]["cat"], "")
        self.assertEqual(new_entries[0]["why"], "updated note")

    def test_uncheck_last_box_keeps_why_as_zero_category(self):
        """Unchecking the last box but leaving why text saves as cat='' (mirrors MomentDialog)."""
        paths_data = {"0": [_make_entry("CLAMP", "C", "note")]}
        dlg, ctrl = _make_dialog(paths_data)
        dlg._row_widgets[0]._checkboxes["C"].setChecked(False)
        dlg._ok_btn.click()
        ctrl.replace_entries_at_path_for_game.assert_called_once()
        _, _, _, new_entries = ctrl.replace_entries_at_path_for_game.call_args[0]
        self.assertEqual(len(new_entries), 1)
        self.assertEqual(new_entries[0]["cat"], "")
        self.assertEqual(new_entries[0]["why"], "note")

    def test_uncheck_all_and_clear_why_is_intentional_delete(self):
        """Unchecking all boxes AND clearing why text deletes the moment (explicit gesture)."""
        paths_data = {"0": [_make_entry("CLAMP", "C", "note")]}
        dlg, ctrl = _make_dialog(paths_data)
        dlg._row_widgets[0]._checkboxes["C"].setChecked(False)
        dlg._row_widgets[0]._why_texts["why"].setPlainText("")
        dlg._ok_btn.click()
        ctrl.replace_entries_at_path_for_game.assert_called_once()
        _, _, _, new_entries = ctrl.replace_entries_at_path_for_game.call_args[0]
        self.assertEqual(new_entries, [])


# ---------------------------------------------------------------------------
# Multi-game dialog shows game headers
# ---------------------------------------------------------------------------

@requires_qt
class TestMultiGameDialog(unittest.TestCase):
    def _make_multi_game_dialog(self, paths1=None, paths2=None):
        from app.views.dialogs.show_tags_dialog import ShowTagsDialog
        from app.models.database_model import GameData

        game1 = GameData(game_number=1, pgn=MAINLINE_PGN, white="Alice", black="Bob")
        game2 = GameData(game_number=2, pgn=SECOND_PGN, white="Carol", black="Dave")
        paths1 = paths1 or {"0": [_make_entry("CLAMP", "C")]}
        paths2 = paths2 or {"0": [_make_entry("CLAMP", "L")]}

        ctrl = MagicMock()
        ctrl.get_tags_for_game.side_effect = lambda g: paths1 if g is game1 else paths2
        ctrl.replace_entries_at_path_for_game = MagicMock()

        dlg = ShowTagsDialog({}, [game1, game2], ctrl)
        return dlg, ctrl, game1, game2

    def test_multi_game_title(self):
        dlg, _, _, _ = self._make_multi_game_dialog()
        self.assertIn("all games", dlg.windowTitle().lower())

    def test_single_game_title_is_not_multi(self):
        dlg, _ = _make_dialog({"0": [_make_entry("CLAMP", "C")]})
        self.assertNotIn("all games", dlg.windowTitle().lower())

    def test_multi_game_has_game_header_labels(self):
        dlg, _, game1, game2 = self._make_multi_game_dialog()
        # Game headers are QLabel children containing player names
        labels = dlg.findChildren(QLabel)
        label_texts = [lbl.text() for lbl in labels]
        # At least one label should contain Alice (game1 header)
        self.assertTrue(any("Alice" in t for t in label_texts))
        # At least one label should contain Carol (game2 header)
        self.assertTrue(any("Carol" in t for t in label_texts))

    def test_single_game_no_game_header_with_player_name(self):
        from app.models.database_model import GameData
        from app.views.dialogs.show_tags_dialog import ShowTagsDialog

        game = GameData(game_number=1, pgn=MAINLINE_PGN, white="UniqueNameXYZ", black="Bob")
        ctrl = MagicMock()
        ctrl.get_tags_for_game.return_value = {"0": [_make_entry("CLAMP", "C")]}
        dlg = ShowTagsDialog({}, [game], ctrl)
        # With a single game, no game-header QLabel is added — the move label
        # won't contain the player name
        labels = dlg.findChildren(QLabel)
        label_texts = [lbl.text() for lbl in labels]
        self.assertFalse(any("UniqueNameXYZ" in t for t in label_texts))

    def test_multi_game_row_count_spans_all_games(self):
        dlg, _, _, _ = self._make_multi_game_dialog(
            paths1={"0": [_make_entry("CLAMP", "C")]},
            paths2={"0": [_make_entry("CLAMP", "L")], "0.0": [_make_entry("CLAMP", "M")]},
        )
        self.assertEqual(len(dlg._row_widgets), 3)

    def test_multi_game_ok_writes_to_correct_game(self):
        dlg, ctrl, game1, game2 = self._make_multi_game_dialog()
        # Edit the second row (game2's row)
        dlg._row_widgets[1]._why_texts["why"].setPlainText("edited g2")
        dlg._ok_btn.click()
        ctrl.replace_entries_at_path_for_game.assert_called_once()
        call_args = ctrl.replace_entries_at_path_for_game.call_args[0]
        # First arg should be game2
        self.assertIs(call_args[0], game2)


# ---------------------------------------------------------------------------
# Ignore checkbox on _TagRowWidget
# ---------------------------------------------------------------------------

@requires_qt
class TestIgnoreCheckbox(unittest.TestCase):
    def _make_row(self, entries, show_ignore=False):
        from app.views.dialogs.show_tags_dialog import _TagRowWidget
        return _TagRowWidget(
            config={},
            preset="CLAMP",
            entries=entries,
            move_label="1. e4",
            fen=None,
            played_move=None,
            bg_rgb=[40, 40, 45],
            text_color=[200, 200, 200],
            show_ignore_checkbox=show_ignore,
        )

    def test_no_ignore_checkbox_by_default(self):
        row = self._make_row([_make_entry("CLAMP", "C")])
        self.assertIsNone(row._ignore_check)

    def test_ignore_checkbox_rendered_when_requested(self):
        row = self._make_row([_make_entry("CLAMP", "C")], show_ignore=True)
        self.assertIsNotNone(row._ignore_check)
        self.assertIsInstance(row._ignore_check, QCheckBox)

    def test_ignore_checkbox_starts_unchecked_when_entry_has_no_flag(self):
        row = self._make_row([_make_entry("CLAMP", "C")], show_ignore=True)
        self.assertFalse(row._ignore_check.isChecked())

    def test_ignore_checkbox_starts_checked_when_entry_flagged(self):
        entry = _make_entry("CLAMP", "C", ignore_shallow=True)
        row = self._make_row([entry], show_ignore=True)
        self.assertTrue(row._ignore_check.isChecked())

    def test_get_current_entries_includes_ignore_shallow_when_checked(self):
        row = self._make_row([_make_entry("CLAMP", "C")], show_ignore=True)
        row._ignore_check.setChecked(True)
        entries = row.get_current_entries()
        self.assertTrue(all(e.get("ignore_shallow") for e in entries))

    def test_get_current_entries_omits_ignore_shallow_when_unchecked(self):
        row = self._make_row([_make_entry("CLAMP", "C")], show_ignore=True)
        row._ignore_check.setChecked(False)
        entries = row.get_current_entries()
        self.assertFalse(any(e.get("ignore_shallow") for e in entries))

    def test_show_tags_dialog_rows_have_no_ignore_checkbox(self):
        """ShowTagsDialog never passes show_ignore_checkbox=True to rows."""
        paths_data = {"0": [_make_entry("CLAMP", "C")]}
        dlg, _ = _make_dialog(paths_data)
        for row in dlg._row_widgets:
            self.assertIsNone(row._ignore_check)


# ---------------------------------------------------------------------------
# ignore_shallow preservation when show_ignore_checkbox=False
# ---------------------------------------------------------------------------

@requires_qt
class TestIgnoreShallowPreservation(unittest.TestCase):
    def _make_row(self, entries):
        from app.views.dialogs.show_tags_dialog import _TagRowWidget
        return _TagRowWidget(
            config={},
            preset="CLAMP",
            entries=entries,
            move_label="1. e4",
            fen=None,
            played_move=None,
            bg_rgb=[40, 40, 45],
            text_color=[200, 200, 200],
            show_ignore_checkbox=False,
        )

    def test_ignore_shallow_preserved_through_edit_roundtrip(self):
        """Editing why-text in Show Tags does not strip an existing ignore_shallow flag."""
        entry = _make_entry("CLAMP", "C", "original note", ignore_shallow=True)
        row = self._make_row([entry])
        row._why_texts["why"].setPlainText("edited note")
        entries = row.get_current_entries()
        self.assertTrue(all(e.get("ignore_shallow") for e in entries))

    def test_no_ignore_shallow_when_entry_never_had_it(self):
        entry = _make_entry("CLAMP", "C", "note")
        row = self._make_row([entry])
        entries = row.get_current_entries()
        self.assertFalse(any(e.get("ignore_shallow") for e in entries))


@requires_qt
class TestBestMoveArrow(unittest.TestCase):
    """Tests confirming best_move is resolved and threaded into _TagRowWidget."""

    def _make_row_with_best(self, best_move=None):
        from app.views.dialogs.show_tags_dialog import _TagRowWidget
        import chess
        entry = _make_entry("CLAMP", "C", "note")
        return _TagRowWidget(
            config={},
            preset="CLAMP",
            entries=[entry],
            move_label="1. e4",
            fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
            played_move=chess.Move.from_uci("e2e4"),
            bg_rgb=[40, 40, 45],
            text_color=[200, 200, 200],
            best_move=best_move,
        )

    def test_row_widget_stores_best_move_none(self):
        row = self._make_row_with_best(None)
        self.assertIsNone(row._best_move)

    def test_row_widget_stores_best_move(self):
        import chess
        best = chess.Move.from_uci("d2d4")
        row = self._make_row_with_best(best)
        self.assertEqual(row._best_move, best)

    def test_snapshot_carries_best_move(self):
        import chess
        best = chess.Move.from_uci("d2d4")
        row = self._make_row_with_best(best)
        snap = row.snapshot()
        self.assertEqual(snap.best_move, best)

    def test_snapshot_best_move_none_when_unset(self):
        row = self._make_row_with_best(None)
        snap = row.snapshot()
        self.assertIsNone(snap.best_move)

    def test_dialog_calls_resolve_best_move(self):
        """ShowTagsDialog calls resolve_best_move_for_path for each row."""
        from unittest.mock import patch
        import chess
        paths_data = {"0": [_make_entry("CLAMP", "C", "note")]}
        fake_best = chess.Move.from_uci("d2d4")
        with patch(
            "app.views.dialogs.show_tags_dialog.resolve_best_move_for_path",
            return_value=fake_best,
        ) as mock_resolve:
            dlg, _ = _make_dialog(paths_data)
        self.assertTrue(mock_resolve.called)
        # The one row widget should carry the resolved best move.
        self.assertEqual(dlg._row_widgets[0]._best_move, fake_best)

    def test_dialog_passes_none_best_move_when_resolver_returns_none(self):
        from unittest.mock import patch
        paths_data = {"0": [_make_entry("CLAMP", "C", "note")]}
        with patch(
            "app.views.dialogs.show_tags_dialog.resolve_best_move_for_path",
            return_value=None,
        ):
            dlg, _ = _make_dialog(paths_data)
        self.assertIsNone(dlg._row_widgets[0]._best_move)


@requires_qt
class TestShowTagsDialogThemeColors(unittest.TestCase):
    """ShowTagsDialog must route separator and text-editor colors through config."""

    def _make_themed_dialog(self, moment_cfg: dict):
        from app.views.dialogs.show_tags_dialog import ShowTagsDialog
        config = {"ui": {"dialogs": {"moment": moment_cfg}}}
        paths_data = {
            "0": [_make_entry("CLAMP", "C", "first")],
            "0.0": [_make_entry("CLAMP", "L", "second")],
        }
        game_data = _make_game_data(MAINLINE_PGN)
        ctrl = _make_controller(paths_data)
        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "app.views.dialogs.show_tags_dialog.resolve_best_move_for_path",
            return_value=None,
        ):
            dlg = ShowTagsDialog(config, [game_data], ctrl)
        return dlg

    def test_separator_uses_config_color(self):
        dlg = self._make_themed_dialog({"separator_color": [10, 20, 30]})
        sep = dlg._make_separator()
        self.assertIn("rgb(10,20,30)", sep.styleSheet())

    def test_separator_fallback_dark(self):
        dlg = self._make_themed_dialog({})
        sep = dlg._make_separator()
        self.assertIn("rgb(70,70,75)", sep.styleSheet())

    def test_text_widget_uses_input_bg_from_config(self):
        from PyQt6.QtWidgets import QPlainTextEdit
        dlg = self._make_themed_dialog({"inputs": {"background_color": [5, 6, 7], "border_color": [8, 9, 10]}})
        te = QPlainTextEdit()
        dlg._row_widgets[0]._style_text_widget(te)
        self.assertIn("rgb(5,6,7)", te.styleSheet())


if __name__ == "__main__":
    unittest.main()
