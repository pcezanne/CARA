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
    from PyQt6.QtWidgets import QApplication, QCheckBox, QPlainTextEdit, QScrollArea
    _APP = QApplication.instance() or QApplication(sys.argv[:1])

# ---------------------------------------------------------------------------
# Minimal PGN helpers
# ---------------------------------------------------------------------------

MAINLINE_PGN = (
    '[Event "T"][Site "?"][Date "2026.01.01"]'
    '[Round "?"][White "W"][Black "B"][Result "*"]\n\n'
    "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 *\n"
)


def _make_game_data(pgn: str = MAINLINE_PGN):
    from app.models.database_model import GameData
    return GameData(game_number=1, pgn=pgn)


def _make_controller(paths_data: dict, custom_categories=None):
    ctrl = MagicMock()
    ctrl.get_tags_for_current_game.return_value = paths_data
    ctrl.get_custom_categories.return_value = custom_categories or []
    ctrl.game_has_any_tags.return_value = bool(paths_data)
    ctrl.replace_entries_at_path = MagicMock()
    return ctrl


def _make_entry(preset, cat, why=""):
    from app.services.chess_log_storage_service import ChessLogStorageService
    return ChessLogStorageService.make_entry(preset, cat, why)


def _make_dialog(paths_data: dict, custom_categories=None, pgn: str = MAINLINE_PGN):
    from app.views.dialogs.show_tags_dialog import ShowTagsDialog
    game_data = _make_game_data(pgn)
    ctrl = _make_controller(paths_data, custom_categories)
    return ShowTagsDialog({}, game_data, ctrl), ctrl


# ---------------------------------------------------------------------------
# Row count and ordering
# ---------------------------------------------------------------------------

