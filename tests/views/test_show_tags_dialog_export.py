"""Tests for Export to PDF additions to ShowTagsDialog and _TagRowWidget.snapshot()."""

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
requires_qt = unittest.skipUnless(_QT_OK, "Qt platform plugin unavailable")

if _QT_OK:
    from PyQt6.QtWidgets import QApplication, QPushButton
    _APP = QApplication.instance() or QApplication(sys.argv[:1])

    from app.models.chess_log_snapshot import TagRowSnapshot
    from app.views.dialogs.show_tags_dialog import _TagRowWidget, ShowTagsDialog

MAINLINE_PGN = (
    '[Event "T"][Site "?"][Date "2026.01.01"]'
    '[Round "?"][White "W"][Black "B"][Result "*"]\n\n'
    "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 *\n"
)


def _make_game_data(pgn: str = MAINLINE_PGN, game_number: int = 1):
    from app.models.database_model import GameData
    return GameData(game_number=game_number, pgn=pgn)


def _make_mock_controller(game):
    ctrl = MagicMock()
    ctrl.get_custom_categories.return_value = []
    ctrl.get_tags_for_game.return_value = {
        "0,0": [{"preset": "CLAMP", "cat": "C", "why": "test", "id": "x", "created": "y"}]
    }
    return ctrl


@requires_qt
class TestTagRowWidgetSnapshot(unittest.TestCase):
    def _make_row(self, preset="CLAMP", entries=None, show_ignore=False):
        if entries is None:
            entries = [{"preset": preset, "cat": "C", "why": "a note", "id": "x", "created": "y"}]
        return _TagRowWidget(
            config={},
            preset=preset,
            entries=entries,
            custom_categories=[],
            move_label="1. e4",
            fen=None,
            played_move=None,
            bg_rgb=[40, 40, 45],
            text_color=[200, 200, 200],
            show_ignore_checkbox=show_ignore,
        )

    def test_snapshot_returns_tag_row_snapshot(self):
        row = self._make_row()
        snap = row.snapshot()
        self.assertIsInstance(snap, TagRowSnapshot)

    def test_snapshot_move_label(self):
        row = self._make_row()
        snap = row.snapshot()
        self.assertEqual(snap.move_label, "1. e4")

    def test_snapshot_preset(self):
        row = self._make_row(preset="CCT")
        snap = row.snapshot()
        self.assertEqual(snap.preset, "CCT")

    def test_snapshot_fen_none(self):
        row = self._make_row()
        snap = row.snapshot()
        self.assertIsNone(snap.fen)

    def test_snapshot_show_ignore_false(self):
        row = self._make_row(show_ignore=False)
        snap = row.snapshot()
        self.assertFalse(snap.show_ignore)

    def test_snapshot_show_ignore_true(self):
        row = self._make_row(
            entries=[{"preset": "CLAMP", "cat": "C", "why": "", "id": "x", "created": "y", "is_shallow": True}],
            show_ignore=True,
        )
        snap = row.snapshot()
        self.assertTrue(snap.show_ignore)

    def test_snapshot_entries_reflects_current_state(self):
        row = self._make_row()
        snap = row.snapshot()
        # entries should be non-empty since "C" checkbox is checked
        self.assertTrue(any(e.get("cat") == "C" for e in snap.entries))

    def test_fen_and_played_move_stored(self):
        import chess
        move = chess.Move.from_uci("e2e4")
        fen = chess.STARTING_FEN
        row = _TagRowWidget(
            config={},
            preset="CLAMP",
            entries=[],
            custom_categories=[],
            move_label="1. e4",
            fen=fen,
            played_move=move,
            bg_rgb=[40, 40, 45],
            text_color=[200, 200, 200],
        )
        self.assertEqual(row._fen, fen)
        self.assertEqual(row._played_move, move)
        snap = row.snapshot()
        self.assertEqual(snap.fen, fen)
        self.assertEqual(snap.played_move, move)


@requires_qt
class TestShowTagsDialogExportButton(unittest.TestCase):
    def _make_dialog(self):
        game = _make_game_data()
        ctrl = _make_mock_controller(game)
        return ShowTagsDialog(config={}, games=[game], controller=ctrl)

    def test_export_pdf_button_exists(self):
        dlg = self._make_dialog()
        export_btn = dlg.findChild(QPushButton, "", options=Qt.FindChildOption.FindChildrenRecursively)
        buttons = [w for w in dlg.findChildren(QPushButton) if "Export" in w.text()]
        self.assertTrue(len(buttons) >= 1, "No Export button found in ShowTagsDialog")

    def test_export_pdf_button_enabled_when_rows_present(self):
        dlg = self._make_dialog()
        export_btn = next(
            (w for w in dlg.findChildren(QPushButton) if "Export" in w.text()), None
        )
        self.assertIsNotNone(export_btn)
        # Dialog has rows (the mock controller returns one row), so button should be enabled
        self.assertTrue(export_btn.isEnabled())


if _QT_OK:
    from PyQt6.QtCore import Qt


if __name__ == "__main__":
    unittest.main()
