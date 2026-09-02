"""Category-frequency-over-time chart widget for Chess Log Charts tab.

Draws a multi-line chart where each line is one category from a single preset.
X-axis: time (bin.time_pct, 0-100) derived from game dates, or uniform bin index
        depending on the series' x_axis_layout field.
Y-axis: integer moment count.

Data entry point: set_series(series, colors)
  series: ChessLogPresetSeries from chess_log_stats_service
  colors: Dict[str, QColor] mapping category → color; falls back to palette
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
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


# ---------------------------------------------------------------------------
# Calendar axis helpers — ported verbatim from detail_player_stats_view.py.
# Player Stats' file is NOT modified; this is Chess Log's own local copy.
# ---------------------------------------------------------------------------

_AXIS_FALLBACK_DAY_MAX_SPAN_DAYS = 31
_AXIS_FALLBACK_WEEK_MAX_SPAN_DAYS = 120
_AXIS_FALLBACK_MONTH_MAX_SPAN_DAYS = 960

# strftime("%b") follows the process locale; keep chart labels English regardless of OS language.
_EN_MONTH_ABBREV = (
    "",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def _format_axis_tick_month_year(d: date) -> str:
    return f"{_EN_MONTH_ABBREV[d.month]} '{d.year % 100:02d}"


def _format_axis_tick_day_month(d: date) -> str:
    return f"{d.day} {_EN_MONTH_ABBREV[d.month]}"


def _effective_calendar_mode(ordinal_min: int, ordinal_max: int) -> str:
    """Pick day/week/month/year tick density based on the ordinal span."""
    span = max(0, ordinal_max - ordinal_min)
    if span <= _AXIS_FALLBACK_DAY_MAX_SPAN_DAYS:
        return "day"
    if span <= _AXIS_FALLBACK_WEEK_MAX_SPAN_DAYS:
        return "week"
    if span <= _AXIS_FALLBACK_MONTH_MAX_SPAN_DAYS:
        return "month"
    return "year"


def _week_start_monday_ordinal(ord_val: int) -> int:
    d = date.fromordinal(ord_val)
    return (d - timedelta(days=d.weekday())).toordinal()


def _ordinal_to_chart_x(o: int, omin: int, omax: int, left: float, right: float) -> float:
    """Convert a day ordinal to a pixel x-coordinate on a linear calendar axis.

    Both calendar gridlines and data bin centers must use this function so they
    share an identical coordinate system. Ported from Player Stats'
    _accuracy_over_time_ordinal_to_x; layout=None branch only (no GapCompressed).
    """
    span = max(1, omax - omin)
    return left + (o - omin) / span * (right - left)


def _calendar_axis_ticks(
    ordinal_min: int,
    ordinal_max: int,
    mode: str,
    max_labels: int = 8,
) -> List[Tuple[int, bool, str]]:
    """Generate calendar tick positions as (ordinal, is_major, label) tuples.

    Ported verbatim from detail_player_stats_view._calendar_axis_ticks.
    Week-minor ticks in month mode are disabled (Chess Log has no config knob
    for the week-minor threshold; month ticks are sufficient for this data).
    """
    omin, omax = ordinal_min, ordinal_max
    if omax <= omin:
        return []
    max_l = max(4, max_labels)
    ticks: List[Tuple[int, bool, str]] = []
    majors: set = set()

    if mode == "year":
        y0 = date.fromordinal(omin).year
        y1 = date.fromordinal(omax).year
        for y in range(y0, y1 + 1):
            o = date(y, 1, 1).toordinal()
            if omin <= o <= omax:
                ticks.append((o, True, str(y)))
                majors.add(o)
        if (y1 - y0) <= 3:
            cur = date(y0, 1, 1)
            end_d = date(y1, 12, 1)
            while cur <= end_d:
                o = cur.toordinal()
                if omin <= o <= omax and o not in majors:
                    ticks.append((o, False, ""))
                if cur.month == 12:
                    cur = date(cur.year + 1, 1, 1)
                else:
                    cur = date(cur.year, cur.month + 1, 1)

    elif mode == "month":
        d0 = date.fromordinal(omin)
        d1 = date.fromordinal(omax)
        cur = date(d0.year, d0.month, 1)
        end_m = date(d1.year, d1.month, 1)
        while cur <= end_m:
            o = cur.toordinal()
            if omin <= o <= omax:
                ticks.append((o, True, _format_axis_tick_month_year(cur)))
                majors.add(o)
            if cur.month == 12:
                cur = date(cur.year + 1, 1, 1)
            else:
                cur = date(cur.year, cur.month + 1, 1)
        # Week minors disabled for Chess Log (no config knob; month density is adequate).

    elif mode == "week":
        w = _week_start_monday_ordinal(omin)
        while w < omin:
            w += 7
        idx = 0
        label_every = max(1, int(max(1, (omax - omin) // 7) // max_l) + 1)
        while w <= omax:
            lbl = _format_axis_tick_day_month(date.fromordinal(w)) if idx % label_every == 0 else ""
            ticks.append((w, True, lbl))
            idx += 1
            w += 7

    else:  # day
        span_days = omax - omin
        step = max(1, (span_days + max_l - 1) // max_l)
        o = omin
        while o <= omax:
            ticks.append((o, True, _format_axis_tick_day_month(date.fromordinal(o))))
            o += step
        if ticks and ticks[-1][0] < omax:
            ticks.append((omax, True, _format_axis_tick_day_month(date.fromordinal(omax))))

    ticks.sort(key=lambda t: t[0])
    return ticks


def _smooth_polyline_path(run: List[QPointF], *, strength: float = 1.0) -> Optional[QPainterPath]:
    """Cubic Bézier chain (Catmull–Rom style) through ``run`` for a flowing line.

    Vertices are preserved as segment endpoints; the curve may bulge slightly past
    straight chords at sharp turns. ``strength`` scales handle tension:
    0 ≈ straight segments, ~1 default, >1 more wavy.

    Ported from detail_player_stats_view._smooth_polyline_path.
    """
    n = len(run)
    if n < 2:
        return None
    path = QPainterPath(run[0])
    if n == 2:
        path.lineTo(run[1])
        return path
    if strength < 0.05:
        for k in range(n - 1):
            path.lineTo(run[k + 1])
        return path
    k = strength / 6.0

    def _pt(i: int) -> QPointF:
        return run[max(0, min(n - 1, i))]

    for i in range(n - 1):
        p_im1 = _pt(i - 1) if i > 0 else QPointF(2 * run[0].x() - run[1].x(), 2 * run[0].y() - run[1].y())
        p_i = run[i]
        p_ip1 = run[i + 1]
        p_ip2 = (
            run[i + 2]
            if i + 2 < n
            else QPointF(2 * run[n - 1].x() - run[n - 2].x(), 2 * run[n - 1].y() - run[n - 2].y())
        )
        c1 = QPointF(
            p_i.x() + (p_ip1.x() - p_im1.x()) * k,
            p_i.y() + (p_ip1.y() - p_im1.y()) * k,
        )
        c2 = QPointF(
            p_ip1.x() - (p_ip2.x() - p_i.x()) * k,
            p_ip1.y() - (p_ip2.y() - p_i.y()) * k,
        )
        path.cubicTo(c1, c2, p_ip1)
    return path


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
        n = len(bins)
        for i, b in enumerate(bins):
            label = b.lab0[:7] if b.lab0 else ""  # "YYYY-MM" for all layout modes
            # uniform_bins and gap_compressed use equal pixel spacing by bin index;
            # calendar_linear uses lab0 start date. Full three-way layout is in _bin_x().
            x = self._bin_x(i, n, b.time_pct, pw, b.lab0) + x0
            tw = fm.horizontalAdvance(label)
            lx = x - tw / 2
            if lx > prev_right + 4:
                p.drawText(int(lx), int(y_base + self._font_size + 2), label)
                prev_right = lx + tw

    def _bin_x(
        self,
        bin_index: int,
        n_bins: int,
        time_pct: float,
        pw: float,
        lab0: Optional[str] = None,
    ) -> float:
        """Return the X pixel offset (from plot origin) for a given bin.

        Layout modes (from series.x_axis_layout):
          - "uniform_bins":   evenly spaced by bin index, ignoring calendar gaps.
          - "calendar_linear": positioned by the bin's start date (lab0). Using the
                              start date rather than the center prevents quantile bins
                              that straddle a gap from appearing inside the gap — a
                              straddling bin spanning May–July renders at its first
                              game date (May), leaving the June gap visually open.
                              Falls back to time_pct when lab0 is not supplied.
          - "gap_compressed": full compressed layout added in a later commit; falls back
                              to uniform_bins until that rendering code is wired.
        """
        if not self._series:
            return (time_pct / 100.0) * pw
        layout = self._series.x_axis_layout
        if layout == "calendar_linear":
            if lab0 is not None and self._series.bins:
                t_min = date.fromisoformat(self._series.bins[0].lab0).toordinal()
                t_max = date.fromisoformat(self._series.bins[-1].lab1).toordinal()
                span = max(1, t_max - t_min)
                return ((date.fromisoformat(lab0).toordinal() - t_min) / span) * pw
            return (time_pct / 100.0) * pw
        # uniform_bins and gap_compressed (pending full port): equal spacing
        if n_bins <= 1:
            return pw / 2
        return (bin_index / (n_bins - 1)) * pw

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
        use_smooth = self._series and self._series.line_style == "smooth"
        strength = self._series.smoothing_strength if self._series else 1.0
        n = len(bins)

        for idx, cat in enumerate(categories):
            if totals.get(cat, 0) == 0:
                continue
            color = self._cat_color(cat, idx)
            pen = QPen(color)
            pen.setWidth(self._line_width)
            p.setPen(pen)

            pts: List[QPointF] = []
            for i, b in enumerate(bins):
                x = x0 + self._bin_x(i, n, b.time_pct, pw, b.lab0)
                count = b.counts.get(cat, 0)
                y = y0 + ph * (1.0 - count / y_max)
                pts.append(QPointF(x, y))

            if use_smooth and len(pts) >= 2:
                path = _smooth_polyline_path(pts, strength=strength)
                if path:
                    p.drawPath(path)
            else:
                for i in range(1, len(pts)):
                    p.drawLine(int(pts[i - 1].x()), int(pts[i - 1].y()),
                               int(pts[i].x()), int(pts[i].y()))

            # Dot at each bin (drawn on top of whichever line style was used)
            p.setBrush(color)
            for pt in pts:
                p.drawEllipse(QRectF(pt.x() - 3, pt.y() - 3, 6, 6))

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
            label = "Uncategorized" if not cat else cat
            p.drawText(int(lx + 14), int(y + self._font_size), label[:24])

    def _cat_color(self, cat: str, idx: int) -> QColor:
        if cat in self._colors:
            return self._colors[cat]
        if not cat:
            return QColor(*_UNCATEGORIZED_COLOR)
        rgb = _FALLBACK_PALETTE[idx % len(_FALLBACK_PALETTE)]
        return QColor(*rgb)
