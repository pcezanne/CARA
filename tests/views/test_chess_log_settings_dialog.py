"""Unit tests for ChessLogSettingsDialog.

Requires a working Qt platform plugin (CI uses QT_QPA_PLATFORM=offscreen).
Tests are skipped automatically when Qt cannot start.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest.mock import MagicMock

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
requires_qt = unittest.skipUnless(_QT_OK, "Qt platform plugin unavailable in this environment")

if _QT_OK:
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication(sys.argv[:1])


def _make_uss(active_preset="CLAMP", custom_categories=None) -> MagicMock:
    uss = MagicMock()
    uss.get_chess_log.return_value = {
        "active_preset": active_preset,
        "custom_categories": list(custom_categories or []),
    }
    return uss


def _make_dialog(active_preset="CLAMP", custom_categories=None):
    from app.views.dialogs.chess_log_settings_dialog import ChessLogSettingsDialog
    uss = _make_uss(active_preset, custom_categories)
    dlg = ChessLogSettingsDialog({}, uss)
    return dlg, uss


@requires_qt
class TestPresetPreselect(unittest.TestCase):
    def test_clamp_preselected_by_default(self):
        dlg, _ = _make_dialog("CLAMP")
        self.assertTrue(dlg._radio_buttons["CLAMP"].isChecked())
        for name in ("CCT", "3x3", "Custom"):
            self.assertFalse(dlg._radio_buttons[name].isChecked())

    def test_cct_preselected_when_setting_is_cct(self):
        dlg, _ = _make_dialog("CCT")
        self.assertTrue(dlg._radio_buttons["CCT"].isChecked())

    def test_threexthree_preselected(self):
        dlg, _ = _make_dialog("3x3")
        self.assertTrue(dlg._radio_buttons["3x3"].isChecked())

    def test_custom_preselected(self):
        dlg, _ = _make_dialog("Custom")
        self.assertTrue(dlg._radio_buttons["Custom"].isChecked())


@requires_qt
class TestCustomSectionVisibility(unittest.TestCase):
    def test_custom_section_hidden_when_clamp_active(self):
        dlg, _ = _make_dialog("CLAMP")
        self.assertFalse(dlg._custom_section.isVisible())

    def test_custom_section_visible_when_custom_active(self):
        dlg, _ = _make_dialog("Custom")
        self.assertTrue(dlg._custom_section.isVisible())

    def test_switching_to_custom_shows_section(self):
        dlg, _ = _make_dialog("CLAMP")
        self.assertFalse(dlg._custom_section.isVisible())
        dlg._radio_buttons["Custom"].setChecked(True)
        self.assertTrue(dlg._custom_section.isVisible())

    def test_switching_away_from_custom_hides_section(self):
        dlg, _ = _make_dialog("Custom")
        self.assertTrue(dlg._custom_section.isVisible())
        dlg._radio_buttons["CCT"].setChecked(True)
        self.assertFalse(dlg._custom_section.isVisible())


@requires_qt
class TestAcceptPersists(unittest.TestCase):
    def test_accept_saves_new_preset(self):
        dlg, uss = _make_dialog("CLAMP")
        dlg._radio_buttons["CCT"].setChecked(True)
        dlg._on_ok()
        uss.update_chess_log_settings.assert_called_once()
        saved = uss.update_chess_log_settings.call_args[0][0]
        self.assertEqual(saved["active_preset"], "CCT")
        uss.save.assert_called_once()

    def test_accept_saves_custom_categories(self):
        dlg, uss = _make_dialog("Custom", ["Time trouble", "Wrong plan"])
        # Simulate user keeping the existing categories
        dlg._radio_buttons["Custom"].setChecked(True)
        dlg._on_ok()
        saved = uss.update_chess_log_settings.call_args[0][0]
        self.assertIn("Time trouble", saved["custom_categories"])
        self.assertIn("Wrong plan", saved["custom_categories"])

    def test_cancel_does_not_persist(self):
        dlg, uss = _make_dialog("CLAMP")
        dlg._radio_buttons["CCT"].setChecked(True)
        dlg.reject()
        uss.update_chess_log_settings.assert_not_called()
        uss.save.assert_not_called()


@requires_qt
class TestCategoryManagement(unittest.TestCase):
    def test_initial_categories_appear_as_rows(self):
        dlg, _ = _make_dialog("Custom", ["A", "B", "C"])
        # Three rows should exist
        self.assertEqual(len(dlg._cat_rows), 3)
        texts = [edit.text() for edit, _ in dlg._cat_rows]
        self.assertIn("A", texts)
        self.assertIn("B", texts)
        self.assertIn("C", texts)

    def test_add_category_appends_row(self):
        dlg, _ = _make_dialog("Custom", ["existing"])
        dlg._on_add_category()
        self.assertEqual(len(dlg._cat_rows), 2)

    def test_categories_saved_on_ok(self):
        dlg, uss = _make_dialog("Custom", [])
        dlg._radio_buttons["Custom"].setChecked(True)
        dlg._on_add_category()
        # Set text on the new row
        dlg._cat_rows[0][0].setText("My category")
        dlg._on_ok()
        saved = uss.update_chess_log_settings.call_args[0][0]
        self.assertIn("My category", saved["custom_categories"])

    def test_blank_categories_excluded_on_save(self):
        dlg, uss = _make_dialog("Custom", [])
        dlg._radio_buttons["Custom"].setChecked(True)
        dlg._on_add_category()
        dlg._on_add_category()
        dlg._cat_rows[0][0].setText("Good category")
        dlg._cat_rows[1][0].setText("")  # blank — should be excluded
        dlg._on_ok()
        saved = uss.update_chess_log_settings.call_args[0][0]
        self.assertEqual(saved["custom_categories"], ["Good category"])


@requires_qt
class TestAttributionLabels(unittest.TestCase):
    """Attribution subtitles must appear for CLAMP and 3x3, and nowhere else."""

    def _attribution_texts(self, dlg) -> set:
        from PyQt6.QtWidgets import QLabel
        return {lbl.text() for lbl in dlg.findChildren(QLabel) if lbl.text().startswith("Developed by")}

    def test_clamp_attribution_present(self):
        dlg, _ = _make_dialog("CLAMP")
        self.assertIn("Developed by Dr. Can Kabadayi", self._attribution_texts(dlg))

    def test_threexthree_attribution_present(self):
        dlg, _ = _make_dialog("CLAMP")  # active preset doesn't affect which rows render
        self.assertIn("Developed by GM Noel Studer", self._attribution_texts(dlg))

    def test_cct_and_custom_have_no_attribution(self):
        """Exactly two attribution labels exist — CLAMP and 3x3; none for CCT or Custom."""
        dlg, _ = _make_dialog("CLAMP")
        texts = self._attribution_texts(dlg)
        self.assertEqual(len(texts), 2)


if __name__ == "__main__":
    unittest.main()