@requires_qt
class TestRowCount(unittest.TestCase):
    def test_one_row_per_move_preset_pair(self):
        # Move at path "0" has CLAMP, move at "0.0" has CLAMP, "0.0" also has Custom → 3 rows
        paths_data = {
            "0": [_make_entry("CLAMP", "C")],
            "0.0": [
                _make_entry("CLAMP", "L"),
                _make_entry("Custom", "Time trouble"),
            ],
        }
        dlg, _ = _make_dialog(paths_data)
        # "0" → 1 row (CLAMP); "0.0" → 2 rows (CLAMP + Custom)
        self.assertEqual(len(dlg._row_widgets), 3)

    def test_three_clamp_rows_plus_one_custom(self):
        paths_data = {
            "0": [_make_entry("CLAMP", "C")],
            "0.0": [_make_entry("CLAMP", "L")],
            "0.0.0": [
                _make_entry("CLAMP", "M"),
                _make_entry("Custom", "Blunder"),
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
        # One move ("0") tagged with CLAMP, CCT, Custom
        paths_data = {
            "0": [
                _make_entry("Custom", "Oops"),
                _make_entry("CCT", "Threats"),
                _make_entry("CLAMP", "C"),
            ],
        }
        dlg, _ = _make_dialog(paths_data)
        presets = [r[1] for r in dlg._rows_data]
        # Should be CLAMP first, CCT second, Custom third
        self.assertEqual(presets, ["CLAMP", "CCT", "Custom"])


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

    def test_3x3_row_text_contains_all_three_sentences(self):
        paths_data = {
            "0": [
                _make_entry("3x3", "Why1", "I wanted to develop"),
                _make_entry("3x3", "Why2", "It lost tempo"),
                _make_entry("3x3", "Why3", "Engine prefers Nf3"),
            ],
        }
        dlg, _ = _make_dialog(paths_data)
        row = dlg._row_widgets[0]
        self.assertIn("Why1", row._why_texts)
        self.assertIn("Why2", row._why_texts)
        self.assertIn("Why3", row._why_texts)
        self.assertIn("develop", row._why_texts["Why1"].toPlainText())
        self.assertIn("tempo", row._why_texts["Why2"].toPlainText())
        self.assertIn("Nf3", row._why_texts["Why3"].toPlainText())


# ---------------------------------------------------------------------------
# Read-only / edit mode
# ---------------------------------------------------------------------------

@requires_qt
class TestReadOnlyAndEditMode(unittest.TestCase):
    def test_read_only_mode_disables_checkboxes(self):
        paths_data = {"0": [_make_entry("CLAMP", "C")]}
        dlg, _ = _make_dialog(paths_data)
        row = dlg._row_widgets[0]
        for cb in row._checkboxes.values():
            self.assertFalse(cb.isEnabled())

    def test_read_only_mode_makes_text_read_only(self):
        paths_data = {"0": [_make_entry("CLAMP", "C", "missed it")]}
        dlg, _ = _make_dialog(paths_data)
        row = dlg._row_widgets[0]
        for te in row._why_texts.values():
            self.assertTrue(te.isReadOnly())

    def test_edit_button_enables_checkboxes(self):
        paths_data = {"0": [_make_entry("CLAMP", "C")]}
        dlg, _ = _make_dialog(paths_data)
        dlg._edit_btn.click()
        row = dlg._row_widgets[0]
        for cb in row._checkboxes.values():
            self.assertTrue(cb.isEnabled())

    def test_edit_button_makes_text_editable(self):
        paths_data = {"0": [_make_entry("CLAMP", "C", "why")]}
        dlg, _ = _make_dialog(paths_data)
        dlg._edit_btn.click()
        row = dlg._row_widgets[0]
        for te in row._why_texts.values():
            self.assertFalse(te.isReadOnly())


# ---------------------------------------------------------------------------
# OK and Cancel persistence
# ---------------------------------------------------------------------------

@requires_qt
class TestPersistence(unittest.TestCase):
    def test_ok_in_read_only_mode_does_not_write(self):
        paths_data = {"0": [_make_entry("CLAMP", "C")]}
        dlg, ctrl = _make_dialog(paths_data)
        dlg._ok_btn.click()
        ctrl.replace_entries_at_path.assert_not_called()

    def test_ok_after_edit_persists_changed_row(self):
        paths_data = {"0": [_make_entry("CLAMP", "C", "old why")]}
        dlg, ctrl = _make_dialog(paths_data)
        dlg._edit_btn.click()
        # Change the why text
        row = dlg._row_widgets[0]
        row._why_texts["why"].setPlainText("new why")
        dlg._ok_btn.click()
        ctrl.replace_entries_at_path.assert_called_once()
        call_args = ctrl.replace_entries_at_path.call_args
        path_key, preset, new_entries = call_args[0]
        self.assertEqual(path_key, "0")
        self.assertEqual(preset, "CLAMP")
        self.assertTrue(any(e.get("why") == "new why" for e in new_entries))

    def test_ok_writes_only_changed_rows(self):
        paths_data = {
            "0": [_make_entry("CLAMP", "C", "unchanged")],
            "0.0": [_make_entry("CLAMP", "L", "will change")],
        }
        dlg, ctrl = _make_dialog(paths_data)
        dlg._edit_btn.click()
        # Modify only the second row
        dlg._row_widgets[1]._why_texts["why"].setPlainText("changed!")
        dlg._ok_btn.click()
        self.assertEqual(ctrl.replace_entries_at_path.call_count, 1)
        call_args = ctrl.replace_entries_at_path.call_args
        self.assertEqual(call_args[0][0], "0.0")

    def test_ok_preserves_other_preset_at_same_path(self):
        """Editing CLAMP row must NOT write to the Custom preset at the same path."""
        paths_data = {
            "0": [
                _make_entry("CLAMP", "C", "clamp why"),
                _make_entry("Custom", "Time trouble", "custom why"),
            ],
        }
        dlg, ctrl = _make_dialog(paths_data, custom_categories=["Time trouble"])
        dlg._edit_btn.click()
        # Edit the CLAMP row (index 0 in rows_data since CLAMP < Custom)
        clamp_row_idx = next(
            i for i, r in enumerate(dlg._rows_data) if r[1] == "CLAMP"
        )
        dlg._row_widgets[clamp_row_idx]._why_texts["why"].setPlainText("new clamp")
        dlg._ok_btn.click()
        # Only one replace call (for CLAMP)
        self.assertEqual(ctrl.replace_entries_at_path.call_count, 1)
        call_args = ctrl.replace_entries_at_path.call_args
        self.assertEqual(call_args[0][1], "CLAMP")

    def test_cancel_after_edit_does_not_write(self):
        paths_data = {"0": [_make_entry("CLAMP", "C", "original")]}
        dlg, ctrl = _make_dialog(paths_data)
        dlg._edit_btn.click()
        dlg._row_widgets[0]._why_texts["why"].setPlainText("changed but cancelled")
        dlg._cancel_btn.click()
        ctrl.replace_entries_at_path.assert_not_called()


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

    def test_custom_categories_render_from_controller(self):
        paths_data = {
            "0": [_make_entry("Custom", "Time trouble")],
        }
        dlg, ctrl = _make_dialog(paths_data, custom_categories=["Time trouble", "Wrong plan"])
        row = dlg._row_widgets[0]
        self.assertIn("Time trouble", row._checkboxes)
        self.assertIn("Wrong plan", row._checkboxes)
        self.assertTrue(row._checkboxes["Time trouble"].isChecked())
        self.assertFalse(row._checkboxes["Wrong plan"].isChecked())


if __name__ == "__main__":
    unittest.main()
