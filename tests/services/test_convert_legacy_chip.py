"""Tests for ChessLogStorageService.convert_legacy_chip and ConvertAllResult.

Covers:
- Byte-preservation: only the CARAGameTags line changes.
- Header-value preservation: CARAChessLog/Info/Checksum untouched.
- Idempotency: second run reports changed=False.
- Safety: 🏷 chip in CARAGameTags with no CARAChessLog is NOT modified.
- Empty-tags cleanup: chip-only CARAGameTags header line is deleted.
- Report counts: skipped_reason codes from convert_legacy_chip.
- convert_legacy_chip_all aggregator counts via fake database.
"""

from __future__ import annotations

import difflib
import re
import unittest
from dataclasses import dataclass
from typing import List, Optional
from unittest.mock import MagicMock

from app.models.database_model import GameData
from app.services.chess_log_storage_service import ChessLogStorageService, ConvertResult


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

# Minimal but realistic legacy PGN: has CARAChessLog data and 🏷 in CARAGameTags.
_LEGACY_PGN = """\
[Event "Test Game"]
[Site "?"]
[Date "2026.01.15"]
[White "Paul"]
[Black "Opponent"]
[Result "1-0"]
[CARAChessLog "H4sIAAAAAAAAA6tWKkktLlGyUlIqS61QslIqLU4tykvMTQUAHMJPNhgAAAA="]
[CARAChessLogInfo "1 moment (CLAMP)"]
[CARAChessLogChecksum "abc123def456"]
[CARAGameTags "🏷;Rapid;London"]

1. e4 e5 2. Nf3 Nc6 1-0
"""

# Same PGN but chip-only in CARAGameTags.
_LEGACY_CHIP_ONLY_PGN = """\
[Event "Test Game"]
[Site "?"]
[Date "2026.01.15"]
[White "Paul"]
[Black "Opponent"]
[Result "1-0"]
[CARAChessLog "H4sIAAAAAAAAA6tWKkktLlGyUlIqS61QslIqLU4tykvMTQUAHMJPNhgAAAA="]
[CARAChessLogInfo "1 moment (CLAMP)"]
[CARAChessLogChecksum "abc123def456"]
[CARAGameTags "🏷"]

1. e4 e5 2. Nf3 Nc6 1-0
"""

# No CARAChessLog header, but still has 🏷 (should never be touched).
_CHIP_NO_LOG_PGN = """\
[Event "Test Game"]
[Site "?"]
[Date "2026.01.15"]
[White "Paul"]
[Black "Opponent"]
[Result "1-0"]
[CARAGameTags "🏷;Rapid"]

1. e4 e5 1-0
"""

# Already clean — no chip.
_CLEAN_PGN = """\
[Event "Test Game"]
[Site "?"]
[Date "2026.01.15"]
[White "Paul"]
[Black "Opponent"]
[Result "1-0"]
[CARAChessLog "H4sIAAAAAAAAA6tWKkktLlGyUlIqS61QslIqLU4tykvMTQUAHMJPNhgAAAA="]
[CARAChessLogInfo "1 moment (CLAMP)"]
[CARAChessLogChecksum "abc123def456"]
[CARAGameTags "Rapid;London"]

1. e4 e5 2. Nf3 Nc6 1-0
"""


def _make_game(pgn: str, has_chess_log_tags: bool = True, game_tags_raw: str = "") -> GameData:
    return GameData(
        game_number=1,
        white="Paul",
        black="Opponent",
        pgn=pgn,
        has_chess_log_tags=has_chess_log_tags,
        game_tags_raw=game_tags_raw,
    )


def _chess_log_header_values(pgn: str) -> dict:
    """Extract CARAChessLog, CARAChessLogInfo, CARAChessLogChecksum values."""
    result = {}
    for tag in ("CARAChessLog", "CARAChessLogInfo", "CARAChessLogChecksum"):
        m = re.search(rf'^\[{tag}\s+"([^"]*)"\]$', pgn, re.MULTILINE)
        result[tag] = m.group(1) if m else None
    return result


# ---------------------------------------------------------------------------
# Unit tests for convert_legacy_chip()
# ---------------------------------------------------------------------------

