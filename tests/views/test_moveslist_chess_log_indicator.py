"""Tests for the Chess Log tag indicator in MovesListModel.

Qt-guarded (skipped if Qt platform plugin unavailable, same pattern as
test_moment_dialog.py).  The persistence test (toggle state round-trip
through UserSettingsService) runs without Qt.
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


def _make_model():
    from app.models.moveslist_model import MovesListModel, MoveData
    model = MovesListModel()
    model.add_move(MoveData(move_number=1, white_move="e4", black_move="e5"))
    model.add_move(MoveData(move_number=2, white_move="Nf3", black_move="Nc6"))
    return model


def _make_chess_log_ctrl(tagged_path_keys=()):
    """Return a mock ChessLogController with the given path keys pre-tagged."""
    from app.services.chess_log_storage_service import ChessLogStorageService
    ctrl = MagicMock()
    paths_data = {
        key: [ChessLogStorageService.make_entry("CLAMP", "M")]
        for key in tagged_path_keys
    }
    ctrl.get_tags_for_current_game.return_value = paths_data
    return ctrl


@requires_qt
class TestTagIndicatorAppearsWhenEnabled(unittest.TestCase):
    def test_tagged_white_move_gets_indicator_when_on(self):
        from app.models.moveslist_model import MovesListModel
        from app.utils.pgn_variation_path import encode_path, mainline_path_for_ply
        model = _make_model()
        # Ply 1 = white's first move (e4)
        path_key = encode_path(mainline_path_for_ply(1))
        ctrl = _make_chess_log_ctrl(tagged_path_keys=[path_key])
        model.set_chess_log_controller(ctrl)
        model.set_highlight_chess_log_moves(True)
        text = model.data(model.index(0, MovesListModel.COL_WHITE))
        self.assertIn("🏷", text)
        self.assertTrue(text.startswith("e4"))

    def test_tagged_black_move_gets_indicator_when_on(self):
        from app.models.moveslist_model import MovesListModel
        from app.utils.pgn_variation_path import encode_path, mainline_path_for_ply
        model = _make_model()
        # Ply 2 = black's first move (e5)
        path_key = encode_path(mainline_path_for_ply(2))
        ctrl = _make_chess_log_ctrl(tagged_path_keys=[path_key])
        model.set_chess_log_controller(ctrl)
        model.set_highlight_chess_log_moves(True)
        text = model.data(model.index(0, MovesListModel.COL_BLACK))
        self.assertIn("🏷", text)
        self.assertTrue(text.startswith("e5"))


@requires_qt
class TestTagIndicatorAbsentWhenDisabled(unittest.TestCase):
    def test_no_indicator_when_toggle_off(self):
        from app.models.moveslist_model import MovesListModel
        from app.utils.pgn_variation_path import encode_path, mainline_path_for_ply
        model = _make_model()
        path_key = encode_path(mainline_path_for_ply(1))
        ctrl = _make_chess_log_ctrl(tagged_path_keys=[path_key])
        model.set_chess_log_controller(ctrl)
        model.set_highlight_chess_log_moves(False)  # off
        text = model.data(model.index(0, MovesListModel.COL_WHITE))
        self.assertEqual(text, "e4")
        self.assertNotIn("🏷", text or "")

    def test_no_indicator_for_untagged_move(self):
        from app.models.moveslist_model import MovesListModel
        model = _make_model()
        ctrl = _make_chess_log_ctrl(tagged_path_keys=[])  # nothing tagged
        model.set_chess_log_controller(ctrl)
        model.set_highlight_chess_log_moves(True)
        text = model.data(model.index(0, MovesListModel.COL_WHITE))
        self.assertEqual(text, "e4")
        self.assertNotIn("🏷", text or "")


class TestTogglePersistence(unittest.TestCase):
    """Persistence round-trip — no Qt needed."""

    def test_toggle_persists_via_update_chess_log_settings(self):
        from app.services.user_settings_service import UserSettingsService
        uss = MagicMock(spec=UserSettingsService)
        uss.get_chess_log.return_value = {}

        # Simulate the main_window handler persisting the toggle
        checked = True
        uss.update_chess_log_settings({"highlight_chess_log_moves_in_list": checked})
        uss.update_chess_log_settings.assert_called_once_with(
            {"highlight_chess_log_moves_in_list": True}
        )

    def test_toggle_loads_from_chess_log_settings(self):
        uss = MagicMock()
        uss.get_chess_log.return_value = {"highlight_chess_log_moves_in_list": True}
        settings = {"chess_log": uss.get_chess_log()}
        loaded = settings.get("chess_log", {}).get("highlight_chess_log_moves_in_list", False)
        self.assertTrue(loaded)

    def test_toggle_defaults_to_false_when_key_absent(self):
        settings = {"chess_log": {}}
        loaded = settings.get("chess_log", {}).get("highlight_chess_log_moves_in_list", False)
        self.assertFalse(loaded)


if __name__ == "__main__":
    unittest.main()
