"""Dialog for reviewing and editing Chess Log tags — single-game or multi-game."""

from __future__ import annotations

import hashlib
from io import StringIO
from typing import Any, Dict, List, Optional, Tuple

import chess
import chess.pgn

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QFont
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
from app.services.chess_log_storage_service import ChessLogStorageService
from app.utils.chess_log_best_move import resolve_best_move_for_path
from app.utils.chess_log_preset_order import CLAMP_ORDER, CCT_ORDER
from app.utils.chess_log_prompts import THREE_BY_THREE_PROMPTS as _3X3_PROMPTS
from app.utils.pgn_variation_path import decode_path
from app.views.dialogs._tag_row_helpers import node_info as _node_info_fn, ply_for_path as _ply_for_path_fn
from app.views.style.style_manager import StyleManager
from app.views.widgets.mini_chessboard_widget import MiniChessBoardWidget

_PRESET_ORDER = ["CLAMP", "CCT", "3x3"]

_3X3_KEYS = list(_3X3_PROMPTS.keys())

# Scale matching manual analysis default (1.25 × 160 base = 200px board ≈ 204px widget)
_MINI_BOARD_SCALE = 1.25
_MINI_BOARD_PLACEHOLDER_PX = 204


def _normalize_entries(entries: List[Dict[str, Any]]) -> List[Tuple]:
    """(cat, why, ignore_shallow, ignore_text_hash, is_shallow, is_vague) tuples sorted for change detection."""
    return sorted(
        (
            e.get("cat", ""), e.get("why", ""),
            bool(e.get("ignore_shallow")), e.get("ignore_text_hash"),
            bool(e.get("is_shallow")), bool(e.get("is_vague")),
        )
        for e in entries
    )


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

        # Per-entry preserved flags, keyed by cat. For each entry, validate
        # ignore_text_hash against the stored why text; drop Ignore on mismatch.
        self._preserved_per_cat: Dict[str, Dict[str, Any]] = {}
        for e in entries:
            cat = e.get("cat", "")
            why = (e.get("why") or "").strip()
            ignore_shallow = ChessLogStorageService.is_entry_ignore_honoured(e)
            ignore_text_hash = e.get("ignore_text_hash") if ignore_shallow else None
            is_shallow = bool(e.get("is_shallow", False))
            is_vague = bool(e.get("is_vague", False))
            self._preserved_per_cat[cat] = {
                "ignore_shallow": ignore_shallow,
                "ignore_text_hash": ignore_text_hash,
                "is_shallow": is_shallow,
                "is_vague": is_vague,
                "original_why": why,
            }

        # Original why text for CLAMP/CCT text-change detection (all entries share one why).
        self._original_why_clamp_cct: str = (
            (entries[0].get("why") or "").strip()
            if entries and preset != "3x3"
            else ""
        )

        self._preserved_ignore_shallow: bool = any(
            d.get("ignore_shallow", False) for d in self._preserved_per_cat.values()
        )
        self._preserved_is_shallow: bool = any(
            bool(e.get("is_shallow")) for e in entries
        )
        self._preserved_is_vague: bool = any(
            bool(e.get("is_vague")) for e in entries
        )

        self._fen: Optional[str] = fen
        self._played_move: Optional[chess.Move] = played_move
        self._best_move: Optional[chess.Move] = best_move
        self._is_flipped: bool = is_flipped

        self._checkboxes: Dict[str, QCheckBox] = {}
        self._why_texts: Dict[str, QPlainTextEdit] = {}
        self._header_label: Optional[QLabel] = None
        self._ignore_check: Optional[QCheckBox] = None
        self._shallow_chip: Optional[QLabel] = None
        self._vague_chip: Optional[QLabel] = None
        # Per-answer Ignore checkboxes for 3x3 rows (keyed by Why cat name).
        self._ignore_checks: Dict[str, QCheckBox] = {}
        # Per-answer chips for 3x3 rows — used for real-time opacity updates.
        self._chips_per_cat: Dict[str, QLabel] = {}

        self._edit_debounce = QTimer(self)
        self._edit_debounce.setSingleShot(True)
        self._edit_debounce.setInterval(300)
        self._edit_debounce.timeout.connect(self.edited.emit)

        self._load_font_config(config)
        self._setup(move_label, fen, played_move)

    def _load_font_config(self, config: Dict[str, Any]) -> None:
        from app.utils.font_utils import resolve_font_family, scale_font_size
        st = config.get("ui", {}).get("dialogs", {}).get("show_tags", {})
        self._label_font_family = resolve_font_family(st.get("label_font_family", "Helvetica Neue"))
        self._label_font_size = int(scale_font_size(st.get("label_font_size", 11)))
        st_inp = st.get("inputs", {})
        self._input_font_family = resolve_font_family(st_inp.get("font_family", "Helvetica Neue"))
        self._input_font_size = int(scale_font_size(st_inp.get("font_size", 11)))
        self._why_min_lines = int(st.get("why_minimum_lines", 3))
        self._3x3_min_lines = int(st.get("three_by_three_edit_minimum_lines", 3))

    def _make_chip(self, kind: str) -> QLabel:
        """Return a styled QLabel chip for 'shallow' or 'vague_lesson'."""
        defaults = {
            "shallow": ([185, 70, 70], [255, 255, 255], "Shallow"),
            "vague_lesson": ([195, 145, 55], [255, 255, 255], "Vague lesson"),
        }
        def_bg, def_tc, def_text = defaults.get(kind, ([128, 128, 128], [255, 255, 255], kind))
        chip_cfg = (
            self._config.get("ui", {}).get("dialogs", {})
            .get("shallow", {}).get("labels", {}).get(kind, {})
        )
        bg = chip_cfg.get("background_color", def_bg)
        tc = chip_cfg.get("text_color", def_tc)
        text = chip_cfg.get("text", def_text)
        tooltip = chip_cfg.get("tooltip", "")
        lbl = QLabel(text)
        lbl.setFont(QFont(self._label_font_family, max(8, self._label_font_size - 1)))
        lbl.setStyleSheet(
            f"background-color: rgb({bg[0]},{bg[1]},{bg[2]}); "
            f"color: rgb({tc[0]},{tc[1]},{tc[2]}); "
            f"border-radius: 3px; padding: 1px 5px; border: none;"
        )
        if tooltip:
            lbl.setToolTip(tooltip)
        return lbl

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
        header.setFont(QFont(self._label_font_family, self._label_font_size))
        header.setStyleSheet(f"color: rgb({tr},{tg},{tb}); font-weight: bold;")
        header_row.addWidget(header, 1)
        self._header_label = header

        # For CLAMP/CCT: chips stay on the move-header. For 3x3: chips move to
        # the per-answer question lines (rendered in the txt_col loop below).
        if self._preset != "3x3":
            from PyQt6.QtWidgets import QGraphicsOpacityEffect as _OpEff
            if self._preserved_is_shallow:
                chip = self._make_chip("shallow")
                if self._preserved_ignore_shallow:
                    eff = _OpEff(chip); eff.setOpacity(0.4); chip.setGraphicsEffect(eff)
                header_row.addWidget(chip)
                self._shallow_chip = chip
            if self._preserved_is_vague:
                chip = self._make_chip("vague_lesson")
                if self._preserved_ignore_shallow:
                    eff = _OpEff(chip); eff.setOpacity(0.4); chip.setGraphicsEffect(eff)
                header_row.addWidget(chip)
                self._vague_chip = chip

        if self._show_ignore_checkbox and self._preset != "3x3":
            self._ignore_check = QCheckBox("Ignore")
            self._ignore_check.setChecked(self._preserved_ignore_shallow)
            self._ignore_check.setStyleSheet(f"color: rgb({tr},{tg},{tb});")
            self._ignore_check.stateChanged.connect(self._schedule_edited)
            self._ignore_check.stateChanged.connect(
                lambda st: self._update_clamp_cct_chip_opacity(bool(st))
            )
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
            from PyQt6.QtWidgets import QGraphicsOpacityEffect
            why_map = {e.get("cat", ""): e.get("why", "") for e in self._entries}
            for key in _3X3_KEYS:
                per_cat = self._preserved_per_cat.get(key, {})
                has_shallow_chip = per_cat.get("is_shallow") and key in ("Why1", "Why2", "Why3")
                has_vague_chip = per_cat.get("is_vague") and key == "Why4"
                is_ignored = per_cat.get("ignore_shallow", False)

                # Question line: label (stretch) + chip right-justified
                q_row = QHBoxLayout()
                prompt_lbl = QLabel(_3X3_PROMPTS[key])
                prompt_lbl.setFont(QFont(self._label_font_family, max(8, self._label_font_size - 1)))
                prompt_lbl.setStyleSheet(f"color: rgb({tr},{tg},{tb}); font-style: italic;")
                prompt_lbl.setWordWrap(True)
                q_row.addWidget(prompt_lbl, 1)
                if has_shallow_chip or has_vague_chip:
                    chip_kind = "shallow" if has_shallow_chip else "vague_lesson"
                    chip = self._make_chip(chip_kind)
                    if is_ignored:
                        eff = QGraphicsOpacityEffect(chip)
                        eff.setOpacity(0.4)
                        chip.setGraphicsEffect(eff)
                    q_row.addWidget(chip, 0, Qt.AlignmentFlag.AlignTop)
                    if has_shallow_chip:
                        self._shallow_chip = chip
                    else:
                        self._vague_chip = chip
                    self._chips_per_cat[key] = chip
                txt_col.addLayout(q_row)

                # Ignore checkbox: right-justified under chip (shown when chip present)
                if has_shallow_chip or has_vague_chip:
                    ign_row = QHBoxLayout()
                    ign_row.addStretch(1)
                    if self._show_ignore_checkbox or is_ignored:
                        ign_cb = QCheckBox("Ignore")
                        ign_cb.setChecked(is_ignored)
                        ign_cb.setStyleSheet(f"color: rgb({tr},{tg},{tb});")
                        ign_cb.stateChanged.connect(self._schedule_edited)
                        ign_cb.stateChanged.connect(
                            lambda st, k=key: self._set_chip_opacity(
                                self._chips_per_cat.get(k), bool(st)
                            )
                        )
                        ign_row.addWidget(ign_cb)
                        self._ignore_checks[key] = ign_cb
                    txt_col.addLayout(ign_row)

                te = QPlainTextEdit(why_map.get(key, ""))
                te.setFont(QFont(self._input_font_family, self._input_font_size))
                self._style_text_widget(te)
                te.setMinimumHeight(self._plain_text_edit_min_height_for_lines(te, self._3x3_min_lines))
                te.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                te.textChanged.connect(self._schedule_edited)
                txt_col.addWidget(te)
                self._why_texts[key] = te
        else:
            why_text = self._entries[0].get("why", "") if self._entries else ""
            te = QPlainTextEdit(why_text)
            te.setFont(QFont(self._input_font_family, self._input_font_size))
            self._style_text_widget(te)
            te.setMinimumHeight(self._plain_text_edit_min_height_for_lines(te, self._why_min_lines))
            te.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            te.textChanged.connect(self._schedule_edited)
            txt_col.addWidget(te)
            self._why_texts["why"] = te
        cols.addLayout(txt_col, 1)

    @staticmethod
    def _plain_text_edit_min_height_for_lines(te: QPlainTextEdit, lines: int) -> int:
        te.ensurePolished()
        fm = te.fontMetrics()
        doc_margin = int(te.document().documentMargin())
        frame = te.frameWidth()
        return fm.lineSpacing() * lines + doc_margin * 2 + frame * 2 + fm.descent() + 2

    def _schedule_edited(self) -> None:
        """Restart the 300ms debounce timer on any input change."""
        self._edit_debounce.start()

    @staticmethod
    def _set_chip_opacity(chip: Optional[QLabel], dim: bool) -> None:
        """Dim (opacity 0.4) or fully restore a chip widget in real time."""
        if chip is None:
            return
        from PyQt6.QtWidgets import QGraphicsOpacityEffect
        if dim:
            eff = QGraphicsOpacityEffect(chip)
            eff.setOpacity(0.4)
            chip.setGraphicsEffect(eff)
        else:
            chip.setGraphicsEffect(None)

    def _update_clamp_cct_chip_opacity(self, dim: bool) -> None:
        for chip in filter(None, [self._shallow_chip, self._vague_chip]):
            self._set_chip_opacity(chip, dim)

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
            why_text = (d.get("why") or "").strip()
            if ignore:
                d["ignore_shallow"] = True
                if why_text:
                    d["ignore_text_hash"] = hashlib.sha256(why_text.encode("utf-8")).hexdigest()
            if self._preserved_is_shallow:
                d["is_shallow"] = True
            if self._preserved_is_vague:
                d["is_vague"] = True
            return d

        if self._preset == "3x3":
            result = []
            for key in _3X3_KEYS:
                text = self._why_texts.get(key, QPlainTextEdit()).toPlainText().strip()
                if not text:
                    continue
                per_cat = self._preserved_per_cat.get(key, {})
                per_cat_ignore_cb = self._ignore_checks.get(key)
                entry: Dict[str, Any] = {"preset": "3x3", "cat": key, "why": text}
                if per_cat_ignore_cb is not None:
                    # User-controlled Ignore checkbox for this answer
                    current_ignore = per_cat_ignore_cb.isChecked()
                    was_ignored = per_cat.get("ignore_shallow", False)
                    if current_ignore:
                        entry["ignore_shallow"] = True
                        entry["ignore_text_hash"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
                        if per_cat.get("is_shallow") and key in ("Why1", "Why2", "Why3"):
                            entry["is_shallow"] = True
                        if per_cat.get("is_vague") and key == "Why4":
                            entry["is_vague"] = True
                    elif was_ignored:
                        # unticked → clear only ignore flags; preserve is_shallow and is_vague
                        if per_cat.get("is_shallow") and key in ("Why1", "Why2", "Why3"):
                            entry["is_shallow"] = True
                        if per_cat.get("is_vague") and key == "Why4":
                            entry["is_vague"] = True
                    else:
                        if per_cat.get("is_shallow") and key in ("Why1", "Why2", "Why3"):
                            entry["is_shallow"] = True
                        if per_cat.get("is_vague") and key == "Why4":
                            entry["is_vague"] = True
                else:
                    # No checkbox for this answer → preserve original flags
                    if per_cat.get("ignore_shallow"):
                        entry["ignore_shallow"] = True
                        if per_cat.get("ignore_text_hash"):
                            entry["ignore_text_hash"] = per_cat["ignore_text_hash"]
                    if per_cat.get("is_shallow") and key in ("Why1", "Why2", "Why3"):
                        entry["is_shallow"] = True
                    if per_cat.get("is_vague") and key == "Why4":
                        entry["is_vague"] = True
                entry = ChessLogStorageService.clear_verdict_if_text_changed(
                    entry, per_cat.get("original_why", "")
                )
                result.append(entry)
            return result

        why = self._why_texts.get("why", QPlainTextEdit()).toPlainText().strip()
        selected = [cat for cat, cb in self._checkboxes.items() if cb.isChecked()]

        def _build(cat: str) -> Dict[str, Any]:
            return ChessLogStorageService.clear_verdict_if_text_changed(
                _annotate({"preset": self._preset, "cat": cat, "why": why}),
                self._original_why_clamp_cct,
            )

        if not selected:
            # Mirror MomentDialog.get_entries(): zero boxes + why → cat="" entry;
            # zero boxes + empty why → [] (intentional delete gesture).
            return [_build("")] if why else []
        return [_build(cat) for cat in selected]

    def snapshot(self):
        """Return current widget state as a TagRowSnapshot for PDF export."""
        shallow_cats: frozenset = frozenset()
        vague_cats: frozenset = frozenset()
        if self._preset == "3x3":
            shallow_cats = frozenset(
                cat for cat, data in self._preserved_per_cat.items()
                if data.get("is_shallow") and cat in ("Why1", "Why2", "Why3")
            )
            vague_cats = frozenset(
                cat for cat, data in self._preserved_per_cat.items()
                if data.get("is_vague") and cat == "Why4"
            )
        return TagRowSnapshot(
            move_label=self._header_label.text() if self._header_label else "",
            preset=self._preset,
            entries=self.get_current_entries(),
            fen=self._fen,
            played_move=self._played_move,
            best_move=self._best_move,
            show_ignore=self._show_ignore_checkbox,
            is_flipped=self._is_flipped,
            is_shallow=self._preserved_is_shallow,
            is_vague=self._preserved_is_vague,
            shallow_cats=shallow_cats,
            vague_cats=vague_cats,
        )


class ShowTagsDialog(QDialog):
    """Scrollable, editable list of Chess Log tags.

    Accepts a list of GameData objects — pass a single-element list for the
    single-game (Show Tags) use case.  Multi-game usage inserts a game-header
    label between each game's rows.

    Save persists all changes: calls ``controller.replace_entries_at_path_for_game``
    for each changed row then ``controller.save_games(affected_games)`` to write
    game.pgn and mark each affected database unsaved.  Cancel and the window
    close button discard all edits.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        games: List,
        controller,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self._controller = controller
        self._games = list(games)

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
            "Show Logged Moments for All Games" if len(self._games) > 1 else "Logged Moments"
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
        st = self.config.get("ui", {}).get("dialogs", {}).get("show_tags", {})
        self._btn_save_label = st.get("button_save", "Save")
        self._btn_cancel_label = st.get("button_cancel", "Cancel")

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

            last_game = None
            row_count = 0
            orphan_count = 0

            for i, (path_key, preset, entries) in enumerate(self._rows_data):
                game = self._row_games[i]
                pgn_game = self._row_pgn_games[i]

                fen, played_move, move_label, mover_is_black = _node_info_fn(pgn_game, path_key)
                if move_label == path_key:
                    # Orphan: path does not resolve in this game's move tree (e.g.
                    # the game's moves were edited after the moment was tagged).
                    # Never display the raw dotted-integer path_key as a label.
                    orphan_count += 1
                    continue

                if game is not last_game:
                    self._rows_layout.addWidget(self._make_game_header(game))
                    last_game = game
                elif row_count > 0:
                    self._rows_layout.addWidget(self._make_separator())

                best_move = resolve_best_move_for_path(game, path_key, played_move, pgn_game)
                row_is_shallow = any(e.get("is_shallow") or e.get("is_vague") for e in entries)
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
                    is_flipped=mover_is_black,
                )
                self._rows_layout.addWidget(row_widget)
                self._row_widgets.append(row_widget)
                row_count += 1

            if orphan_count > 0:
                s = "s" if orphan_count != 1 else ""
                notice = QLabel(
                    f"Note: {orphan_count} tagged moment{s} could not be located "
                    f"— the game’s moves may have been edited after tagging."
                )
                tr, tg, tb = self._text_color_rgb
                notice.setStyleSheet(
                    f"color: rgb({tr},{tg},{tb}); padding: 4px 0px;"
                )
                notice.setWordWrap(True)
                self._rows_layout.addWidget(notice)

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

        # Button bar: [Export to PDF]  stretch  Cancel | Save
        btn_row = QHBoxLayout()

        self._export_pdf_btn = QPushButton("Export to PDF")
        self._export_pdf_btn.setAutoDefault(False)
        self._export_pdf_btn.setFixedHeight(self._button_height)
        self._export_pdf_btn.setEnabled(bool(self._rows_data))
        self._export_pdf_btn.clicked.connect(self._on_export_pdf)
        btn_row.addWidget(self._export_pdf_btn)

        btn_row.addStretch(1)

        self._cancel_btn = QPushButton(self._btn_cancel_label)
        self._cancel_btn.setAutoDefault(False)
        self._cancel_btn.setFixedSize(self._button_width, self._button_height)
        self._cancel_btn.clicked.connect(self.reject)

        self._save_btn = QPushButton(self._btn_save_label)
        self._save_btn.setDefault(True)
        self._save_btn.setAutoDefault(True)
        self._save_btn.setFixedSize(self._button_width, self._button_height)
        self._save_btn.clicked.connect(self._on_save)

        btn_row.addWidget(self._cancel_btn)
        btn_row.addSpacing(6)
        btn_row.addWidget(self._save_btn)
        root.addLayout(btn_row)

        StyleManager.style_buttons(
            [self._export_pdf_btn, self._cancel_btn, self._save_btn],
            self.config,
            self._bg_rgb,
            self._border_rgb,
        )

        self.setMinimumWidth(800)
        from app.views.widgets.themed_dialog_size_grip import install_themed_dialog_resize_grip
        install_themed_dialog_resize_grip(self, self.config)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_save(self) -> None:
        affected_games = set()
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
                affected_games.add(game)
        if affected_games:
            self._controller.save_games(affected_games)
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

        for i, row_widget in enumerate(self._row_widgets):
            game = self._row_games[i]
            if game is not current_game:
                if current_rows:
                    tag_groups.append({"header": current_header, "rows": current_rows})
                current_game = game
                current_rows = []
                white = str(getattr(game, "white", "") or "").strip() or "Unknown"
                black = str(getattr(game, "black", "") or "").strip() or "Unknown"
                result = str(getattr(game, "result", "") or "").strip() or "*"
                date = str(getattr(game, "date", "") or "").strip() or "????.??.??"
                moves = getattr(game, "moves", 0) or 0
                current_header = f"{white} - {black} {result} ({date} - {moves} moves)"
            current_rows.append(row_widget.snapshot())

        if current_rows:
            tag_groups.append({"header": current_header, "rows": current_rows})

        ChessLogPDFService(self.config).export_tags(Path(path), tag_groups)
