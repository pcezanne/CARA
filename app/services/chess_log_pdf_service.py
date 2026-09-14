"""PDF export service for Chess Log — tags dialogs and the Charts page."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import chess

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFontMetrics,
    QImage,
    QPainter,
    QPen,
    QPixmap,
)

from app.services.pdf_report_base import BasePDFReportService


@dataclass
class TagRowSnapshot:
    """Immutable snapshot of one _TagRowWidget's current state for PDF export."""

    move_label: str
    preset: str
    entries: List[Dict[str, Any]]
    fen: Optional[str]
    played_move: Optional[chess.Move]
    show_ignore: bool


_3X3_PROMPTS: Dict[str, str] = {
    "Why1": "Why did I make this move?",
    "Why2": "Why was it suboptimal?",
    "Why3": "Why is the engine's suggestion better?",
}

_ROW_HEIGHT: Dict[str, float] = {
    "CLAMP": 175.0,
    "CCT": 175.0,
    "Custom": 175.0,
    "3x3": 290.0,
}
_ROW_HEIGHT_DEFAULT = 175.0


def default_chess_log_tags_pdf_filename(*, is_shallow_only: bool = False) -> str:
    ts = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    kind = "ShallowTags" if is_shallow_only else "AllGames"
    return f"CARA-ChessLog-{kind}-{ts}.pdf"


def default_chess_log_charts_pdf_filename(player_name: str = "") -> str:
    ts = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in player_name)[:40]
    return f"CARA-ChessLogCharts-{safe}-{ts}.pdf" if safe else f"CARA-ChessLogCharts-{ts}.pdf"


