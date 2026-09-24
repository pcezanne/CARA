"""Dialog for reviewing and editing Chess Log tags — single-game or multi-game."""

from __future__ import annotations

from io import StringIO
from typing import Any, Dict, List, Optional, Tuple

import chess
import chess.pgn

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
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

from app.models.chess_log_snapshot import TagRowSnapshot
from app.utils.chess_log_best_move import resolve_best_move_for_path
from app.utils.chess_log_preset_order import CLAMP_ORDER, CCT_ORDER
from app.utils.chess_log_prompts import THREE_BY_THREE_PROMPTS as _3X3_PROMPTS
from app.utils.pgn_variation_path import decode_path
from app.utils.player_matcher import game_player_is_black
from app.views.dialogs._tag_row_helpers import node_info as _node_info_fn, ply_for_path as _ply_for_path_fn
from app.views.style.style_manager import StyleManager
from app.views.widgets.mini_chessboard_widget import MiniChessBoardWidget

_PRESET_ORDER = ["CLAMP", "CCT", "3x3"]

_3X3_KEYS = list(_3X3_PROMPTS.keys())

# Scale matching manual analysis default (1.25 × 160 base = 200px board ≈ 204px widget)
_MINI_BOARD_SCALE = 1.25
_MINI_BOARD_PLACEHOLDER_PX = 204


