"""Unit tests for MomentDialog (active-preset design).

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


def _make(active_preset="CLAMP", move_number=5, san="Nf3", is_white=True):
    from app.views.dialogs.moment_dialog import MomentDialog
    return MomentDialog({}, active_preset, move_number, san, is_white)


@requires_qt
class TestClampPreset(unittest.TestCase):
    def test_no_selection_returns_empty(self):
        dlg = _make("CLAMP")
        self.assertEqual(dlg.get_entries(), [])

    def test_single_chip_returns_one_entry(self):
        dlg = _make("CLAMP")
        m_btn = next(btn for cat, btn in dlg._chip_buttons if cat == "M")
        m_btn.setChecked(True)
        entries = dlg.get_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["preset"], "CLAMP")
        self.assertEqual(entries[0]["cat"], "M")
        self.assertEqual(entries[0]["why"], "")

    def test_multi_select_two_chips(self):
        dlg = _make("CLAMP")
        c_btn = next(btn for cat, btn in dlg._chip_buttons if cat == "C")
        l_btn = next(btn for cat, btn in dlg._chip_buttons if cat == "L")
        c_btn.setChecked(True)
        l_btn.setChecked(True)
        entries = dlg.get_entries()
        self.assertEqual(len(entries), 2)
        cats = {e["cat"] for e in entries}
        self.assertEqual(cats, {"C", "L"})
        self.assertTrue(all(e["preset"] == "CLAMP" for e in entries))

    def test_all_five_chips_multi_select(self):
        dlg = _make("CLAMP")
        for _, btn in dlg._chip_buttons:
            btn.setChecked(True)
        entries = dlg.get_entries()
        self.assertEqual(len(entries), 5)

    def test_why_shared_across_all_entries(self):
        dlg = _make("CLAMP")
        c_btn = next(btn for cat, btn in dlg._chip_buttons if cat == "C")
        l_btn = next(btn for cat, btn in dlg._chip_buttons if cat == "L")
        c_btn.setChecked(True)
        l_btn.setChecked(True)
        dlg._why_edit.setPlainText("Rook was trapped")
        entries = dlg.get_entries()
        self.assertTrue(all(e["why"] == "Rook was trapped" for e in entries))

    def test_zero_chips_with_why_returns_uncategorized_entry(self):
        dlg = _make("CLAMP")
        dlg._why_edit.setPlainText("general observation")
        entries = dlg.get_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["preset"], "CLAMP")
        self.assertEqual(entries[0]["cat"], "")
        self.assertEqual(entries[0]["why"], "general observation")

    def test_zero_chips_empty_why_returns_empty(self):
        dlg = _make("CLAMP")
        self.assertEqual(dlg.get_entries(), [])


@requires_qt
class TestCctPreset(unittest.TestCase):
    def test_no_selection_returns_empty(self):
        dlg = _make("CCT")
        self.assertEqual(dlg.get_entries(), [])

    def test_single_cct_returns_one_entry(self):
        dlg = _make("CCT")
        t_btn = next(btn for cat, btn in dlg._chip_buttons if cat == "Threats")
        t_btn.setChecked(True)
        entries = dlg.get_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["cat"], "Threats")
        self.assertEqual(entries[0]["preset"], "CCT")

    def test_multiple_cct_returns_multiple_entries_same_why(self):
        dlg = _make("CCT")
        c_btn = next(btn for cat, btn in dlg._chip_buttons if cat == "Checks")
        t_btn = next(btn for cat, btn in dlg._chip_buttons if cat == "Threats")
        c_btn.setChecked(True)
        t_btn.setChecked(True)
        dlg._why_edit.setPlainText("missed the threat")
        entries = dlg.get_entries()
        self.assertEqual(len(entries), 2)
        cats = {e["cat"] for e in entries}
        self.assertEqual(cats, {"Checks", "Threats"})
        self.assertTrue(all(e["why"] == "missed the threat" for e in entries))

    def test_all_three_cct_non_exclusive(self):
        dlg = _make("CCT")
        for _, btn in dlg._chip_buttons:
            btn.setChecked(True)
        self.assertEqual(len(dlg.get_entries()), 3)

    def test_zero_chips_with_why_returns_uncategorized_entry(self):
        dlg = _make("CCT")
        dlg._why_edit.setPlainText("missed a tactic")
        entries = dlg.get_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["preset"], "CCT")
        self.assertEqual(entries[0]["cat"], "")
        self.assertEqual(entries[0]["why"], "missed a tactic")

    def test_zero_chips_empty_why_returns_empty(self):
        dlg = _make("CCT")
        self.assertEqual(dlg.get_entries(), [])


@requires_qt
class TestThreeByThreePreset(unittest.TestCase):
    def test_all_four_whys_filled(self):
        dlg = _make("3x3")
        answers = ["I wanted to attack", "It lost a tempo", "Engine moves centrally", "Check for pins first"]
        for (key, edit), answer in zip(dlg._threexthree_edits, answers):
            edit.setPlainText(answer)
        entries = dlg.get_entries()
        self.assertEqual(len(entries), 4)
        self.assertEqual([e["cat"] for e in entries], ["Why1", "Why2", "Why3", "Why4"])
        self.assertEqual([e["why"] for e in entries], answers)
        self.assertTrue(all(e["preset"] == "3x3" for e in entries))

    def test_partial_whys_skips_empty(self):
        dlg = _make("3x3")
        dlg._threexthree_edits[0][1].setPlainText("I wanted to attack")
        dlg._threexthree_edits[1][1].setPlainText("")
        dlg._threexthree_edits[2][1].setPlainText("")
        dlg._threexthree_edits[3][1].setPlainText("Slow down in sharp positions")
        entries = dlg.get_entries()
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["cat"], "Why1")
        self.assertEqual(entries[1]["cat"], "Why4")

    def test_all_empty_returns_empty_list(self):
        dlg = _make("3x3")
        self.assertEqual(dlg.get_entries(), [])

    def test_ordering_why1_through_why4(self):
        dlg = _make("3x3")
        for _, edit in dlg._threexthree_edits:
            edit.setPlainText("answer")
        entries = dlg.get_entries()
        self.assertEqual([e["cat"] for e in entries], ["Why1", "Why2", "Why3", "Why4"])


@requires_qt
class TestCustomNotOffered(unittest.TestCase):
    """Custom must not appear as an offered preset in MomentDialog."""

    def test_custom_preset_falls_back_to_clamp(self):
        dlg = _make("Custom")
        self.assertEqual(dlg._active_preset, "CLAMP")
        self.assertTrue(bool(dlg._chip_buttons), "CLAMP chips should be present")

    def test_tag_moment_static_factory_excludes_custom(self):
        from app.views.dialogs.moment_dialog import MomentDialog
        from unittest.mock import patch
        with patch.object(MomentDialog, "exec", return_value=0):
            result = MomentDialog.tag_moment({}, "Custom", 1, "e4", True, None)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
