"""Category-frequency-over-time chart widget for Chess Log Charts tab.

Draws a multi-line chart where each line is one category from a single preset.
X-axis: time (bin.time_pct, 0-100) derived from game dates.
Y-axis: integer moment count.

Deliberately simpler than MoveQualityOverTimeChartWidget for this first pass:
no hover cache, no gap compression, no smooth bezier, no calendar tick modes.
Those can be added later once we have real usage data.

Data entry point: set_series(series, colors)
  series: ChessLogPresetSeries from chess_log_stats_service
  colors: Dict[str, QColor] mapping category → color; falls back to palette
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from app.services.chess_log_stats_service import ChessLogCategoryBin, ChessLogPresetSeries
from app.utils.font_utils import resolve_font_family, scale_font_size

# Built-in rotating palette used when no config color is supplied.
_FALLBACK_PALETTE: List[Tuple[int, int, int]] = [
    (100, 180, 255),   # blue
    (100, 220, 140),   # green
    (255, 180, 70),    # amber
    (220, 110, 110),   # rose
    (180, 130, 220),   # lavender
    (80,  200, 210),   # teal
    (255, 140, 60),    # orange
    (200, 200, 100),   # yellow-green
]
# Uncategorized always gets this neutral grey so it visually separates from named cats.
_UNCATEGORIZED_COLOR: Tuple[int, int, int] = (130, 130, 140)

# Default inline config used when no config dict is supplied.
_DEFAULTS: Dict[str, Any] = {
    "height": 220,
    "background_color": [28, 28, 33],
    "grid_color": [55, 55, 62],
    "axis_color": [140, 140, 150],
    "text_color": [200, 200, 210],
    "title_color": [210, 210, 220],
    "line_width": 2,
    "legend_width": 120,
    "padding": [40, 16, 28, 48],  # top, right, bottom, left
    "font_family": "Helvetica Neue",
    "font_size": 9,
}


class ChessLogCategoryChartWidget(QWidget):
    """Line chart: one line per Chess Log category within a single preset."""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        cfg = self._resolve_cfg(config or {})

        self._height = int(cfg.get("height", _DEFAULTS["height"]))
        self._bg = QColor(*cfg.get("background_color", _DEFAULTS["background_color"]))
        self._grid_color = QColor(*cfg.get("grid_color", _DEFAULTS["grid_color"]))
        self._axis_color = QColor(*cfg.get("axis_color", _DEFAULTS["axis_color"]))
        self._text_color = QColor(*cfg.get("text_color", _DEFAULTS["text_color"]))
        self._title_color = QColor(*cfg.get("title_color", _DEFAULTS["title_color"]))
        self._line_width = int(cfg.get("line_width", _DEFAULTS["line_width"]))
        self._legend_width = int(cfg.get("legend_width", _DEFAULTS["legend_width"]))
        self._padding = cfg.get("padding", _DEFAULTS["padding"])  # [top, right, bottom, left]
        font_family = resolve_font_family(cfg.get("font_family", _DEFAULTS["font_family"]))
        self._font_size = int(scale_font_size(cfg.get("font_size", _DEFAULTS["font_size"])))
        self._font = QFont(font_family, self._font_size)

        self._series: Optional[ChessLogPresetSeries] = None
        self._colors: Dict[str, QColor] = {}

        self.setFixedHeight(self._height)
        self.setMinimumWidth(200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    @staticmethod
    def _resolve_cfg(top_config: Dict[str, Any]) -> Dict[str, Any]:
        return (
            top_config
            .get("ui", {})
            .get("panels", {})
            .get("detail", {})
            .get("chess_log_charts", {})
            .get("chart", {})
        ) or {}

    def set_series(
        self,
        series: ChessLogPresetSeries,
        colors: Optional[Dict[str, QColor]] = None,
    ) -> None:
        """Load a new preset series and repaint."""
        self._series = series
        self._colors = colors or {}
        self.update()

    def clear(self) -> None:
        self._series = None
        self._colors = {}
        self.update()

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self._bg)

        if not self._series or not self._series.bins:
            painter.setPen(self._text_color)
            painter.setFont(self._font)
            painter.drawText(
                QRectF(0, 0, self.width(), self.height()),
                Qt.AlignmentFlag.AlignCenter,
                "No data",
            )
            return

        pad_t, pad_r, pad_b, pad_l = self._padding
        legend_w = self._legend_width
        plot_x0 = pad_l
        plot_x1 = self.width() - pad_r - legend_w
        plot_y0 = pad_t
        plot_y1 = self.height() - pad_b
        plot_w = max(1, plot_x1 - plot_x0)
        plot_h = max(1, plot_y1 - plot_y0)

        categories = self._series.categories
        bins = self._series.bins
        totals: Dict[str, int] = {
            cat: sum(b.counts.get(cat, 0) for b in bins) for cat in categories
        }
        y_max = self._compute_y_max(categories, bins)

        self._draw_grid(painter, plot_x0, plot_y0, plot_x1, plot_y1, plot_w, plot_h, y_max)
        self._draw_axes(painter, plot_x0, plot_y0, plot_x1, plot_y1)
        self._draw_x_labels(painter, bins, plot_x0, plot_y1, plot_w)
        self._draw_y_labels(painter, plot_x0, plot_y0, plot_y1, plot_h, y_max)
        self._draw_title(painter, plot_x0, plot_x1)
        self._draw_lines(painter, categories, bins, plot_x0, plot_y0, plot_w, plot_h, y_max, totals)
        self._draw_legend(painter, categories, plot_x1 + 8, plot_y0, legend_w - 8, totals)

    @staticmethod
    def _compute_y_max(categories: List[str], bins: List) -> int:
        """Return the largest single-bin count across all (category, bin) pairs."""
        raw = max(
            (b.counts.get(cat, 0) for b in bins for cat in categories),
            default=1,
        )
        return max(1, raw)

    def _draw_grid(self, p, x0, y0, x1, y1, pw, ph, y_max) -> None:
        grid_pen = QPen(self._grid_color)
        grid_pen.setWidth(1)
        p.setPen(grid_pen)
        n_lines = max(2, min(6, y_max))
        for i in range(n_lines + 1):
            y = y1 - (i / n_lines) * ph
            p.drawLine(int(x0), int(y), int(x1), int(y))

    def _draw_axes(self, p, x0, y0, x1, y1) -> None:
        ax_pen = QPen(self._axis_color)
        ax_pen.setWidth(1)
        p.setPen(ax_pen)
        p.drawLine(int(x0), int(y0), int(x0), int(y1))  # Y axis
        p.drawLine(int(x0), int(y1), int(x1), int(y1))  # X axis

    def _draw_x_labels(self, p, bins, x0, y_base, pw) -> None:
        p.setPen(self._text_color)
        p.setFont(self._font)
        fm = QFontMetrics(self._font)
        prev_right = -999
        for b in bins:
            label = b.lab0[:7] if b.lab0 else ""  # "YYYY-MM"
            x = x0 + (b.time_pct / 100.0) * pw
            tw = fm.horizontalAdvance(label)
            lx = x - tw / 2
            if lx > prev_right + 4:
                p.drawText(int(lx), int(y_base + self._font_size + 2), label)
                prev_right = lx + tw

    def _draw_y_labels(self, p, x0, y0, y1, ph, y_max) -> None:
        p.setPen(self._text_color)
        p.setFont(self._font)
        fm = QFontMetrics(self._font)
        n_lines = max(2, min(6, y_max))
        for i in range(n_lines + 1):
            val = round(y_max * i / n_lines)
            label = str(val)
            tw = fm.horizontalAdvance(label)
            y = y1 - (i / n_lines) * ph
            p.drawText(int(x0 - tw - 4), int(y + self._font_size / 2), label)

    def _draw_title(self, p, x0, x1) -> None:
        if not self._series:
            return
        p.setPen(self._title_color)
        font = QFont(self._font)
        font.setBold(True)
        p.setFont(font)
        title = self._series.preset
        p.drawText(
            QRectF(x0, 4, x1 - x0, self._padding[0] - 4),
            Qt.AlignmentFlag.AlignCenter,
            title,
        )
        p.setFont(self._font)

    def _draw_lines(self, p, categories, bins, x0, y0, pw, ph, y_max, totals: Dict[str, int]) -> None:
        for idx, cat in enumerate(categories):
            if totals.get(cat, 0) == 0:
                continue
            color = self._cat_color(cat, idx)
            pen = QPen(color)
            pen.setWidth(self._line_width)
            p.setPen(pen)

            points = []
            for b in bins:
                x = x0 + (b.time_pct / 100.0) * pw
                count = b.counts.get(cat, 0)
                y = y0 + ph * (1.0 - count / y_max)
                points.append((x, y))

            for i in range(1, len(points)):
                x1a, y1a = points[i - 1]
                x2a, y2a = points[i]
                p.drawLine(int(x1a), int(y1a), int(x2a), int(y2a))

            # Dot at each bin
            for x, y in points:
                p.setBrush(color)
                p.drawEllipse(QRectF(x - 3, y - 3, 6, 6))

    def _draw_legend(self, p, categories, lx, ly, lw, totals: Dict[str, int]) -> None:
        p.setFont(self._font)
        fm = QFontMetrics(self._font)
        row_h = self._font_size + 6
        for idx, cat in enumerate(categories):
            has_data = totals.get(cat, 0) > 0
            color = self._cat_color(cat, idx)
            y = ly + idx * row_h
            swatch_color = QColor(color)
            if not has_data:
                swatch_color.setAlphaF(0.4)
            p.setBrush(swatch_color)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRect(int(lx), int(y + 2), 10, self._font_size)
            p.setPen(self._axis_color if not has_data else self._text_color)
            if not cat:
                label = "(uncategorized)" if has_data else "(uncategorized) (no data)"
            else:
                label = cat if has_data else f"{cat} (no data)"
            p.drawText(int(lx + 14), int(y + self._font_size), label[:24])

    def _cat_color(self, cat: str, idx: int) -> QColor:
        if cat in self._colors:
            return self._colors[cat]
        if not cat:
            return QColor(*_UNCATEGORIZED_COLOR)
        rgb = _FALLBACK_PALETTE[idx % len(_FALLBACK_PALETTE)]
        return QColor(*rgb)