class TestConvertLegacyChipBytePreservation(unittest.TestCase):

    def test_only_game_tags_line_changes(self):
        game = _make_game(_LEGACY_PGN)
        before_lines = _LEGACY_PGN.splitlines(keepends=True)
        ChessLogStorageService.convert_legacy_chip(game)
        after_lines = game.pgn.splitlines(keepends=True)
        diff = list(difflib.unified_diff(before_lines, after_lines))
        changed_lines = [l for l in diff if l.startswith(("-", "+")) and not l.startswith(("---", "+++"))]
        # Only the CARAGameTags line should appear as changed (one removed, one added).
        self.assertEqual(len(changed_lines), 2)
        self.assertTrue(any("CARAGameTags" in l for l in changed_lines))

    def test_chess_log_header_values_unchanged(self):
        game = _make_game(_LEGACY_PGN)
        before_vals = _chess_log_header_values(_LEGACY_PGN)
        ChessLogStorageService.convert_legacy_chip(game)
        after_vals = _chess_log_header_values(game.pgn)
        self.assertEqual(before_vals["CARAChessLog"], after_vals["CARAChessLog"])
        self.assertEqual(before_vals["CARAChessLogInfo"], after_vals["CARAChessLogInfo"])
        self.assertEqual(before_vals["CARAChessLogChecksum"], after_vals["CARAChessLogChecksum"])

    def test_remaining_tags_preserved(self):
        game = _make_game(_LEGACY_PGN)
        result = ChessLogStorageService.convert_legacy_chip(game)
        self.assertEqual(result.tags_after, "Rapid;London")
        self.assertIn('CARAGameTags "Rapid;London"', game.pgn)

    def test_move_text_unchanged(self):
        game = _make_game(_LEGACY_PGN)
        ChessLogStorageService.convert_legacy_chip(game)
        self.assertIn("1. e4 e5 2. Nf3 Nc6 1-0", game.pgn)


class TestConvertLegacyChipIdempotency(unittest.TestCase):

    def test_second_run_returns_not_changed(self):
        game = _make_game(_LEGACY_PGN)
        ChessLogStorageService.convert_legacy_chip(game)
        result2 = ChessLogStorageService.convert_legacy_chip(game)
        self.assertFalse(result2.changed)

    def test_second_run_does_not_mutate_pgn(self):
        game = _make_game(_LEGACY_PGN)
        ChessLogStorageService.convert_legacy_chip(game)
        pgn_after_first = game.pgn
        ChessLogStorageService.convert_legacy_chip(game)
        self.assertEqual(game.pgn, pgn_after_first)


class TestConvertLegacyChipSafety(unittest.TestCase):

    def test_chip_without_chess_log_not_modified(self):
        game = _make_game(_CHIP_NO_LOG_PGN, has_chess_log_tags=False)
        original_pgn = game.pgn
        result = ChessLogStorageService.convert_legacy_chip(game)
        self.assertFalse(result.changed)
        self.assertEqual(game.pgn, original_pgn)
        self.assertEqual(result.skipped_reason, "no_chess_log")

    def test_clean_game_returns_not_changed(self):
        game = _make_game(_CLEAN_PGN)
        original_pgn = game.pgn
        result = ChessLogStorageService.convert_legacy_chip(game)
        self.assertFalse(result.changed)
        self.assertEqual(game.pgn, original_pgn)

    def test_no_pgn_returns_not_changed(self):
        game = _make_game("")
        result = ChessLogStorageService.convert_legacy_chip(game)
        self.assertFalse(result.changed)


class TestConvertLegacyChipEmptyTagsCleanup(unittest.TestCase):

    def test_chip_only_tag_deletes_header_line(self):
        game = _make_game(_LEGACY_CHIP_ONLY_PGN)
        result = ChessLogStorageService.convert_legacy_chip(game)
        self.assertTrue(result.changed)
        self.assertNotIn("CARAGameTags", game.pgn)
        self.assertEqual(result.tags_after, "")

    def test_chip_only_tag_no_empty_line_artifacts(self):
        game = _make_game(_LEGACY_CHIP_ONLY_PGN)
        ChessLogStorageService.convert_legacy_chip(game)
        # Should not leave a blank [CARAGameTags ""] line behind.
        self.assertNotIn('[CARAGameTags ""]', game.pgn)

    def test_game_tags_raw_empty_after_chip_only_removal(self):
        game = _make_game(_LEGACY_CHIP_ONLY_PGN)
        ChessLogStorageService.convert_legacy_chip(game)
        self.assertEqual(game.game_tags_raw, "")


class TestConvertLegacyChipAttributes(unittest.TestCase):

    def test_game_tags_raw_updated(self):
        game = _make_game(_LEGACY_PGN)
        ChessLogStorageService.convert_legacy_chip(game)
        self.assertEqual(game.game_tags_raw, "Rapid;London")

    def test_result_tags_before(self):
        game = _make_game(_LEGACY_PGN)
        result = ChessLogStorageService.convert_legacy_chip(game)
        self.assertIn("🏷", result.tags_before)

    def test_result_changed_true(self):
        game = _make_game(_LEGACY_PGN)
        result = ChessLogStorageService.convert_legacy_chip(game)
        self.assertTrue(result.changed)


