"""Dialog that shows only the shallow-noted rows from the current corpus.

Live-edit: every change is immediately persisted to the multi-game cache via
``controller.replace_entries_at_path_for_game``.  No Cancel/OK — just Close.

The Ignore checkbox (via ``_TagRowWidget(show_ignore_checkbox=True)``) lets
the user dismiss rows from future ``flag_shallow_notes()`` runs.  The row
stays visible for the rest of this session; it disappears on the next open.
"""

from __future__ import annotations

from io import StringIO
from typing import Any, Dict, List, Optional, Set, Tuple

import chess.pgn

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.utils.pgn_variation_path import decode_path
from app.views.dialogs._tag_row_helpers import node_info as _node_info_fn, ply_for_path as _ply_for_path_fn
from app.views.dialogs.show_tags_dialog import _TagRowWidget, _PRESET_ORDER
from app.views.style.style_manager import StyleManager


class ShowShallowTagsDialog(QDialog):
    """Live-edit dialog listing only the shallow-flagged rows.

    Args:
        config: application config dict.
        games: list of GameData objects in scope (same list ``flag_shallow_notes`` used).
        controller: ChessLogController instance (not ChessLogChartsController).
        shallow_keys: set of (game_number, path_key, preset) tuples returned by
            ``flag_shallow_notes()``.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        games: List,
        controller,
        shallow_keys: Set[Tuple[int, str, str]],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._controller = controller
        self._shallow_keys = shallow_keys

        self._load_config()

        # Build rows filtered to shallow_keys only.
        # Parallel lists: _rows (path_key, preset, entries), _row_games, _row_pgn_games.
        self._rows: List[Tuple[str, str, List[Dict[str, Any]]]] = []
        self._row_games: List = []
        self._row_pgn_games: List = []

        preset_rank = {p: i for i, p in enumerate(_PRESET_ORDER)}

        for game in games:
            pgn_game = self._parse_pgn(game)
            tags = controller.get_tags_for_game(game)

            game_rows: List[Tuple[int, int, str, str, List[Dict[str, Any]]]] = []
            for path_key, all_entries in tags.items():
                if not all_entries:
                    continue
                path = decode_path(path_key)
                if path is None:
                    continue

                by_preset: Dict[str, List[Dict[str, Any]]] = {}
                for entry in all_entries:
                    p = entry.get("preset", "")
                    by_preset.setdefault(p, []).append(entry)

                for preset, entries in by_preset.items():
                    if (game.game_number, path_key, preset) not in shallow_keys:
                        continue
                    ply = _ply_for_path_fn(pgn_game, path)
                    rank = preset_rank.get(preset, len(_PRESET_ORDER))
                    game_rows.append((ply, rank, path_key, preset, entries))

            game_rows.sort(key=lambda r: (r[0], r[1]))
            for _, _, path_key, preset, entries in game_rows:
                self._rows.append((path_key, preset, entries))
                self._row_games.append(game)
                self._row_pgn_games.append(pgn_game)

        self._row_widgets: List[_TagRowWidget] = []
        self._rows_layout = None
        self._setup_ui()
        self.setWindowTitle("Show Shallow Tags")

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def _load_config(self) -> None:
        dc = self._config.get("ui", {}).get("dialogs", {}).get("moment", {})
        self._bg_rgb = dc.get("background_color", [40, 40, 45])
        self._border_rgb = dc.get("border_color", [60, 60, 65])
        self._text_color_rgb = dc.get("text_color", [200, 200, 200])
        self._button_width = dc.get("button_width", 100)
        self._button_height = dc.get("button_height", 28)

    @staticmethod
    def _parse_pgn(game_data):
        try:
            pgn = getattr(game_data, "pgn", None)
            if not pgn:
                return None
            return chess.pgn.read_game(StringIO(pgn))
        except Exception:
            return None

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _make_separator(self) -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Plain)
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: rgb(70, 70, 75); border: none;")
        return sep

    def _make_game_header(self, game) -> QLabel:
        _white = str(getattr(game, "white", "") or "").strip() or "Unknown"
        _black = str(getattr(game, "black", "") or "").strip() or "Unknown"
        _result = str(getattr(game, "result", "") or "").strip() or "*"
        _date = str(getattr(game, "date", "") or "").strip() or "????.??.??"
        try:
            _moves = int(getattr(game, "moves", 0) or 0)
        except (TypeError, ValueError):
            _moves = 0
        text = f"{_white} - {_black} {_result} ({_date} - {_moves} moves)"
        label = QLabel(text)
        br, bg, bb = self._bg_rgb
        tr, tg, tb = self._text_color_rgb
        bor, bog, bob = self._border_rgb
        label.setStyleSheet(
            f"background-color: rgb({min(255, br+20)},{min(255, bg+20)},{min(255, bb+20)}); "
            f"color: rgb({tr},{tg},{tb}); "
            f"padding: 3px 8px; "
            f"border: 1px solid rgb({bor},{bog},{bob});"
        )
        return label

    def _setup_ui(self) -> None:
        br, bg, bb = self._bg_rgb
        self.setStyleSheet(f"QDialog {{ background-color: rgb({br},{bg},{bb}); }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        if not self._rows:
            tr, tg, tb = self._text_color_rgb
            lbl = QLabel("No shallow notes found.")
            lbl.setStyleSheet(f"color: rgb({tr},{tg},{tb});")
            root.addWidget(lbl)
        else:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.setFrameShape(QFrame.Shape.NoFrame)

            content = QWidget()
            self._rows_layout = QVBoxLayout(content)
            self._rows_layout.setSpacing(0)
            self._rows_layout.setContentsMargins(0, 0, 0, 0)
            self._rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            rows_layout = self._rows_layout

            multi_game = len(set(id(g) for g in self._row_games)) > 1
            last_game = None

            for i, (path_key, preset, entries) in enumerate(self._rows):
                game = self._row_games[i]
                pgn_game = self._row_pgn_games[i]

                if multi_game and game is not last_game:
                    rows_layout.addWidget(self._make_game_header(game))
                    last_game = game
                elif i > 0:
                    rows_layout.addWidget(self._make_separator())

                fen, played_move, move_label = _node_info_fn(pgn_game, path_key)
                row_widget = _TagRowWidget(
                    self._config,
                    preset,
                    entries,
                    move_label,
                    fen or None,
                    played_move,
                    self._bg_rgb,
                    self._text_color_rgb,
                    show_ignore_checkbox=True,
                )
                # Live edit: persist immediately on any change
                row_widget.edited.connect(
                    self._make_live_edit_handler(game, path_key, preset, row_widget)
                )
                rows_layout.addWidget(row_widget)
                self._row_widgets.append(row_widget)

            rows_layout.addStretch(1)
            scroll.setWidget(content)

            StyleManager.style_scroll_area(
                scroll,
                self._config,
                self._bg_rgb,
                self._border_rgb,
                border_radius=0,
                include_scroll_area_border=False,
            )

            screen = self.screen()
            max_h = int(screen.availableGeometry().height() * 0.85) if screen else 800
            scroll.setMinimumHeight(min(400, max_h))
            scroll.setMaximumHeight(max_h)
            root.addWidget(scroll)

        btn_row = QHBoxLayout()

        has_rows = bool(self._rows)
        self._export_pdf_btn = QPushButton("Export to PDF")
        self._export_pdf_btn.setAutoDefault(False)
        self._export_pdf_btn.setFixedHeight(self._button_height)
        self._export_pdf_btn.setEnabled(has_rows)
        self._export_pdf_btn.clicked.connect(self._on_export_pdf)
        btn_row.addWidget(self._export_pdf_btn)

        btn_row.addStretch(1)
        self._close_btn = QPushButton("Close")
        self._close_btn.setDefault(True)
        self._close_btn.setAutoDefault(True)
        self._close_btn.setFixedSize(self._button_width, self._button_height)
        self._close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._close_btn)
        root.addLayout(btn_row)

        StyleManager.style_buttons(
            [self._export_pdf_btn, self._close_btn],
            self._config,
            self._bg_rgb,
            self._border_rgb,
        )

        self.setMinimumWidth(800)

    def _on_export_pdf(self) -> None:
        from pathlib import Path
        from PyQt6.QtWidgets import QFileDialog
        from app.services.chess_log_pdf_service import (
            ChessLogPDFService,
            default_chess_log_tags_pdf_filename,
        )
        suggested = default_chess_log_tags_pdf_filename(is_shallow_only=True)
        path, _ = QFileDialog.getSaveFileName(
            self, "Export to PDF", suggested, "PDF Files (*.pdf)"
        )
        if not path:
            return

        multi_game = len(set(id(g) for g in self._row_games)) > 1
        tag_groups = []
        current_game = None
        current_rows = []
        current_header = None

        for i, row_widget in enumerate(self._row_widgets):
            game = self._row_games[i]
            if game is not current_game:
                if current_rows:
                    tag_groups.append({"header": current_header, "rows": current_rows})
                current_game = game
                current_rows = []
                if multi_game:
                    white = str(getattr(game, "white", "") or "").strip() or "Unknown"
                    black = str(getattr(game, "black", "") or "").strip() or "Unknown"
                    result = str(getattr(game, "result", "") or "").strip() or "*"
                    date = str(getattr(game, "date", "") or "").strip() or "????.??.??"
                    moves = getattr(game, "moves", 0) or 0
                    current_header = f"{white} - {black} {result} ({date} - {moves} moves)"
                else:
                    current_header = None
            current_rows.append(row_widget.snapshot())

        if current_rows:
            tag_groups.append({"header": current_header, "rows": current_rows})

        ChessLogPDFService(self._config).export_tags(
            Path(path), tag_groups, is_shallow_only=True
        )

    def _make_live_edit_handler(self, game, path_key: str, preset: str, row: _TagRowWidget):
        def _handler():
            self._controller.replace_entries_at_path_for_game(
                game, path_key, preset, row.get_current_entries()
            )
        return _handler