class ChessLogPDFService(BasePDFReportService):
    """PDF report for Chess Log tags (dialogs) and the Charts page."""

    _BOARD_RENDER_SCALE = 4
    _BOARD_DISPLAY_PT = 100.0
    _ROW_PAD = 8.0
    _ROW_GAP = 6.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def export_tags(
        self,
        path: Path,
        tag_groups: List[Dict[str, Any]],
        *,
        is_shallow_only: bool = False,
    ) -> bool:
        """Write tag rows from a Show-Tags dialog to a PDF.

        tag_groups is a list of {"header": Optional[str], "rows": List[TagRowSnapshot]}.
        header is the per-game header text (None for single-game exports).
        """
        painter = None
        try:
            writer = self._create_pdf_writer(path)
            painter = QPainter(writer)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            content = self._content_rect(writer)
            self._page_number = 1
            self._draw_page_chrome(painter, content)
            title = "Chess Log — Shallow Notes" if is_shallow_only else "Chess Log — Tagged Moments"
            y = self._draw_report_header(painter, content, title)

            for group in tag_groups:
                header_text = group.get("header")
                rows: List[TagRowSnapshot] = group.get("rows", [])
                if not rows:
                    continue
                first_h = _ROW_HEIGHT.get(rows[0].preset, _ROW_HEIGHT_DEFAULT)
                if header_text:
                    y = self._section_heading(
                        painter, writer, content, y, header_text, keep_with=first_h
                    )
                for row in rows:
                    y = self._draw_tag_row(painter, writer, content, y, row)

            painter.end()
            return True
        except Exception as exc:
            try:
                from app.services.logging_service import LoggingService
                LoggingService.get_instance().error(
                    f"ChessLogPDFService.export_tags error: {exc}", exc_info=exc
                )
            except Exception:
                pass
            if painter is not None:
                try:
                    painter.end()
                except Exception:
                    pass
            return False

    def export_charts_report(
        self,
        path: Path,
        player_name: str,
        source_label: str,
        chart_pixmaps: List[Tuple[str, QPixmap]],
        narrative_text: str,
        shallow_rows: List[TagRowSnapshot],
    ) -> bool:
        """Write Chess Log Charts page (charts + narrative + optional shallow rows) to a PDF."""
        painter = None
        try:
            writer = self._create_pdf_writer(path)
            painter = QPainter(writer)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            content = self._content_rect(writer)
            self._page_number = 1
            self._draw_page_chrome(painter, content)

            display_name = player_name or "Chess Log"
            title = f"Chess Log Charts — {display_name}"
            y = self._draw_report_header(painter, content, title)
            if source_label:
                y = self._draw_text_line(
                    painter, f"Source: {source_label}",
                    content.left(), y, content.width(),
                    self._font_body, self._muted,
                )
                y += 6.0

            for preset, pixmap in chart_pixmaps:
                if pixmap is None or pixmap.isNull():
                    continue
                aspect = pixmap.height() / max(pixmap.width(), 1)
                chart_h = content.width() * aspect
                y, _ = self._ensure_space(painter, writer, content, y, chart_h + 32)
                y = self._section_heading(
                    painter, writer, content, y, f"Chart: {preset}", keep_with=chart_h
                )
                target = QRectF(content.left(), y, content.width(), chart_h)
                painter.drawPixmap(
                    target, pixmap, QRectF(0, 0, pixmap.width(), pixmap.height())
                )
                y += chart_h + self._ROW_GAP

            narrative = (narrative_text or "").strip()
            if narrative:
                y = self._section_heading(
                    painter, writer, content, y, "Narrative Summary", keep_with=40.0
                )
                y = self._draw_text_line(
                    painter, narrative,
                    content.left(), y, content.width(),
                    self._font_body, self._text,
                )
                y += self._ROW_GAP

            if shallow_rows:
                first_h = _ROW_HEIGHT.get(shallow_rows[0].preset, _ROW_HEIGHT_DEFAULT)
                y = self._section_heading(
                    painter, writer, content, y, "Shallow Notes", keep_with=first_h
                )
                for row in shallow_rows:
                    y = self._draw_tag_row(painter, writer, content, y, row)

            painter.end()
            return True
        except Exception as exc:
            try:
                from app.services.logging_service import LoggingService
                LoggingService.get_instance().error(
                    f"ChessLogPDFService.export_charts_report error: {exc}", exc_info=exc
                )
            except Exception:
                pass
            if painter is not None:
                try:
                    painter.end()
                except Exception:
                    pass
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _draw_report_header(self, painter: QPainter, content: QRectF, title: str) -> float:
        logo_sz = self._logo_size
        logo_rect = QRectF(
            content.right() - logo_sz, content.top(), logo_sz, logo_sz
        )
        self._draw_logo(painter, logo_rect)

        title_w = content.width() - logo_sz - 10.0
        y = content.top()
        y = self._draw_text_line(
            painter, "CARA — Chess Log",
            content.left(), y, title_w,
            self._font_body, self._muted,
        )
        y = self._draw_text_line(
            painter, title,
            content.left(), y + 2.0, title_w,
            self._font_title, self._accent,
        )
        y += 6.0
        painter.setPen(QPen(self._rule, 1.5))
        painter.drawLine(int(content.left()), int(y), int(content.right()), int(y))
        return y + 12.0

    def _draw_tag_row(
        self,
        painter: QPainter,
        writer,
        content: QRectF,
        y: float,
        row: TagRowSnapshot,
    ) -> float:
        """Draw one tag row atomically. Returns y after the row."""
        needed = _ROW_HEIGHT.get(row.preset, _ROW_HEIGHT_DEFAULT) + self._ROW_PAD * 2
        y, _ = self._ensure_space(painter, writer, content, y, needed)

        pad = self._ROW_PAD
        x = content.left()
        w = content.width()

        # Card background
        painter.save()
        painter.setBrush(self._card)
        painter.setPen(QPen(self._rule, 0.5))
        row_box_h = _ROW_HEIGHT.get(row.preset, _ROW_HEIGHT_DEFAULT)
        painter.drawRoundedRect(QRectF(x, y, w, row_box_h), 4, 4)
        painter.restore()

        y_inner = y + pad
        x_inner = x + pad
        w_inner = w - pad * 2.0

        # Header line: move label + optional ⚠️ ignore state
        header_text = row.move_label
        if row.show_ignore:
            is_ignored = any(e.get("ignore_shallow") for e in row.entries)
            header_text += f"   ⚠️  Ignore: {'Yes' if is_ignored else 'No'}"
        y_inner = self._draw_text_line(
            painter, header_text, x_inner, y_inner, w_inner,
            self._font_body_bold, self._text,
        )
        y_inner += 4.0

        # Three-column: board | checkboxes | why
        board_sz = self._BOARD_DISPLAY_PT
        gap = 8.0
        col2_x = x_inner + board_sz + gap
        remaining = w_inner - board_sz - gap
        col2_w = remaining * 0.38
        col3_x = col2_x + col2_w + gap
        col3_w = remaining - col2_w - gap

        board_px = self._render_board(row.fen, row.played_move)
        if board_px and not board_px.isNull():
            target = QRectF(x_inner, y_inner, board_sz, board_sz)
            painter.drawPixmap(
                target, board_px, QRectF(0, 0, board_px.width(), board_px.height())
            )

        if row.preset == "3x3":
            why_map = {e.get("cat", ""): e.get("why", "") for e in row.entries}
            y_col = y_inner
            full_w = col2_w + gap + col3_w
            for key in ("Why1", "Why2", "Why3"):
                prompt = _3X3_PROMPTS.get(key, key)
                y_col = self._draw_text_line(
                    painter, prompt, col2_x, y_col, full_w,
                    self._font_body_bold, self._muted,
                )
                answer = why_map.get(key, "").strip()
                if answer:
                    y_col = self._draw_text_line(
                        painter, answer, col2_x, y_col, full_w,
                        self._font_body, self._text,
                    )
                y_col += 3.0
        else:
            from app.utils.chess_log_preset_order import CLAMP_ORDER, CCT_ORDER
            if row.preset == "CLAMP":
                cats = list(CLAMP_ORDER)
            elif row.preset == "CCT":
                cats = list(CCT_ORDER)
            else:
                cats = sorted({e.get("cat", "") for e in row.entries if e.get("cat")})
            selected = {e.get("cat", "") for e in row.entries}
            y_col = y_inner
            for cat in cats:
                mark = "☑" if cat in selected else "☐"
                y_col = self._draw_text_line(
                    painter, f"{mark} {cat}", col2_x, y_col, col2_w,
                    self._font_body, self._text,
                )
            why = next((e.get("why", "").strip() for e in row.entries if e.get("why")), "")
            if why:
                self._draw_text_line(
                    painter, why, col3_x, y_inner, col3_w,
                    self._font_body, self._muted,
                )

        return y + row_box_h + self._ROW_GAP

    def _render_board(
        self, fen: Optional[str], played_move: Optional[chess.Move]
    ) -> Optional[QPixmap]:
        """Rasterize a MiniChessBoardWidget for PDF embedding."""
        try:
            import chess as chess_lib
            from app.views.widgets.mini_chessboard_widget import MiniChessBoardWidget
            size_px = int(self._BOARD_DISPLAY_PT * self._BOARD_RENDER_SCALE)
            widget = MiniChessBoardWidget(
                self.config,
                fen or chess_lib.STARTING_FEN,
                embedded=True,
                size_override=size_px,
            )
            if played_move is not None:
                widget.set_move(played_move, True)
            widget_size = widget.size()
            image = QImage(widget_size, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.white)
            widget.render(image)
            return QPixmap.fromImage(image)
        except Exception:
            return None