# ---------------------------------------------------------------------------
# Aggregator tests for convert_legacy_chip_all()
# ---------------------------------------------------------------------------

class TestConvertLegacyChipAll(unittest.TestCase):
    """Tests for ChessLogController.convert_legacy_chip_all aggregator."""

    def _make_controller(self, games: List[GameData]):
        from app.controllers.chess_log_controller import ChessLogController

        class FakeGameModel:
            active_game = None
            active_game_changed = MagicMock()
            def get_active_path(self): return []

        class FakeGameController:
            def get_game_model(self): return FakeGameModel()

        class FakeDb:
            def get_all_games(self): return games

        class FakeDbController:
            def __init__(self):
                self._db = FakeDb()
                self.unsaved_marked = []
            def get_active_database(self): return self._db
            def find_database_model_for_game(self, g): return self._db
            def mark_database_unsaved(self, db): self.unsaved_marked.append(db)

        db_ctrl = FakeDbController()
        ctrl = ChessLogController(
            config={},
            game_controller=FakeGameController(),
            database_controller=db_ctrl,
        )
        return ctrl, db_ctrl

    def _game_with_log_and_chip(self, pgn=_LEGACY_PGN) -> GameData:
        return GameData(
            game_number=1, white="A", black="B",
            pgn=pgn,
            has_chess_log_tags=True,
            game_tags_raw="🏷;Rapid",
        )

    def _game_without_chip(self, pgn=_CLEAN_PGN) -> GameData:
        return GameData(
            game_number=2, white="A", black="B",
            pgn=pgn,
            has_chess_log_tags=True,
            game_tags_raw="Rapid",
        )

    def _game_chip_no_log(self) -> GameData:
        return GameData(
            game_number=3, white="A", black="B",
            pgn=_CHIP_NO_LOG_PGN,
            has_chess_log_tags=False,
            game_tags_raw="🏷;Rapid",
        )

    def test_converted_count(self):
        ctrl, _ = self._make_controller([self._game_with_log_and_chip()])
        result = ctrl.convert_legacy_chip_all()
        self.assertEqual(result.converted, 1)

    def test_skipped_count(self):
        ctrl, _ = self._make_controller([self._game_without_chip()])
        result = ctrl.convert_legacy_chip_all()
        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.converted, 0)

    def test_no_data_with_chip_count(self):
        ctrl, _ = self._make_controller([self._game_chip_no_log()])
        result = ctrl.convert_legacy_chip_all()
        self.assertEqual(result.no_data_with_chip, 1)
        self.assertEqual(result.converted, 0)

    def test_mixed_games(self):
        games = [
            self._game_with_log_and_chip(),
            self._game_without_chip(),
            self._game_chip_no_log(),
        ]
        ctrl, _ = self._make_controller(games)
        result = ctrl.convert_legacy_chip_all()
        self.assertEqual(result.converted, 1)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.no_data_with_chip, 1)

    def test_database_marked_unsaved_after_conversion(self):
        game = self._game_with_log_and_chip()
        ctrl, db_ctrl = self._make_controller([game])
        ctrl.convert_legacy_chip_all()
        self.assertTrue(len(db_ctrl.unsaved_marked) >= 1)

    def test_idempotent_second_run(self):
        game = self._game_with_log_and_chip()
        ctrl, _ = self._make_controller([game])
        ctrl.convert_legacy_chip_all()
        result2 = ctrl.convert_legacy_chip_all()
        self.assertEqual(result2.converted, 0)

    def test_no_active_database_returns_empty_result(self):
        from app.controllers.chess_log_controller import ChessLogController, ConvertAllResult

        class FakeGameModel:
            active_game = None
            active_game_changed = MagicMock()
            def get_active_path(self): return []

        class FakeGameController:
            def get_game_model(self): return FakeGameModel()

        class FakeDbCtrlNoDb:
            def get_active_database(self): return None

        ctrl = ChessLogController(
            config={},
            game_controller=FakeGameController(),
            database_controller=FakeDbCtrlNoDb(),
        )
        result = ctrl.convert_legacy_chip_all()
        self.assertEqual(result.converted, 0)
        self.assertEqual(result.skipped, 0)


if __name__ == "__main__":
    unittest.main()
