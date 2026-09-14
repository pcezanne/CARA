"""PDF export service for Chess Log — tags dialogs and the Charts page."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import chess

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFontMetrics,
    QImage,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
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
        """Write tag rows from a Show-Tags dialog to a PDF."""
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
                if header_text:
                    first_row_h = self._measure_tag_row_height(painter, content, rows[0])
                    y = self._section_heading(
                        painter, writer, content, y, header_text,
                        keep_with=first_row_h + self._ROW_GAP,
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
                y = self._draw_narrative_paginated(painter, writer, content, y, narrative)
                y += self._ROW_GAP

            if shallow_rows:
                first_row_h = self._measure_tag_row_height(painter, content, shallow_rows[0])
                y = self._section_heading(
                    painter, writer, content, y, "Shallow Notes",
                    keep_with=first_row_h + self._ROW_GAP,
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

    def _measure_tag_row_height(
        self,
        painter: QPainter,
        content: QRectF,
        row: TagRowSnapshot,
    ) -> float:
        """Compute the total card height (including padding) needed for this row."""
        pad = self._ROW_PAD
        board_sz = self._BOARD_DISPLAY_PT
        gap = 8.0
        w_inner = content.width() - pad * 2
        remaining = w_inner - board_sz - gap
        col2_w = remaining * 0.38
        col3_w = remaining - col2_w - gap
        flags = int(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap
        )

        painter.setFont(self._font_body_bold)
        fm_bold = QFontMetrics(self._font_body_bold)
        fm_body = QFontMetrics(self._font_body)
        bold_line_h = float(fm_bold.height())
        body_line_h = float(fm_body.height())

        # Header height — move label (bold), plus room for triangle if shown
        header_br = painter.boundingRect(QRectF(0, 0, w_inner, 1000), flags, row.move_label)
        header_h = float(header_br.height())
        if row.show_ignore:
            header_h = max(header_h, bold_line_h)

        # Body content height
        if row.preset == "3x3":
            why_map = {e.get("cat", ""): e.get("why", "") for e in row.entries}
            full_w = col2_w + gap + col3_w
            body_h = 0.0
            for key in ("Why1", "Why2", "Why3"):
                prompt = _3X3_PROMPTS.get(key, key)
                painter.setFont(self._font_body_bold)
                br = painter.boundingRect(QRectF(0, 0, full_w, 1000), flags, prompt)
                body_h += float(br.height())
                answer = why_map.get(key, "").strip()
                if answer:
                    painter.setFont(self._font_body)
                    br2 = painter.boundingRect(QRectF(0, 0, full_w, 1000), flags, answer)
                    body_h += float(br2.height())
                body_h += 3.0
        else:
            from app.utils.chess_log_preset_order import CLAMP_ORDER, CCT_ORDER
            if row.preset == "CLAMP":
                cats = list(CLAMP_ORDER)
            elif row.preset == "CCT":
                cats = list(CCT_ORDER)
            else:
                cats = sorted({e.get("cat", "") for e in row.entries if e.get("cat")})
            check_h = len(cats) * body_line_h if cats else 0.0
            why = next((e.get("why", "").strip() for e in row.entries if e.get("why")), "")
            why_h = 0.0
            if why:
                painter.setFont(self._font_body)
                br = painter.boundingRect(QRectF(0, 0, col3_w, 1000), flags, why)
                why_h = float(br.height())
            body_h = max(check_h, why_h)

        body_h = max(body_h, board_sz)
        return pad * 2 + header_h + 4.0 + body_h

    def _draw_tag_row(
        self,
        painter: QPainter,
        writer,
        content: QRectF,
        y: float,
        row: TagRowSnapshot,
    ) -> float:
        """Draw one tag row atomically. Returns y after the row."""
        pad = self._ROW_PAD
        board_sz = self._BOARD_DISPLAY_PT
        gap = 8.0
        x = content.left()
        w = content.width()
        x_inner = x + pad
        w_inner = w - pad * 2
        remaining = w_inner - board_sz - gap
        col2_w = remaining * 0.38
        col3_w = remaining - col2_w - gap
        col2_x = x_inner + board_sz + gap
        col3_x = col2_x + col2_w + gap
        flags = int(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap
        )

        # ---- Phase 1: Measure (before page-break check) ----
        painter.setFont(self._font_body_bold)
        fm_bold = QFontMetrics(self._font_body_bold)
        fm_body = QFontMetrics(self._font_body)
        bold_line_h = float(fm_bold.height())
        body_line_h = float(fm_body.height())

        header_br = painter.boundingRect(QRectF(0, 0, w_inner, 1000), flags, row.move_label)
        header_h = float(header_br.height())
        tri_size = 0.0
        if row.show_ignore:
            tri_size = bold_line_h
            header_h = max(header_h, tri_size)

        if row.preset == "3x3":
            cats: List[str] = []
            why = ""
            why_h = 0.0
            why_map_3x3 = {e.get("cat", ""): e.get("why", "") for e in row.entries}
            full_w = col2_w + gap + col3_w
            body_h = 0.0
            for key in ("Why1", "Why2", "Why3"):
                prompt = _3X3_PROMPTS.get(key, key)
                painter.setFont(self._font_body_bold)
                br = painter.boundingRect(QRectF(0, 0, full_w, 1000), flags, prompt)
                body_h += float(br.height())
                answer = why_map_3x3.get(key, "").strip()
                if answer:
                    painter.setFont(self._font_body)
                    br2 = painter.boundingRect(QRectF(0, 0, full_w, 1000), flags, answer)
                    body_h += float(br2.height())
                body_h += 3.0
        else:
            why_map_3x3 = {}
            full_w = 0.0
            from app.utils.chess_log_preset_order import CLAMP_ORDER, CCT_ORDER
            if row.preset == "CLAMP":
                cats = list(CLAMP_ORDER)
            elif row.preset == "CCT":
                cats = list(CCT_ORDER)
            else:
                cats = sorted({e.get("cat", "") for e in row.entries if e.get("cat")})
            check_h = len(cats) * body_line_h if cats else 0.0
            why = next((e.get("why", "").strip() for e in row.entries if e.get("why")), "")
            why_h = 0.0
            if why:
                painter.setFont(self._font_body)
                br = painter.boundingRect(QRectF(0, 0, col3_w, 1000), flags, why)
                why_h = float(br.height())
            body_h = max(check_h, why_h)

        body_h = max(body_h, board_sz)
        card_h = pad * 2 + header_h + 4.0 + body_h

        # ---- Page-break check ----
        y, _ = self._ensure_space(painter, writer, content, y, card_h + self._ROW_GAP)

        # ---- Phase 2: Draw ----
        painter.save()
        painter.setBrush(self._card)
        painter.setPen(QPen(self._rule, 0.5))
        painter.drawRoundedRect(QRectF(x, y, w, card_h), 4, 4)
        painter.restore()

        y_inner = y + pad

        # Header: move label
        painter.setFont(self._font_body_bold)
        painter.setPen(self._text)
        painter.drawText(QRectF(x_inner, y_inner, w_inner, header_h + 2), flags, row.move_label)

        # Header: warning triangle + Ignore text (right-aligned)
        if row.show_ignore:
            is_ignored = any(e.get("ignore_shallow") for e in row.entries)
            ignore_text = f"Ignore: {'Yes' if is_ignored else 'No'}"
            text_w = float(fm_bold.horizontalAdvance(ignore_text))
            tri_x = x_inner + w_inner - text_w - 4.0 - tri_size
            self._draw_warning_triangle(painter, tri_x, y_inner, tri_size)
            painter.setFont(self._font_body_bold)
            painter.setPen(self._text)
            painter.drawText(
                QRectF(tri_x + tri_size + 4.0, y_inner, text_w + 4.0, bold_line_h + 2),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
                ignore_text,
            )

        y_inner += header_h + 4.0

        # Board miniature
        board_px = self._render_board(row.fen, row.played_move)
        if board_px and not board_px.isNull():
            target = QRectF(x_inner, y_inner, board_sz, board_sz)
            painter.drawPixmap(
                target, board_px, QRectF(0, 0, board_px.width(), board_px.height())
            )

        # Body content: 3x3 prompts/answers OR checkboxes + why-text
        if row.preset == "3x3":
            y_col = y_inner
            for key in ("Why1", "Why2", "Why3"):
                prompt = _3X3_PROMPTS.get(key, key)
                painter.setFont(self._font_body_bold)
                painter.setPen(self._muted)
                br = painter.boundingRect(QRectF(col2_x, 0, full_w, 1000), flags, prompt)
                painter.drawText(
                    QRectF(col2_x, y_col, full_w, float(br.height()) + 2), flags, prompt
                )
                y_col += float(br.height())
                answer = why_map_3x3.get(key, "").strip()
                if answer:
                    painter.setFont(self._font_body)
                    painter.setPen(self._text)
                    br2 = painter.boundingRect(QRectF(col2_x, 0, full_w, 1000), flags, answer)
                    painter.drawText(
                        QRectF(col2_x, y_col, full_w, float(br2.height()) + 2), flags, answer
                    )
                    y_col += float(br2.height())
                y_col += 3.0
        else:
            selected = {e.get("cat", "") for e in row.entries}
            y_col = y_inner
            painter.setFont(self._font_body)
            painter.setPen(self._text)
            for cat in cats:
                mark = "☑" if cat in selected else "☐"
                painter.drawText(
                    QRectF(col2_x, y_col, col2_w, body_line_h + 2),
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
                    f"{mark} {cat}",
                )
                y_col += body_line_h
            if why:
                painter.setFont(self._font_body)
                painter.setPen(self._muted)
                painter.drawText(
                    QRectF(col3_x, y_inner, col3_w, why_h + 4), flags, why
                )

        return y + card_h + self._ROW_GAP

    def _draw_warning_triangle(
        self, painter: QPainter, x: float, y: float, size: float
    ) -> None:
        """Draw a filled yellow warning triangle with a black exclamation mark."""
        painter.save()
        yellow = QColor(241, 196, 15)
        outline = QColor(30, 30, 30)
        poly = QPolygonF([
            QPointF(x + size / 2, y),
            QPointF(x, y + size),
            QPointF(x + size, y + size),
        ])
        painter.setBrush(yellow)
        painter.setPen(QPen(outline, 1.0))
        painter.drawPolygon(poly)
        # Exclamation mark: vertical bar + dot
        painter.setPen(QPen(outline, 1.5))
        cx = x + size / 2
        painter.drawLine(
            QPointF(cx, y + size * 0.30),
            QPointF(cx, y + size * 0.62),
        )
        painter.setBrush(outline)
        painter.setPen(QPen(outline, 0.5))
        painter.drawEllipse(QPointF(cx, y + size * 0.78), size * 0.055, size * 0.055)
        painter.restore()

    def _draw_narrative_paginated(
        self,
        painter: QPainter,
        writer,
        content: QRectF,
        y: float,
        text: str,
    ) -> float:
        """Draw narrative text with automatic page breaks before the footer."""
        painter.setFont(self._font_body)
        painter.setPen(self._text)
        fm = QFontMetrics(self._font_body)
        line_h = float(fm.height())
        cx = content.left()
        cw = content.width()
        flags_wrap = int(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap
        )
        flags_draw = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        for para in text.split("\n"):
            stripped = para.strip()
            if not stripped:
                y += line_h * 0.5
                continue

            # Markdown heading: render as a styled section heading
            if stripped.startswith("#"):
                heading_text = stripped.lstrip("#").strip()
                if heading_text:
                    y = self._section_heading(
                        painter, writer, content, y, heading_text, keep_with=line_h * 2
                    )
                    painter.setFont(self._font_body)
                    painter.setPen(self._text)
                continue

            # Body text: word-wrap line by line with page-break checks
            words = stripped.split()
            cur = ""
            for word in words:
                candidate = (cur + " " + word).strip() if cur else word
                if cur:
                    br = painter.boundingRect(
                        QRectF(cx, 0, cw, 2000), flags_wrap, candidate
                    )
                    wraps = float(br.height()) > line_h * 1.3
                else:
                    wraps = False
                if wraps:
                    y, _ = self._ensure_space(painter, writer, content, y, line_h)
                    painter.setFont(self._font_body)
                    painter.setPen(self._text)
                    painter.drawText(QRectF(cx, y, cw, line_h + 2), flags_draw, cur)
                    y += line_h
                    cur = word
                else:
                    cur = candidate
            if cur:
                y, _ = self._ensure_space(painter, writer, content, y, line_h)
                painter.setFont(self._font_body)
                painter.setPen(self._text)
                painter.drawText(QRectF(cx, y, cw, line_h + 2), flags_draw, cur)
                y += line_h
            y += line_h * 0.3  # paragraph gap

        return y

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
