"""Dialog for reviewing and editing all Chess Log tags in a game."""

from __future__ import annotations

from io import StringIO
from typing import Any, Dict, List, Optional, Tuple

import chess
import chess.pgn

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.utils.chess_log_preset_order import CLAMP_ORDER, CCT_ORDER
from app.utils.pgn_variation_path import decode_path, node_at_path
from app.views.style.style_manager import StyleManager
from app.views.widgets.mini_chessboard_widget import MiniChessBoardWidget

_PRESET_ORDER = ["CLAMP", "CCT", "3x3", "Custom"]

_3X3_KEYS = ["Why1", "Why2", "Why3"]
_3X3_PROMPTS = {
    "Why1": "Why did I make this move?",
    "Why2": "Why was it suboptimal?",
    "Why3": "Why is the engine's suggestion better?",
}

# Scale matching manual analysis default (1.25 × 160 base = 200px board ≈ 204px widget)
_MINI_BOARD_SCALE = 1.25
_MINI_BOARD_PLACEHOLDER_PX = 204


def _normalize_entries(entries: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """(cat, why) tuples sorted for change detection."""
    return sorted((e.get("cat", ""), e.get("why", "")) for e in entries)


class _TagRowWidget(QFrame):
    """One row in the Show Tags list — one (path_key, preset) pair, always editable."""

    def __init__(
        self,
        config: Dict[str, Any],
        preset: str,
        entries: List[Dict[str, Any]],
        custom_categories: List[str],
        move_label: str,
        fen: Optional[str],
        played_move: Optional[chess.Move],
        bg_rgb: List[int],
        text_color: List[int],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._preset = preset
        self._entries = entries
        self._custom_categories = custom_categories
        self._config = config
        self._bg_rgb = bg_rgb
        self._text_color = text_color

        self._checkboxes: Dict[str, QCheckBox] = {}
        self._why_texts: Dict[str, QPlainTextEdit] = {}

        self._setup(move_label, fen, played_move)

    def _setup(self, move_label: str, fen: Optional[str], played_move: Optional[chess.Move]) -> None:
        br, bg, bb = self._bg_rgb
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(
            f"background-color: rgb({br},{bg},{bb});"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(4)

        # Move label header
        tr, tg, tb = self._text_color
        header = QLabel(move_label)
        header.setStyleSheet(
            f"color: rgb({tr},{tg},{tb}); font-weight: bold; font-size: 11px;"
        )
        outer.addWidget(header)

        # Three-column row: board | checkboxes | text
        cols = QHBoxLayout()
        cols.setSpacing(10)
        outer.addLayout(cols)

        # Column 1: board miniature (played move arrow, manual-analysis scale)
        if fen:
            try:
                board_widget = MiniChessBoardWidget(
                    self._config,
                    fen,
                    is_flipped=False,
                    scale_factor=_MINI_BOARD_SCALE,
                    embedded=True,
                )
                if played_move is not None:
                    board_widget.set_move(played_move, True)
                cols.addWidget(board_widget, 0, Qt.AlignmentFlag.AlignTop)
            except Exception:
                ph = QLabel("Board\nunavailable")
                ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
                ph.setFixedSize(_MINI_BOARD_PLACEHOLDER_PX, _MINI_BOARD_PLACEHOLDER_PX)
                ph.setStyleSheet(f"color: rgb({tr},{tg},{tb});")
                cols.addWidget(ph, 0, Qt.AlignmentFlag.AlignTop)
        else:
            ph = QLabel("")
            ph.setFixedSize(_MINI_BOARD_PLACEHOLDER_PX, _MINI_BOARD_PLACEHOLDER_PX)
            cols.addWidget(ph, 0, Qt.AlignmentFlag.AlignTop)

        # Column 2: checkboxes (blank for 3x3)
        cb_col = QVBoxLayout()
        cb_col.setSpacing(3)
        cb_col.setAlignment(Qt.AlignmentFlag.AlignTop)
        if self._preset != "3x3":
            ticked = {e.get("cat", "") for e in self._entries}
            cats = self._categories_for_preset()
            for cat in cats:
                cb = QCheckBox(cat)
                cb.setChecked(cat in ticked)
                cb.setStyleSheet(f"color: rgb({tr},{tg},{tb});")
                cb_col.addWidget(cb)
                self._checkboxes[cat] = cb
        cols.addLayout(cb_col)

        # Column 3: text / notes (always editable; height fitted after show).
        # No alignment set on txt_col — alignment=0 lets it fill the allocated region.
        txt_col = QVBoxLayout()
        txt_col.setSpacing(4)
        if self._preset == "3x3":
            why_map = {e.get("cat", ""): e.get("why", "") for e in self._entries}
            for key in _3X3_KEYS:
                prompt_lbl = QLabel(_3X3_PROMPTS[key])
                prompt_lbl.setStyleSheet(
                    f"color: rgb({tr},{tg},{tb}); font-size: 10px; font-style: italic;"
                )
                txt_col.addWidget(prompt_lbl)
                te = QPlainTextEdit(why_map.get(key, ""))
                te.setMinimumHeight(50)
                te.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                self._style_text_widget(te)
                txt_col.addWidget(te)
                self._why_texts[key] = te
        else:
            why_text = self._entries[0].get("why", "") if self._entries else ""
            te = QPlainTextEdit(why_text)
            te.setMinimumHeight(50)
            te.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self._style_text_widget(te)
            txt_col.addWidget(te)
            self._why_texts["why"] = te
        txt_col.addStretch(1)
        cols.addLayout(txt_col, 1)

    def _style_text_widget(self, te: QPlainTextEdit) -> None:
        tr, tg, tb = self._text_color
        te.setStyleSheet(
            f"color: rgb({tr},{tg},{tb}); background-color: rgb(30,30,35);"
            "border: 1px solid rgb(60,60,65);"
        )

    def _categories_for_preset(self) -> List[str]:
        if self._preset == "CLAMP":
            return list(CLAMP_ORDER)
        if self._preset == "CCT":
            return list(CCT_ORDER)
        return list(self._custom_categories)

    def fit_text_heights(self) -> None:
        """Set each text widget to exactly fit its current content.

        Called from ShowTagsDialog.showEvent after layout is complete.
        Height is fixed after fitting — vertical scrollbar appears if the
        user then types more than fits in that height.
        """
        for te in self._why_texts.values():
            doc = te.document()
            content_h = int(doc.documentLayout().documentSize().height())
            te.setFixedHeight(max(50, min(content_h + 10, 400)))

    def get_current_entries(self) -> List[Dict[str, Any]]:
        """Return the current widget state as a list of {preset, cat, why} dicts."""
        if self._preset == "3x3":
            result = []
            for key in _3X3_KEYS:
                text = self._why_texts.get(key, QPlainTextEdit()).toPlainText().strip()
                if text:
                    result.append({"preset": "3x3", "cat": key, "why": text})
            return result
        why = self._why_texts.get("why", QPlainTextEdit()).toPlainText().strip()
        selected = [cat for cat, cb in self._checkboxes.items() if cb.isChecked()]
        if not selected:
            # Mirror MomentDialog.get_entries(): zero boxes + why → cat="" entry;
            # zero boxes + empty why → [] (intentional delete gesture).
            return [{"preset": self._preset, "cat": "", "why": why}] if why else []
        return [{"preset": self._preset, "cat": cat, "why": why} for cat in selected]


class ShowTagsDialog(QDialog):
    """Scrollable list of all Chess Log tags in a game, always editable.

    Rows are sorted by ply ascending, then preset in canonical order.
    OK persists any changes back to the controller's in-memory cache
    (same two-step save pattern as Tag This Moment).
    """

    def __init__(
        self,
        config: Dict[str, Any],
        game_data,
        controller,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self._controller = controller

        self._load_config()

        self._pgn_game = self._parse_pgn(game_data)
        tags = controller.get_tags_for_current_game()
        self._rows_data: List[Tuple[str, str, List[Dict[str, Any]]]] = self._build_rows_data(tags)
        self._original_snapshot = {
            (path_key, preset): list(entries)
            for path_key, preset, entries in self._rows_data
        }
        self._row_widgets: List[_TagRowWidget] = []

        self._setup_ui()
        self.setWindowTitle("Chess Log Tags")

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def _load_config(self) -> None:
        dc = self.config.get("ui", {}).get("dialogs", {}).get("moment", {})
        self._bg_rgb = dc.get("background_color", [40, 40, 45])
        self._border_rgb = dc.get("border_color", [60, 60, 65])
        self._text_color_rgb = dc.get("text_color", [200, 200, 200])
        self._button_width = dc.get("button_width", 100)
        self._button_height = dc.get("button_height", 28)

    # ------------------------------------------------------------------
    # Data building
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_pgn(game_data) -> Optional[chess.pgn.Game]:
        try:
            pgn = getattr(game_data, "pgn", None)
            if not pgn:
                return None
            return chess.pgn.read_game(StringIO(pgn))
        except Exception:
            return None

    def _build_rows_data(
        self, tags: Dict[str, List[Dict[str, Any]]]
    ) -> List[Tuple[str, str, List[Dict[str, Any]]]]:
        """Return sorted (path_key, preset, entries) tuples — one per (move, preset) pair."""
        preset_rank = {p: i for i, p in enumerate(_PRESET_ORDER)}
        rows: List[Tuple[int, int, str, str, List[Dict[str, Any]]]] = []

        for path_key, all_entries in tags.items():
            if not all_entries:
                continue
            path = decode_path(path_key)
            if path is None:
                continue
            ply = self._ply_for_path(path)

            by_preset: Dict[str, List[Dict[str, Any]]] = {}
            for entry in all_entries:
                p = entry.get("preset", "")
                by_preset.setdefault(p, []).append(entry)

            for preset, entries in by_preset.items():
                rank = preset_rank.get(preset, len(_PRESET_ORDER))
                rows.append((ply, rank, path_key, preset, entries))

        rows.sort(key=lambda r: (r[0], r[1]))
        return [(path_key, preset, entries) for _, _, path_key, preset, entries in rows]

    def _ply_for_path(self, path) -> int:
        if self._pgn_game is None:
            return len(path)
        node = node_at_path(self._pgn_game, path)
        if node is None:
            return len(path)
        try:
            return node.ply()
        except AttributeError:
            pass
        parent = getattr(node, "parent", None)
        if parent is None:
            return len(path)
        pre = parent.board()
        return (pre.fullmove_number - 1) * 2 + (0 if pre.turn == chess.WHITE else 1)

    def _node_info(self, path_key: str) -> Tuple[str, Optional[chess.Move], str]:
        """Return (fen_after_move, played_move, move_label) for display."""
        if self._pgn_game is None:
            return ("", None, path_key)
        path = decode_path(path_key)
        if not path:
            return ("", None, path_key)
        node = node_at_path(self._pgn_game, path)
        if node is None or node.move is None:
            return ("", None, path_key)
        try:
            pre_board = node.parent.board()
            san = pre_board.san(node.move)
            fullmove = pre_board.fullmove_number
            if pre_board.turn == chess.WHITE:
                move_label = f"{fullmove}. {san}"
            else:
                move_label = f"{fullmove}… {san}"
            fen = node.board().fen()
            return (fen, node.move, move_label)
        except Exception:
            return ("", None, path_key)

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

    def _setup_ui(self) -> None:
        br, bg, bb = self._bg_rgb
        self.setStyleSheet(
            f"QDialog {{ background-color: rgb({br},{bg},{bb}); }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        if not self._rows_data:
            lbl = QLabel("No tagged moments found in this game.")
            tr, tg, tb = self._text_color_rgb
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

            for i, (path_key, preset, entries) in enumerate(self._rows_data):
                if i > 0:
                    self._rows_layout.addWidget(self._make_separator())

                fen, played_move, move_label = self._node_info(path_key)
                custom_cats = self._controller.get_custom_categories()
                row_widget = _TagRowWidget(
                    self.config,
                    preset,
                    entries,
                    custom_cats,
                    move_label,
                    fen or None,
                    played_move,
                    self._bg_rgb,
                    self._text_color_rgb,
                )
                self._rows_layout.addWidget(row_widget)
                self._row_widgets.append(row_widget)

            self._rows_layout.addStretch(1)
            scroll.setWidget(content)

            StyleManager.style_scroll_area(
                scroll,
                self.config,
                self._bg_rgb,
                self._border_rgb,
                border_radius=0,
                include_scroll_area_border=False,
            )

            screen = self.screen()
            if screen:
                max_h = int(screen.availableGeometry().height() * 0.85)
            else:
                max_h = 800
            scroll.setMinimumHeight(min(400, max_h))
            scroll.setMaximumHeight(max_h)
            root.addWidget(scroll)

        # Button bar: Cancel | OK
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setAutoDefault(False)
        self._cancel_btn.setFixedSize(self._button_width, self._button_height)
        self._cancel_btn.clicked.connect(self.reject)

        self._ok_btn = QPushButton("OK")
        self._ok_btn.setDefault(True)
        self._ok_btn.setAutoDefault(True)
        self._ok_btn.setFixedSize(self._button_width, self._button_height)
        self._ok_btn.clicked.connect(self._on_ok)

        btn_row.addWidget(self._cancel_btn)
        btn_row.addSpacing(6)
        btn_row.addWidget(self._ok_btn)
        root.addLayout(btn_row)

        # 1/3 wider than the original 600px baseline
        self.setMinimumWidth(800)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Fit text widget heights to content now that layout widths are known.
        # Height is then fixed so vertical scrollbar appears if the user types more.
        QTimer.singleShot(0, self._fit_text_heights)

    def _fit_text_heights(self) -> None:
        for rw in self._row_widgets:
            rw.fit_text_heights()

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_ok(self) -> None:
        for (path_key, preset, _), row_widget in zip(self._rows_data, self._row_widgets):
            new_entries = row_widget.get_current_entries()
            original = self._original_snapshot.get((path_key, preset), [])
            if _normalize_entries(new_entries) != _normalize_entries(original):
                self._controller.replace_entries_at_path(path_key, preset, new_entries)
        self.accept()