def _normalize_entries(entries: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """(cat, why) tuples sorted for change detection."""
    return sorted((e.get("cat", ""), e.get("why", "")) for e in entries)


class _TagRowWidget(QFrame):
    """One row in the Show Tags list — one (path_key, preset) pair, always editable.

    Emits ``edited`` (with 300ms debounce) whenever the user changes a
    checkbox, why-text, or the ignore checkbox, so live-edit callers can
    persist immediately.  ShowTagsDialog ignores this signal — it still
    batches on OK.

    Pass ``show_ignore_checkbox=True`` to render the Ignore checkbox (used
    by ShowShallowTagsDialog).  When False (default), the original
    moment-level ``ignore_shallow`` value is preserved transparently through
    ``get_current_entries()`` without exposing UI for it.
    """

    edited = pyqtSignal()

    def __init__(
        self,
        config: Dict[str, Any],
        preset: str,
        entries: List[Dict[str, Any]],
        move_label: str,
        fen: Optional[str],
        played_move: Optional[chess.Move],
        bg_rgb: List[int],
        text_color: List[int],
        show_ignore_checkbox: bool = False,
        best_move: Optional[chess.Move] = None,
        is_flipped: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._preset = preset
        self._entries = entries
        self._config = config
        self._bg_rgb = bg_rgb
        self._text_color = text_color
        self._show_ignore_checkbox = show_ignore_checkbox
        self._preserved_ignore_shallow: bool = any(
            bool(e.get("ignore_shallow")) for e in entries
        )
        self._preserved_is_shallow: bool = any(
            bool(e.get("is_shallow")) for e in entries
        )

        self._fen: Optional[str] = fen
        self._played_move: Optional[chess.Move] = played_move
        self._best_move: Optional[chess.Move] = best_move
        self._is_flipped: bool = is_flipped

        self._checkboxes: Dict[str, QCheckBox] = {}
        self._why_texts: Dict[str, QPlainTextEdit] = {}
        self._header_label: Optional[QLabel] = None
        self._ignore_check: Optional[QCheckBox] = None

        self._edit_debounce = QTimer(self)
        self._edit_debounce.setSingleShot(True)
        self._edit_debounce.setInterval(300)
        self._edit_debounce.timeout.connect(self.edited.emit)

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

        # Move label header row (label + optional Ignore checkbox)
        tr, tg, tb = self._text_color
        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        header = QLabel(move_label)
        header.setStyleSheet(
            f"color: rgb({tr},{tg},{tb}); font-weight: bold; font-size: 11px;"
        )
        header_row.addWidget(header, 1)
        self._header_label = header

        if self._show_ignore_checkbox:
            warning_lbl = QLabel("⚠️")
            warning_lbl.setStyleSheet("border: none;")
            header_row.addWidget(warning_lbl)
            self._ignore_check = QCheckBox("Ignore")
            self._ignore_check.setChecked(self._preserved_ignore_shallow)
            self._ignore_check.setStyleSheet(f"color: rgb({tr},{tg},{tb});")
            self._ignore_check.stateChanged.connect(self._schedule_edited)
            header_row.addWidget(self._ignore_check)

        outer.addLayout(header_row)

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
                    is_flipped=self._is_flipped,
                    scale_factor=_MINI_BOARD_SCALE,
                    embedded=True,
                )
                board_widget.set_played_and_best(played_move, self._best_move)
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
                cb.stateChanged.connect(self._schedule_edited)
                cb_col.addWidget(cb)
                self._checkboxes[cat] = cb
        cols.addLayout(cb_col)

        # Column 3: text / notes (always editable).
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
                te.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                self._style_text_widget(te)
                te.textChanged.connect(self._schedule_edited)
                txt_col.addWidget(te)
                self._why_texts[key] = te
        else:
            why_text = self._entries[0].get("why", "") if self._entries else ""
            te = QPlainTextEdit(why_text)
            te.setMinimumHeight(50)
            te.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self._style_text_widget(te)
            te.textChanged.connect(self._schedule_edited)
            txt_col.addWidget(te)
            self._why_texts["why"] = te
        cols.addLayout(txt_col, 1)

    def _schedule_edited(self) -> None:
        """Restart the 300ms debounce timer on any input change."""
        self._edit_debounce.start()

    def _style_text_widget(self, te: QPlainTextEdit) -> None:
        tr, tg, tb = self._text_color
        dc = self._config.get("ui", {}).get("dialogs", {}).get("moment", {})
        inp = dc.get("inputs", {})
        ibg = inp.get("background_color", [30, 30, 35])
        ibr = inp.get("border_color", [60, 60, 65])
        te.setStyleSheet(
            f"color: rgb({tr},{tg},{tb}); "
            f"background-color: rgb({ibg[0]},{ibg[1]},{ibg[2]}); "
            f"border: 1px solid rgb({ibr[0]},{ibr[1]},{ibr[2]});"
        )

    def _categories_for_preset(self) -> List[str]:
        if self._preset == "CLAMP":
            return list(CLAMP_ORDER)
        if self._preset == "CCT":
            return list(CCT_ORDER)
        return []

    def get_current_entries(self) -> List[Dict[str, Any]]:
        """Return the current widget state as a list of entry dicts."""
        if self._show_ignore_checkbox:
            ignore = self._ignore_check is not None and self._ignore_check.isChecked()
        else:
            ignore = self._preserved_ignore_shallow

        def _annotate(d: Dict[str, Any]) -> Dict[str, Any]:
            if ignore:
                d["ignore_shallow"] = True
            if self._preserved_is_shallow:
                d["is_shallow"] = True
            return d

        if self._preset == "3x3":
            result = []
            for key in _3X3_KEYS:
                text = self._why_texts.get(key, QPlainTextEdit()).toPlainText().strip()
                if text:
                    result.append(_annotate({"preset": "3x3", "cat": key, "why": text}))
            return result
        why = self._why_texts.get("why", QPlainTextEdit()).toPlainText().strip()
        selected = [cat for cat, cb in self._checkboxes.items() if cb.isChecked()]
        if not selected:
            # Mirror MomentDialog.get_entries(): zero boxes + why → cat="" entry;
            # zero boxes + empty why → [] (intentional delete gesture).
            return [_annotate({"preset": self._preset, "cat": "", "why": why})] if why else []
        return [_annotate({"preset": self._preset, "cat": cat, "why": why}) for cat in selected]

    def snapshot(self):
        """Return current widget state as a TagRowSnapshot for PDF export."""
        return TagRowSnapshot(
            move_label=self._header_label.text() if self._header_label else "",
            preset=self._preset,
            entries=self.get_current_entries(),
            fen=self._fen,
            played_move=self._played_move,
            best_move=self._best_move,
            show_ignore=self._show_ignore_checkbox,
            is_flipped=self._is_flipped,
        )


class ShowTagsDialog(QDialog):
    """Scrollable, editable list of Chess Log tags.

    Accepts a list of GameData objects — pass a single-element list for the
    single-game (Show Tags) use case.  Multi-game usage inserts a game-header
    label between each game's rows.

    OK persists changes via ``controller.replace_entries_at_path_for_game``;
    Cancel discards all edits.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        games: List,
        controller,
        parent=None,
        player_name: str = "",
    ) -> None:
        super().__init__(parent)
        self.config = config
        self._controller = controller
        self._games = list(games)
        self._player_name = player_name or ""

        self._load_config()

        # Build (path_key, preset, entries) rows for all games in order.
        # _row_games and _row_pgn_games are parallel to _rows_data.
        self._rows_data: List[Tuple[str, str, List[Dict[str, Any]]]] = []
        self._row_games: List = []
        self._row_pgn_games: List[Optional[chess.pgn.Game]] = []

        for game in self._games:
            pgn_game = self._parse_pgn(game)
            tags = controller.get_tags_for_game(game)
            for path_key, preset, entries in self._build_rows_for_game(pgn_game, tags):
                self._rows_data.append((path_key, preset, entries))
                self._row_games.append(game)
                self._row_pgn_games.append(pgn_game)

        # Snapshot keyed by (game_number, path_key, preset)
        self._original_snapshot = {
            (self._row_games[i].game_number, pk, pr): list(entries)
            for i, (pk, pr, entries) in enumerate(self._rows_data)
        }
        self._row_widgets: List[_TagRowWidget] = []

        self._setup_ui()
        self.setWindowTitle(
            "Show Chess Logs for all games" if len(self._games) > 1 else "Chess Log Tags"
        )

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def _load_config(self) -> None:
        dc = self.config.get("ui", {}).get("dialogs", {}).get("moment", {})
        self._bg_rgb = dc.get("background_color", [40, 40, 45])
        self._border_rgb = dc.get("border_color", [60, 60, 65])
        self._text_color_rgb = dc.get("text_color", [200, 200, 200])
        self._separator_rgb = dc.get("separator_color", [70, 70, 75])
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

    @staticmethod
    def _build_rows_for_game(
        pgn_game: Optional[chess.pgn.Game],
        tags: Dict[str, List[Dict[str, Any]]],
    ) -> List[Tuple[str, str, List[Dict[str, Any]]]]:
        """Return sorted (path_key, preset, entries) tuples for one game."""
        preset_rank = {p: i for i, p in enumerate(_PRESET_ORDER)}
        rows: List[Tuple[int, int, str, str, List[Dict[str, Any]]]] = []

        for path_key, all_entries in tags.items():
            if not all_entries:
                continue
            path = decode_path(path_key)
            if path is None:
                continue
            ply = _ply_for_path_fn(pgn_game, path)

            by_preset: Dict[str, List[Dict[str, Any]]] = {}
            for entry in all_entries:
                p = entry.get("preset", "")
                by_preset.setdefault(p, []).append(entry)

            for preset, entries in by_preset.items():
                rank = preset_rank.get(preset, len(_PRESET_ORDER))
                rows.append((ply, rank, path_key, preset, entries))

        rows.sort(key=lambda r: (r[0], r[1]))
        return [(path_key, preset, entries) for _, _, path_key, preset, entries in rows]

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _make_separator(self) -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Plain)
        sep.setFixedHeight(1)
        sr, sg, sb = self._separator_rgb
        sep.setStyleSheet(f"background-color: rgb({sr},{sg},{sb}); border: none;")
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
        self.setStyleSheet(
            f"QDialog {{ background-color: rgb({br},{bg},{bb}); }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        if not self._rows_data:
            lbl = QLabel("No tagged moments found.")
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

            multi_game = len(self._games) > 1
            last_game = None

            for i, (path_key, preset, entries) in enumerate(self._rows_data):
                game = self._row_games[i]
                pgn_game = self._row_pgn_games[i]

                if multi_game and game is not last_game:
                    self._rows_layout.addWidget(self._make_game_header(game))
                    last_game = game
                elif i > 0:
                    self._rows_layout.addWidget(self._make_separator())

                fen, played_move, move_label = _node_info_fn(pgn_game, path_key)
                best_move = resolve_best_move_for_path(game, path_key, played_move, pgn_game)
                row_is_shallow = any(e.get("is_shallow") for e in entries)
                row_is_flipped = game_player_is_black(game, self._player_name)
                row_widget = _TagRowWidget(
                    self.config,
                    preset,
                    entries,
                    move_label,
                    fen or None,
                    played_move,
                    self._bg_rgb,
                    self._text_color_rgb,
                    show_ignore_checkbox=row_is_shallow,
                    best_move=best_move,
                    is_flipped=row_is_flipped,
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

        # Button bar: [Export to PDF]  stretch  Cancel | OK
        btn_row = QHBoxLayout()

        self._export_pdf_btn = QPushButton("Export to PDF")
        self._export_pdf_btn.setAutoDefault(False)
        self._export_pdf_btn.setFixedHeight(self._button_height)
        self._export_pdf_btn.setEnabled(bool(self._rows_data))
        self._export_pdf_btn.clicked.connect(self._on_export_pdf)
        btn_row.addWidget(self._export_pdf_btn)

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

        StyleManager.style_buttons(
            [self._export_pdf_btn, self._cancel_btn, self._ok_btn],
            self.config,
            self._bg_rgb,
            self._border_rgb,
        )

        self.setMinimumWidth(800)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_ok(self) -> None:
        for i, ((path_key, preset, _), row_widget) in enumerate(
            zip(self._rows_data, self._row_widgets)
        ):
            new_entries = row_widget.get_current_entries()
            game = self._row_games[i]
            original = self._original_snapshot.get((game.game_number, path_key, preset), [])
            if _normalize_entries(new_entries) != _normalize_entries(original):
                self._controller.replace_entries_at_path_for_game(
                    game, path_key, preset, new_entries
                )
        self.accept()

    def _on_export_pdf(self) -> None:
        from pathlib import Path
        from PyQt6.QtWidgets import QFileDialog
        from app.services.chess_log_pdf_service import (
            ChessLogPDFService,
            default_chess_log_tags_pdf_filename,
        )
        suggested = default_chess_log_tags_pdf_filename()
        path, _ = QFileDialog.getSaveFileName(
            self, "Export to PDF", suggested, "PDF Files (*.pdf)"
        )
        if not path:
            return

        # Group row widgets by game, preserving display order.
        tag_groups = []
        current_game = None
        current_rows = []
        current_header: Optional[str] = None
        multi_game = len(self._games) > 1

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

        ChessLogPDFService(self.config).export_tags(Path(path), tag_groups)
