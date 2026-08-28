"""Chess Log menu definition for MainWindow."""

from __future__ import annotations

from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QMenuBar

from app.utils.themed_icon import (
    SVG_CONTEXT_DELETE,
    SVG_MENU_SAVE,
    set_menubar_themable_action_icon,
)


def setup_chess_log_menu(mw, menu_bar: QMenuBar) -> None:
    chess_log_menu = menu_bar.addMenu("Chess Log")
    mw._apply_menu_styling(chess_log_menu)

    mw.chess_log_settings_action = QAction("Chess Log Settings…", mw)
    mw.chess_log_settings_action.triggered.connect(mw._show_chess_log_settings)
    chess_log_menu.addAction(mw.chess_log_settings_action)

    chess_log_menu.addSeparator()

    mw.clear_chess_log_action = QAction("Clear Chess Log for current game", mw)
    mw.clear_chess_log_action.setShortcut(QKeySequence("Ctrl+Shift+L"))
    set_menubar_themable_action_icon(mw, mw.clear_chess_log_action, SVG_CONTEXT_DELETE)
    mw.clear_chess_log_action.triggered.connect(mw._clear_chess_log_for_current_game)
    chess_log_menu.addAction(mw.clear_chess_log_action)

    mw.save_chess_log_action = QAction("Save Chess Log to current game", mw)
    mw.save_chess_log_action.setShortcut(QKeySequence("Ctrl+Alt+L"))
    set_menubar_themable_action_icon(mw, mw.save_chess_log_action, SVG_MENU_SAVE)
    mw.save_chess_log_action.triggered.connect(mw._save_chess_log_for_current_game)
    chess_log_menu.addAction(mw.save_chess_log_action)

    chess_log_menu.addSeparator()

    mw.highlight_chess_log_moves_action = QAction("Highlight tagged moves in moves list", mw)
    mw.highlight_chess_log_moves_action.setCheckable(True)
    mw.highlight_chess_log_moves_action.setChecked(False)
    mw.highlight_chess_log_moves_action.triggered.connect(mw._on_highlight_chess_log_moves_toggled)
    chess_log_menu.addAction(mw.highlight_chess_log_moves_action)
