"""Unit tests for MomentDialog.

Requires a working Qt platform plugin (CI uses QT_QPA_PLATFORM=offscreen).
Tests are skipped automatically when Qt cannot start (e.g. macOS without display).
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _qt_starts_cleanly() -> bool:
    """Return True if QApplication can be created in this environment."""
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


@requires_qt
class TestMomentDialogClamp(unittest.TestCase):
    def _make(self, move_number=5, san="Nf3", is_white=True):
        from app.views.dialogs.moment_dialog import MomentDialog
        return MomentDialog({}, move_number, san, is_white)

    def test_no_selection_returns_empty(self):
        dlg = self._make()
        dlg._tabs.setCurrentIndex(0)
        self.assertEqual(dlg.get_entries(), [])

    def test_clamp_selection_returns_one_entry(self):
        dlg = self._make()
        dlg._tabs.setCurrentIndex(0)
        dlg._clamp_buttons[3].setChecked(True)  # M
        entries = dlg.get_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["preset"], "CLAMP")
        self.assertEqual(entries[0]["cat"], "M")
        self.assertEqual(entries[0]["why"], "")

    def test_clamp_exclusive_only_one_checked(self):
        dlg = self._make()
        dlg._tabs.setCurrentIndex(0)
        dlg._clamp_buttons[0].setChecked(True)  # C
        dlg._clamp_buttons[4].setChecked(True)  # P → should deselect C
        checked = [b for b in dlg._clamp_buttons if b.isChecked()]
        self.assertEqual(len(checked), 1)
        self.assertEqual(checked[0].text(), "P")

    def test_clamp_why_text_passed_through(self):
        dlg = self._make()
        dlg._tabs.setCurrentIndex(0)
        dlg._clamp_buttons[1].setChecked(True)  # L
        dlg._why_edit.setPlainText("Rook was trapped")
        self.assertEqual(dlg.get_entries()[0]["why"], "Rook was trapped")


@requires_qt
class TestMomentDialogCct(unittest.TestCase):
    def _make(self):
        from app.views.dialogs.moment_dialog import MomentDialog
        return MomentDialog({}, 10, "Bxf7", True)

    def test_no_cct_selection_returns_empty(self):
        dlg = self._make()
        dlg._tabs.setCurrentIndex(1)
        self.assertEqual(dlg.get_entries(), [])

    def test_single_cct_returns_one_entry(self):
        dlg = self._make()
        dlg._tabs.setCurrentIndex(1)
        dlg._cct_buttons[2][1].setChecked(True)  # Threats
        entries = dlg.get_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["cat"], "Threats")

    def test_multiple_cct_returns_multiple_entries_same_why(self):
        dlg = self._make()
        dlg._tabs.setCurrentIndex(1)
        dlg._cct_buttons[0][1].setChecked(True)  # Checks
        dlg._cct_buttons[2][1].setChecked(True)  # Threats
        dlg._why_edit.setPlainText("missed the threat")
        entries = dlg.get_entries()
        self.assertEqual(len(entries), 2)
        cats = {e["cat"] for e in entries}
        self.assertEqual(cats, {"Checks", "Threats"})
        self.assertTrue(all(e["why"] == "missed the threat" for e in entries))

    def test_cct_non_exclusive_all_three(self):
        dlg = self._make()
        dlg._tabs.setCurrentIndex(1)
        for _, btn in dlg._cct_buttons:
            btn.setChecked(True)
        self.assertEqual(len(dlg.get_entries()), 3)


@requires_qt
class TestMomentDialogCustom(unittest.TestCase):
    def _make(self):
        from app.views.dialogs.moment_dialog import MomentDialog
        return MomentDialog({}, 20, "O-O", True)

    def test_empty_custom_returns_empty(self):
        dlg = self._make()
        dlg._tabs.setCurrentIndex(2)
        self.assertEqual(dlg.get_entries(), [])

    def test_custom_text_entry(self):
        dlg = self._make()
        dlg._tabs.setCurrentIndex(2)
        dlg._custom_edit.setText("King safety")
        entries = dlg.get_entries()
        self.assertEqual(entries[0]["preset"], "custom")
        self.assertEqual(entries[0]["cat"], "King safety")

    def test_custom_why_preserved(self):
        dlg = self._make()
        dlg._tabs.setCurrentIndex(2)
        dlg._custom_edit.setText("Zwischenzug")
        dlg._why_edit.setPlainText("Missed in-between move")
        self.assertEqual(dlg.get_entries()[0]["why"], "Missed in-between move")


if __name__ == "__main__":
    unittest.main()
