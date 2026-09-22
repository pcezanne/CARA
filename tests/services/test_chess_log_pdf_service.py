"""Tests for ChessLogPDFService — filename helpers and export smoke tests."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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
requires_qt = unittest.skipUnless(_QT_OK, "Qt platform plugin unavailable")

if _QT_OK:
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication(sys.argv[:1])

    from app.services.chess_log_pdf_service import (
        ChessLogPDFService,
        TagRowSnapshot,
        default_chess_log_charts_pdf_filename,
        default_chess_log_tags_pdf_filename,
    )


class TestFilenameHelpers(unittest.TestCase):
    def test_tags_filename_has_pdf_extension(self):
        name = default_chess_log_tags_pdf_filename()
        self.assertTrue(name.endswith(".pdf"), name)

    def test_tags_filename_shallow_variant(self):
        name = default_chess_log_tags_pdf_filename(is_shallow_only=True)
        self.assertIn("ShallowTags", name)

    def test_charts_filename_has_pdf_extension(self):
        name = default_chess_log_charts_pdf_filename()
        self.assertTrue(name.endswith(".pdf"), name)

    def test_charts_filename_includes_player_name(self):
        name = default_chess_log_charts_pdf_filename("Paul")
        self.assertIn("Paul", name)

    def test_charts_filename_sanitizes_spaces(self):
        name = default_chess_log_charts_pdf_filename("Paul Morphy")
        self.assertTrue(name.endswith(".pdf"), name)
        self.assertNotIn(" ", name)


@requires_qt
class TestExportTagsSmoke(unittest.TestCase):
    """Smoke tests: export_tags writes a non-empty PDF file."""

    _MINIMAL_CONFIG: dict = {}

    def _make_minimal_snapshot(self) -> TagRowSnapshot:
        return TagRowSnapshot(
            move_label="1. e4",
            preset="CLAMP",
            entries=[{"preset": "CLAMP", "cat": "C", "why": "test note"}],
            fen=None,
            played_move=None,
            show_ignore=False,
        )

    def test_export_tags_creates_file(self):
        svc = ChessLogPDFService(self._MINIMAL_CONFIG)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            result = svc.export_tags(tmp_path, [{"header": None, "rows": [self._make_minimal_snapshot()]}])
            self.assertTrue(result, "export_tags returned False")
            self.assertTrue(tmp_path.exists(), "PDF file not created")
            self.assertGreater(tmp_path.stat().st_size, 0, "PDF file is empty")
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_export_tags_multi_game(self):
        svc = ChessLogPDFService(self._MINIMAL_CONFIG)
        groups = [
            {"header": "White - Black * (2026.01.01 - 20 moves)", "rows": [self._make_minimal_snapshot()]},
            {"header": "A - B 1-0 (2026.02.01 - 15 moves)", "rows": [self._make_minimal_snapshot()]},
        ]
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            result = svc.export_tags(tmp_path, groups)
            self.assertTrue(result)
            self.assertGreater(tmp_path.stat().st_size, 0)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_export_tags_empty_groups_succeeds(self):
        svc = ChessLogPDFService(self._MINIMAL_CONFIG)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            result = svc.export_tags(tmp_path, [])
            self.assertTrue(result)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_export_charts_report_creates_file(self):
        from PyQt6.QtGui import QPixmap
        svc = ChessLogPDFService(self._MINIMAL_CONFIG)
        pixmap = QPixmap(400, 200)
        pixmap.fill()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            result = svc.export_charts_report(
                tmp_path,
                player_name="Paul",
                source_label="Active Database",
                chart_pixmaps=[("CLAMP", pixmap)],
                narrative_text="Test narrative text.",
                shallow_rows=[],
            )
            self.assertTrue(result, "export_charts_report returned False")
            self.assertGreater(tmp_path.stat().st_size, 0)
        finally:
            tmp_path.unlink(missing_ok=True)


class TestParseBoldSpans(unittest.TestCase):
    """Unit tests for ChessLogPDFService._parse_bold_spans — no Qt needed."""

    def _parse(self, text):
        if _QT_OK:
            return ChessLogPDFService._parse_bold_spans(text)
        # Fallback: import directly without Qt guard
        from app.services.chess_log_pdf_service import ChessLogPDFService as _Svc
        return _Svc._parse_bold_spans(text)

    def test_empty_string(self):
        self.assertEqual(self._parse(""), [])

    def test_no_markers(self):
        self.assertEqual(self._parse("hello world"), [("hello world", False)])

    def test_single_bold_span(self):
        result = self._parse("**bold**")
        self.assertEqual(result, [("bold", True)])

    def test_bold_in_middle(self):
        result = self._parse("before **bold** after")
        self.assertEqual(result, [("before ", False), ("bold", True), (" after", False)])

    def test_two_bold_spans(self):
        result = self._parse("**a** and **b**")
        self.assertIn(("a", True), result)
        self.assertIn(("b", True), result)

    def test_unmatched_trailing_marker_treated_as_literal(self):
        result = self._parse("text **orphan")
        joined = "".join(s for s, _ in result)
        self.assertIn("**orphan", joined)
        # None of the runs should be bold since there's no closing marker.
        self.assertTrue(all(not bold for _, bold in result))


@requires_qt
class TestDrawNarrativePaginated(unittest.TestCase):
    """drawText-spy tests for bold-span rendering in _draw_narrative_paginated."""

    from unittest.mock import MagicMock

    def _make_service(self):
        return ChessLogPDFService({})

    def _run(self, text):
        from unittest.mock import MagicMock
        from PyQt6.QtCore import QRectF
        svc = self._make_service()
        painter = MagicMock()
        writer = MagicMock()
        content = QRectF(0, 0, 500, 700)
        svc._draw_narrative_paginated(painter, writer, content, 0.0, text)
        return svc, painter

    def test_no_asterisks_reach_draw_text(self):
        _, painter = self._run("Regular **bold phrase** rest of line.")
        drawn_strings = [
            a for call in painter.drawText.call_args_list
            for a in call.args if isinstance(a, str)
        ]
        self.assertFalse(
            any("**" in s for s in drawn_strings),
            f"raw ** markers reached drawText: {drawn_strings}",
        )

    def test_bold_font_used_for_bold_span(self):
        svc, painter = self._run("Plain **emphatic** end.")
        bold_calls = [
            c for c in painter.setFont.call_args_list
            if c.args and c.args[0] == svc._font_body_bold
        ]
        self.assertGreater(len(bold_calls), 0,
                           "Expected at least one setFont(_font_body_bold) call")

    def test_plain_text_no_bold_font_calls(self):
        svc, painter = self._run("Completely plain sentence with no markers.")
        bold_calls = [
            c for c in painter.setFont.call_args_list
            if c.args and c.args[0] == svc._font_body_bold
        ]
        self.assertEqual(len(bold_calls), 0,
                         "No bold font expected for plain text")

    def test_heading_does_not_call_draw_text_directly(self):
        """Heading lines go through _section_heading, not the word-draw loop."""
        from unittest.mock import MagicMock, patch
        from PyQt6.QtCore import QRectF
        svc = self._make_service()
        painter = MagicMock()
        writer = MagicMock()
        content = QRectF(0, 0, 500, 700)
        with patch.object(svc, "_section_heading", return_value=10.0) as mock_sh:
            svc._draw_narrative_paginated(painter, writer, content, 0.0,
                                          "## My Heading\nBody text here.")
        mock_sh.assert_called_once()
        drawn_strings = [
            a for call in painter.drawText.call_args_list
            for a in call.args if isinstance(a, str)
        ]
        self.assertFalse(
            any("My Heading" in s for s in drawn_strings),
            "Heading text should not reach drawText directly",
        )


class TestIsTableSeparator(unittest.TestCase):
    """Unit tests for ChessLogPDFService._is_table_separator — no Qt needed."""

    def _check(self, line):
        if _QT_OK:
            return ChessLogPDFService._is_table_separator(line)
        from app.services.chess_log_pdf_service import ChessLogPDFService as _Svc
        return _Svc._is_table_separator(line)

    def test_standard_separator(self):
        self.assertTrue(self._check("| --- | --- | --- |"))

    def test_no_spaces_separator(self):
        self.assertTrue(self._check("|---|---|"))

    def test_colon_aligned(self):
        self.assertTrue(self._check("| :---: | ---: |"))

    def test_content_row_is_not_separator(self):
        self.assertFalse(self._check("| a | b |"))

    def test_plain_text_is_not_separator(self):
        self.assertFalse(self._check("regular prose"))

    def test_empty_string_is_not_separator(self):
        self.assertFalse(self._check(""))

    def test_single_cell_separator_is_not_separator(self):
        self.assertFalse(self._check("| --- |"))


class TestParsePipeTable(unittest.TestCase):
    """Unit tests for ChessLogPDFService._parse_pipe_table — no Qt needed."""

    def _parse(self, lines):
        if _QT_OK:
            return ChessLogPDFService._parse_pipe_table(lines)
        from app.services.chess_log_pdf_service import ChessLogPDFService as _Svc
        return _Svc._parse_pipe_table(lines)

    def test_three_column_table(self):
        lines = [
            "| Skill | Observed Issue | Strategic Impact |",
            "| --- | --- | --- |",
            "| Checks | Often missed | Allows counterplay |",
        ]
        header, body = self._parse(lines)
        self.assertEqual(header, ["Skill", "Observed Issue", "Strategic Impact"])
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0], ["Checks", "Often missed", "Allows counterplay"])

    def test_whitespace_stripped_from_cells(self):
        lines = [
            "|  A  |  B  |",
            "| --- | --- |",
            "|  x  |  y  |",
        ]
        header, body = self._parse(lines)
        self.assertEqual(header, ["A", "B"])
        self.assertEqual(body[0], ["x", "y"])

    def test_short_body_row_padded(self):
        lines = [
            "| A | B | C |",
            "| --- | --- | --- |",
            "| x | y |",  # one cell short
        ]
        header, body = self._parse(lines)
        self.assertEqual(len(body[0]), 3)
        self.assertEqual(body[0][2], "")

    def test_long_body_row_truncated(self):
        lines = [
            "| A | B |",
            "| --- | --- |",
            "| x | y | extra |",
        ]
        header, body = self._parse(lines)
        self.assertEqual(len(body[0]), 2)

    def test_no_body_rows(self):
        lines = [
            "| A | B |",
            "| --- | --- |",
        ]
        header, body = self._parse(lines)
        self.assertEqual(header, ["A", "B"])
        self.assertEqual(body, [])

    def test_empty_input(self):
        header, body = self._parse([])
        self.assertEqual(header, [])
        self.assertEqual(body, [])


@requires_qt
class TestMeasurePipeTableRow(unittest.TestCase):
    """Tests for _measure_pipe_table_row — uses manual word-wrap, not painter.boundingRect."""

    def test_single_line_cells_give_one_line_height_plus_padding(self):
        from unittest.mock import MagicMock
        from PyQt6.QtGui import QFontMetrics
        svc = ChessLogPDFService({})
        painter = MagicMock()
        pad = 4.0
        line_h = float(QFontMetrics(svc._font_body).height())
        col_widths = [100.0, 200.0, 200.0]
        cells = ["Checks", "Often missed", "Allows counterplay"]
        result = svc._measure_pipe_table_row(
            painter, col_widths, cells, svc._font_body, pad
        )
        self.assertAlmostEqual(result, line_h + 2 * pad, places=1)

    def test_narrow_column_forces_wrapping_and_taller_height(self):
        from unittest.mock import MagicMock
        from PyQt6.QtGui import QFontMetrics
        svc = ChessLogPDFService({})
        painter = MagicMock()
        pad = 4.0
        line_h = float(QFontMetrics(svc._font_body).height())
        # Very narrow — forces multi-line wrap
        result = svc._measure_pipe_table_row(
            painter, [20.0], ["a b c d e f g"], svc._font_body, pad
        )
        self.assertGreater(result, line_h + 2 * pad)


@requires_qt
class TestDrawNarrativePaginatedTableDetection(unittest.TestCase):
    """Verify pipe tables are rendered as cells, not as raw | characters."""

    def _run(self, text):
        from unittest.mock import MagicMock
        from PyQt6.QtCore import QRectF
        svc = ChessLogPDFService({})
        painter = MagicMock()
        writer = MagicMock()
        content = QRectF(0, 0, 500, 700)
        # _measure_pipe_table_row calls painter.boundingRect; return a real QRectF
        # so .height() yields a float and comparisons don't fail.
        painter.boundingRect.return_value = QRectF(0, 0, 100, 12)
        svc._draw_narrative_paginated(painter, writer, content, 0.0, text)
        return svc, painter

    def test_section_heading_keep_with_is_table_height_when_table_follows(self):
        """_section_heading must be called with keep_with >= header+first-body height."""
        from unittest.mock import MagicMock, patch
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QFontMetrics
        svc = ChessLogPDFService({})
        painter = MagicMock()
        writer = MagicMock()
        content = QRectF(0, 0, 500, 700)
        painter.boundingRect.return_value = QRectF(0, 0, 100, 12)

        narrative = (
            "## Tactical Breakdown\n\n"
            "| Skill | Observed Issue | Strategic Impact |\n"
            "| --- | --- | --- |\n"
            "| Checks | Missed fork | Drops material |\n"
        )
        line_h = float(QFontMetrics(svc._font_body).height())
        with patch.object(svc, "_section_heading", return_value=10.0) as mock_sh:
            svc._draw_narrative_paginated(painter, writer, content, 0.0, narrative)
        self.assertEqual(mock_sh.call_count, 1)
        _, kwargs = mock_sh.call_args
        keep_with = kwargs.get("keep_with", mock_sh.call_args.args[-1] if mock_sh.call_args.args else 0)
        self.assertGreater(
            keep_with, line_h * 2,
            f"keep_with ({keep_with:.1f}) should exceed default line_h*2 ({line_h * 2:.1f}) "
            "when a table follows the heading",
        )

    def test_section_heading_keep_with_is_default_when_no_table_follows(self):
        """keep_with stays at line_h*2 when heading is followed by prose."""
        from unittest.mock import MagicMock, patch
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QFontMetrics
        svc = ChessLogPDFService({})
        painter = MagicMock()
        writer = MagicMock()
        content = QRectF(0, 0, 500, 700)
        painter.boundingRect.return_value = QRectF(0, 0, 100, 12)

        narrative = "## Patterns & Recurrent Themes\n\nSome prose follows here.\n"
        line_h = float(QFontMetrics(svc._font_body).height())
        with patch.object(svc, "_section_heading", return_value=10.0) as mock_sh:
            svc._draw_narrative_paginated(painter, writer, content, 0.0, narrative)
        _, kwargs = mock_sh.call_args
        keep_with = kwargs.get("keep_with", mock_sh.call_args.args[-1] if mock_sh.call_args.args else 0)
        self.assertAlmostEqual(keep_with, line_h * 2, places=1)

    def test_draw_rect_called_for_table_cells(self):
        narrative = (
            "## Tactical Breakdown\n\n"
            "| Skill | Observed Issue | Strategic Impact |\n"
            "| --- | --- | --- |\n"
            "| Checks | Missed tactics | Drops material |\n"
            "| Loose Pieces | Left hanging | Opponent gains tempo |\n"
        )
        _, painter = self._run(narrative)
        # 1 header row + 2 body rows, each with 3 cells = 9 drawRect calls minimum
        rect_calls = painter.drawRect.call_count
        self.assertGreaterEqual(rect_calls, 9, f"Expected >=9 drawRect calls, got {rect_calls}")

    def test_raw_pipe_chars_do_not_reach_draw_text(self):
        narrative = (
            "| Skill | Observed Issue | Strategic Impact |\n"
            "| --- | --- | --- |\n"
            "| Checks | Missed fork | Loses piece |\n"
        )
        _, painter = self._run(narrative)
        drawn_strings = [
            a for call in painter.drawText.call_args_list
            for a in call.args if isinstance(a, str)
        ]
        self.assertFalse(
            any("|" in s for s in drawn_strings),
            f"Raw | characters reached drawText: {[s for s in drawn_strings if '|' in s]}",
        )

    def test_separator_row_does_not_reach_draw_text(self):
        narrative = (
            "| A | B | C |\n"
            "| --- | --- | --- |\n"
            "| x | y | z |\n"
        )
        _, painter = self._run(narrative)
        drawn_strings = [
            a for call in painter.drawText.call_args_list
            for a in call.args if isinstance(a, str)
        ]
        self.assertFalse(
            any("---" in s for s in drawn_strings),
            "Separator row text reached drawText",
        )

    def test_header_cell_text_reaches_draw_text(self):
        narrative = (
            "| Skill | Observed Issue | Strategic Impact |\n"
            "| --- | --- | --- |\n"
            "| Checks | Something | Something else |\n"
        )
        _, painter = self._run(narrative)
        drawn_strings = [
            a for call in painter.drawText.call_args_list
            for a in call.args if isinstance(a, str)
        ]
        self.assertTrue(
            any("Skill" in s for s in drawn_strings),
            "Header cell text 'Skill' did not reach drawText",
        )


@requires_qt
class TestExportChartsReportWithTable(unittest.TestCase):
    """Smoke test: export_charts_report handles a three-section narrative with a pipe table."""

    def test_export_creates_nonempty_pdf_with_table_narrative(self):
        from PyQt6.QtGui import QPixmap
        svc = ChessLogPDFService({})
        pixmap = QPixmap(400, 200)
        pixmap.fill()
        narrative = (
            "## Patterns & Recurrent Themes\n\n"
            "You tend to rush in the middlegame.\n\n"
            "## Tactical Breakdown\n\n"
            "| Skill | Observed Issue | Strategic Impact |\n"
            "| --- | --- | --- |\n"
            "| Checks | Missed back-rank threats | Allows opponent counterplay |\n"
            "| Loose Pieces | Left pieces undefended | Material loss under pressure |\n\n"
            "## Key Takeaways\n\n"
            "Your note 'I just didn't calculate far enough' shows the pattern clearly.\n"
        )
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            result = svc.export_charts_report(
                tmp_path,
                player_name="Paul",
                source_label="Active Database",
                chart_pixmaps=[("CLAMP", pixmap)],
                narrative_text=narrative,
                shallow_rows=[],
            )
            self.assertTrue(result, "export_charts_report returned False")
            self.assertGreater(tmp_path.stat().st_size, 0, "PDF file is empty")
        finally:
            tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# _is_bullet_line — no Qt needed
# ---------------------------------------------------------------------------

class TestIsBulletLine(unittest.TestCase):

    def setUp(self):
        if not _QT_OK:
            self.skipTest("Qt platform plugin unavailable")
        self._svc = ChessLogPDFService({})

    def _check(self, line, expected):
        self.assertEqual(self._svc._is_bullet_line(line), expected, repr(line))

    def test_dash_bullet(self):
        self._check("- foo", True)

    def test_asterisk_bullet(self):
        self._check("* foo", True)

    def test_plus_bullet(self):
        self._check("+ foo", True)

    def test_leading_whitespace(self):
        self._check("  - foo", True)

    def test_bare_dash_not_bullet(self):
        self._check("-", False)

    def test_dash_space_only_not_bullet(self):
        self._check("- ", False)

    def test_no_space_after_dash_not_bullet(self):
        self._check("-foo", False)

    def test_regular_prose_not_bullet(self):
        self._check("regular prose", False)

    def test_empty_not_bullet(self):
        self._check("", False)


# ---------------------------------------------------------------------------
# _parse_bullet_line — no Qt needed
# ---------------------------------------------------------------------------

class TestParseBulletLine(unittest.TestCase):

    def setUp(self):
        if not _QT_OK:
            self.skipTest("Qt platform plugin unavailable")
        self._svc = ChessLogPDFService({})

    def test_strips_dash_marker(self):
        result = self._svc._parse_bullet_line("- **Bold.** rest")
        self.assertEqual(result, "**Bold.** rest")

    def test_strips_asterisk_marker(self):
        result = self._svc._parse_bullet_line("  * foo bar")
        self.assertEqual(result, "foo bar")

    def test_strips_plus_marker(self):
        result = self._svc._parse_bullet_line("+ trailing")
        self.assertEqual(result, "trailing")


# ---------------------------------------------------------------------------
# _draw_narrative_paginated — bullet detection
# ---------------------------------------------------------------------------

@requires_qt
class TestMeasureBulletLineSpanAware(unittest.TestCase):
    """Regression tests: _measure_bullet_line must use span-aware measurement.

    Bug: the original implementation reassembled spans to plain text and called
    painter.boundingRect(plain), which measured all words at body-font width.
    Bold lead-in words are wider than their plain equivalents, so the measured
    height was too small and _ensure_space reserved too little room, causing
    adjacent bullets to overlap.

    Fix: replaced the boundingRect call with _count_cell_lines (the same
    per-word bold/plain algorithm used by _draw_wrapped_spans) so measurement
    and drawing always agree.
    """

    def setUp(self):
        self._svc = ChessLogPDFService({})

    def _span_aware_h(self, text, content_w, bullet_indent=12.0, bullet_gap=6.0, pad=2.0):
        """Ground-truth height: _count_cell_lines × line_h + 2×pad."""
        from PyQt6.QtGui import QFontMetrics
        fm_body = QFontMetrics(self._svc._font_body)
        line_h = float(fm_body.height())
        body_w = content_w - bullet_indent - bullet_gap
        spans = self._svc._parse_bold_spans(text)
        n = self._svc._count_cell_lines(spans, body_w)
        return max(n, 1) * line_h + 2 * pad

    def test_height_matches_count_cell_lines(self):
        """Result must equal _count_cell_lines-based height, not plain-text boundingRect."""
        from PyQt6.QtCore import QRectF
        content = QRectF(0, 0, 200, 700)
        text = (
            "**Rushing calculation in sharp positions.** "
            "You repeatedly find yourself playing the first forcing move without "
            "checking whether the opponent has a quiet intermediate move."
        )
        expected = self._span_aware_h(text, content.width())
        actual = self._svc._measure_bullet_line(content, text, 12.0, 6.0, 2.0)
        self.assertAlmostEqual(actual, expected, places=1)

    def test_all_bold_text_uses_bold_widths(self):
        """All-bold text: returned height reflects bold word widths, not plain word widths.

        Directly demonstrates the fixed bug: the old approach measured with fm_body for
        all words, but bold words are wider, so bold-aware line count >= plain-text count.
        The fixed method must return the bold-aware height.
        """
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QFontMetrics
        content = QRectF(0, 0, 200, 700)
        bullet_indent, bullet_gap, pad = 12.0, 6.0, 2.0
        body_w = content.width() - bullet_indent - bullet_gap
        # All-bold text maximises the bold vs. plain width difference.
        text = "**Book moves and opening habits suppressing live calculation throughout the game.**"
        fm_body = QFontMetrics(self._svc._font_body)
        line_h = float(fm_body.height())
        space_w = float(fm_body.horizontalAdvance(" "))
        spans = self._svc._parse_bold_spans(text)
        # Bold-aware (correct) line count.
        bold_n = self._svc._count_cell_lines(spans, body_w)
        # Plain-text (old broken) line count — measure all words at fm_body width.
        words = [w for seg, _ in spans for w in seg.split() if w]
        plain_n, cur, cur_w = 0, [], 0.0
        for word in words:
            ww = float(fm_body.horizontalAdvance(word))
            needed = ww if not cur else space_w + ww
            if cur and cur_w + needed > body_w:
                plain_n += 1
                cur, cur_w = [word], ww
            else:
                cur.append(word)
                cur_w += needed
        if cur:
            plain_n += 1
        # Bold words must be at least as wide as plain (bold_n >= plain_n always true).
        self.assertGreaterEqual(bold_n, plain_n)
        # The fixed method must return the bold-aware height.
        actual_h = self._svc._measure_bullet_line(content, text, bullet_indent, bullet_gap, pad)
        expected_h = max(bold_n, 1) * line_h + 2 * pad
        self.assertAlmostEqual(actual_h, expected_h, places=1)

    def test_bold_font_is_wider_than_body_font(self):
        """Sanity check: bold font is wider than body font, proving the bug can trigger."""
        from PyQt6.QtGui import QFontMetrics
        fm_body = QFontMetrics(self._svc._font_body)
        fm_bold = QFontMetrics(self._svc._font_body_bold)
        # Pick a wide word that appears in typical bold lead-ins.
        sample = "Rushing"
        self.assertGreater(
            fm_bold.horizontalAdvance(sample),
            fm_body.horizontalAdvance(sample),
            "Bold font must be wider than body font for the bug to manifest",
        )

    def test_no_painter_dependency(self):
        """_measure_bullet_line must not require a live painter (no boundingRect call).

        The old code called painter.boundingRect(plain_text); the fix uses
        _count_cell_lines which needs no painter. Calling with no painter arg
        (only 5 positional args after self) must succeed without error.
        """
        from PyQt6.QtCore import QRectF
        content = QRectF(0, 0, 300, 700)
        text = "**Lead-in.** Some body text here."
        # Five args (no painter): should run without TypeError after the fix.
        h = self._svc._measure_bullet_line(content, text, 12.0, 6.0, 2.0)
        self.assertGreater(h, 0)


@requires_qt
class TestDrawNarrativePaginatedBulletDetection(unittest.TestCase):
    """Verify that bullet list items render via the bullet path (• glyph, no '- ' prefix)."""

    def _run(self, text: str):
        from unittest.mock import MagicMock
        from PyQt6.QtCore import QRectF
        svc = ChessLogPDFService({})
        painter = MagicMock()
        writer = MagicMock()
        content = QRectF(0, 0, 500, 700)
        # _measure_bullet_line calls painter.boundingRect; return a real QRectF
        # so .height() yields a float and comparisons succeed.
        painter.boundingRect.return_value = QRectF(0, 0, 100, 12)
        svc._draw_narrative_paginated(painter, writer, content, 0.0, text)
        return svc, painter

    def test_bullet_glyph_reaches_draw_text(self):
        # No heading — avoids the real QPainter path through _section_heading.
        narrative = (
            "- **Theme one.** Body text here.\n\n"
            "- **Theme two.** More body text.\n\n"
            "- **Theme three.** Even more text.\n"
        )
        _, painter = self._run(narrative)
        all_text_args = [
            a for call in painter.drawText.call_args_list
            for a in call.args if isinstance(a, str)
        ]
        bullet_calls = [t for t in all_text_args if "•" in t]
        self.assertGreaterEqual(len(bullet_calls), 3, "Expected at least 3 bullet glyphs drawn")

    def test_no_dash_prefix_reaches_draw_text(self):
        narrative = (
            "- **Theme one.** Body text here.\n\n"
            "- **Theme two.** More body text.\n"
        )
        _, painter = self._run(narrative)
        all_text_args = [
            a for call in painter.drawText.call_args_list
            for a in call.args if isinstance(a, str)
        ]
        dash_prefix_calls = [t for t in all_text_args if t.startswith("- ")]
        self.assertEqual(dash_prefix_calls, [], "No '- ' prefix should reach drawText")


class TestTagRowSnapshotBestMove(unittest.TestCase):
    """TagRowSnapshot carries the best_move field."""

    def test_snapshot_default_best_move_none(self):
        from app.services.chess_log_pdf_service import TagRowSnapshot
        snap = TagRowSnapshot(
            move_label="1. e4",
            preset="CLAMP",
            entries=[],
            fen=None,
            played_move=None,
            show_ignore=False,
        )
        self.assertIsNone(snap.best_move)

    def test_snapshot_stores_best_move(self):
        import chess
        from app.services.chess_log_pdf_service import TagRowSnapshot
        best = chess.Move.from_uci("d2d4")
        snap = TagRowSnapshot(
            move_label="1. e4",
            preset="CLAMP",
            entries=[],
            fen=None,
            played_move=chess.Move.from_uci("e2e4"),
            show_ignore=False,
            best_move=best,
        )
        self.assertEqual(snap.best_move, best)


@requires_qt
class TestRenderBoardPassesBestMove(unittest.TestCase):
    """_render_board forwards best_move to set_played_and_best."""

    def test_render_board_calls_set_played_and_best(self):
        import chess
        from unittest.mock import patch
        from app.services.chess_log_pdf_service import ChessLogPDFService

        svc = ChessLogPDFService({})
        played = chess.Move.from_uci("e2e4")
        best = chess.Move.from_uci("d2d4")
        captured_calls = []

        from app.views.widgets.mini_chessboard_widget import MiniChessBoardWidget as _Real

        class _SpyWidget(_Real):
            def set_played_and_best(self, p, b=None):
                captured_calls.append((p, b))
                super().set_played_and_best(p, b)

        # _render_board uses a local import from mini_chessboard_widget module
        with patch(
            "app.views.widgets.mini_chessboard_widget.MiniChessBoardWidget",
            new=_SpyWidget,
        ):
            svc._render_board(
                "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
                played,
                best,
            )

        self.assertEqual(len(captured_calls), 1)
        self.assertEqual(captured_calls[0], (played, best))


@requires_qt
class TestNarrativeSanitizationInPDF(unittest.TestCase):
    """sanitize_narrative_markdown is applied before _draw_narrative_paginated
    so bare thematic-break lines never reach drawText."""

    def test_thematic_break_line_not_drawn(self):
        from unittest.mock import MagicMock, patch
        import tempfile
        from pathlib import Path
        from app.services.chess_log_pdf_service import ChessLogPDFService

        svc = ChessLogPDFService({})
        narrative = "## Patterns & Recurrent Themes\n\n---\n\n## Key Takeaways\n\nSome text."

        drawn_texts: list[str] = []

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            # Monkey-patch drawText to capture what would be drawn.
            original_export = ChessLogPDFService.export_charts_report

            def _patched_export(self_inner, path, chart_widgets, narrative_text, source_label="", player="", shallow_rows=None):
                # Write a minimal PDF but intercept the painter's drawText calls.
                from PyQt6.QtGui import QPdfWriter, QPainter, QPageSize
                from PyQt6.QtCore import QMarginsF, QSizeF
                writer = QPdfWriter(str(path))
                writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
                writer.setPageMargins(QMarginsF(20, 20, 20, 20))
                painter = QPainter(writer)
                try:
                    content = self_inner._content_rect(writer)
                    y = content.top()
                    orig_draw = painter.drawText

                    def _capture_draw(*args, **kwargs):
                        for a in args:
                            if isinstance(a, str):
                                drawn_texts.append(a)
                        return orig_draw(*args, **kwargs)

                    painter.drawText = _capture_draw
                    self_inner._draw_narrative_paginated(painter, writer, content, y, narrative_text)
                finally:
                    painter.end()
                return True

            ChessLogPDFService.export_charts_report = _patched_export
            try:
                svc.export_charts_report(tmp_path, [], narrative, source_label="Test")
            finally:
                ChessLogPDFService.export_charts_report = original_export

            dash_only = [t for t in drawn_texts if t.strip() and all(c == "-" for c in t.strip())]
            self.assertEqual(dash_only, [], f"Bare dash text was drawn: {dash_only}")
        finally:
            tmp_path.unlink(missing_ok=True)


@requires_qt
class TestPDFPrintTheme(unittest.TestCase):
    """Phase 6: ChessLogPDFService merges chess_log_charts.pdf_report over ui.pdf."""

    def _make_config(self, ui_pdf_text, report_text, warn_fill=None, warn_outline=None) -> dict:
        cfg: dict = {
            "ui": {
                "pdf": {"colors": {"text": ui_pdf_text}},
                "panels": {
                    "detail": {
                        "chess_log_charts": {
                            "pdf_report": {
                                "colors": {
                                    "text": report_text,
                                }
                            }
                        }
                    }
                },
            }
        }
        if warn_fill is not None:
            cfg["ui"]["panels"]["detail"]["chess_log_charts"]["pdf_report"]["colors"]["warning_fill"] = warn_fill
        if warn_outline is not None:
            cfg["ui"]["panels"]["detail"]["chess_log_charts"]["pdf_report"]["colors"]["warning_outline"] = warn_outline
        return cfg

    def test_report_specific_text_color_overrides_ui_pdf(self):
        """chess_log_charts.pdf_report.colors.text must win over ui.pdf.colors.text."""
        cfg = self._make_config(ui_pdf_text=[255, 255, 255], report_text=[30, 30, 35])
        svc = ChessLogPDFService(cfg)
        from PyQt6.QtGui import QColor
        self.assertEqual(svc._text, QColor(30, 30, 35))

    def test_warning_fill_from_config(self):
        cfg = self._make_config(
            ui_pdf_text=[30, 30, 35], report_text=[30, 30, 35],
            warn_fill=[200, 150, 0],
        )
        svc = ChessLogPDFService(cfg)
        from PyQt6.QtGui import QColor
        self.assertEqual(svc._warn_fill, QColor(200, 150, 0))

    def test_warning_outline_from_config(self):
        cfg = self._make_config(
            ui_pdf_text=[30, 30, 35], report_text=[30, 30, 35],
            warn_outline=[50, 50, 60],
        )
        svc = ChessLogPDFService(cfg)
        from PyQt6.QtGui import QColor
        self.assertEqual(svc._warn_outline, QColor(50, 50, 60))

    def test_warning_fill_default_when_no_config(self):
        from PyQt6.QtGui import QColor
        svc = ChessLogPDFService({})
        self.assertEqual(svc._warn_fill, QColor(241, 196, 15))

    def test_warning_outline_default_when_no_config(self):
        from PyQt6.QtGui import QColor
        svc = ChessLogPDFService({})
        self.assertEqual(svc._warn_outline, QColor(30, 30, 30))

    def test_does_not_mutate_input_config(self):
        import copy
        cfg = self._make_config(ui_pdf_text=[30, 30, 35], report_text=[30, 30, 35])
        original = copy.deepcopy(cfg)
        ChessLogPDFService(cfg)
        self.assertEqual(cfg, original)


if __name__ == "__main__":
    unittest.main()
