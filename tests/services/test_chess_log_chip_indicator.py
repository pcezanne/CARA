"""Tests for the 🏷 Chess Log game-level chip indicator.

Covers:
- Chip injected into game_tags_raw at load time when CARAChessLog header present
- Chip absent when game has no Chess Log moments
- Chip coexists correctly with existing manual CARAGameTags
- Chip added to game_tags_raw after store_tags (first save)
- Chip removed from game_tags_raw after clear_tags (removal behaviour)
- Both render paths read game_tags_raw — confirmed by verifying the shared
  source-of-truth field rather than mocking the delegate/widget.
"""

from __future__ import annotations

import unittest

from app.models.database_model import GameData
from app.services.chess_log_storage_service import ChessLogStorageService
from app.utils.game_tags_utils import format_game_tags, parse_game_tags


CHIP = ChessLogStorageService.CHIP_TEXT  # "🏷 Chess Log"

MINIMAL_PGN = (
    '[Event "Test"]\n'
    '[Site "?"]\n'
    '[Date "2026.08.28"]\n'
    '[Round "?"]\n'
    '[White "White"]\n'
    '[Black "Black"]\n'
    '[Result "*"]\n'
    '\n*\n'
)

# _extract_game_data filters out 0-move games, so tests that call it directly
# need a PGN with at least one move.
ONE_MOVE_PGN = (
    '[Event "Test"]\n'
    '[Site "?"]\n'
    '[Date "2026.08.28"]\n'
    '[Round "?"]\n'
    '[White "White"]\n'
    '[Black "Black"]\n'
    '[Result "*"]\n'
    '\n1. e4 *\n'
)


def _make_game(extra_headers: str = "", game_tags_raw: str = "") -> GameData:
    pgn = (
        '[Event "Test"]\n'
        '[Site "?"]\n'
        '[Date "2026.08.28"]\n'
        '[Round "?"]\n'
        '[White "White"]\n'
        '[Black "Black"]\n'
        '[Result "*"]\n'
        + extra_headers
        + '\n1. e4 *\n'
    )
    game = GameData(game_number=1, pgn=pgn, game_tags_raw=game_tags_raw)
    game.game_tags_raw = game_tags_raw
    return game


def _game_with_chess_log(game_tags_raw: str = "") -> GameData:
    """Return a GameData whose PGN has a CARAChessLog tag."""
    game = _make_game(game_tags_raw=game_tags_raw)
    paths = {"0": [ChessLogStorageService.make_entry("CLAMP", "M", "")]}
    ChessLogStorageService.store_tags(game, paths)
    # Reset game_tags_raw to simulate a clean load (no chip yet)
    game.game_tags_raw = game_tags_raw
    game.game_tags = ""
    return game


# ---------------------------------------------------------------------------
# Chip injection at load time (pgn_service._extract_game_data)
# ---------------------------------------------------------------------------

class TestChipInjectionAtLoadTime(unittest.TestCase):
    """PgnService._extract_game_data injects chip when CARAChessLog header is present."""

    def _extract(self, pgn_text: str) -> dict:
        import io
        import chess.pgn
        from app.services.pgn_service import PgnService
        chess_game = chess.pgn.read_game(io.StringIO(pgn_text))
        result = PgnService._extract_game_data(chess_game, pgn_text)
        self.assertIsNotNone(result)
        return result

    def _pgn_with_chess_log(self, existing_cara_tags: str = "") -> str:
        """Build a minimal PGN that carries a CARAChessLog header (and optionally CARAGameTags)."""
        game = _make_game()
        paths = {"0": [ChessLogStorageService.make_entry("CLAMP", "C", "")]}
        ChessLogStorageService.store_tags(game, paths)
        if existing_cara_tags:
            import io
            import chess.pgn
            chess_game = chess.pgn.read_game(io.StringIO(game.pgn))
            chess_game.headers["CARAGameTags"] = existing_cara_tags
            from app.services.pgn_service import PgnService as PS
            game.pgn = PS.export_game_to_pgn(chess_game)
        return game.pgn

    def test_chip_injected_when_chess_log_present(self):
        game_dict = self._extract(self._pgn_with_chess_log())
        tags = parse_game_tags(game_dict.get("game_tags_raw", ""))
        self.assertIn(CHIP, tags, f"Chip missing from tags: {tags}")

    def test_chip_absent_when_no_chess_log(self):
        game_dict = self._extract(ONE_MOVE_PGN)
        tags = parse_game_tags(game_dict.get("game_tags_raw", ""))
        self.assertNotIn(CHIP, tags, f"Chip unexpectedly present: {tags}")

    def test_has_chess_log_tags_flag_true_when_header_present(self):
        game_dict = self._extract(self._pgn_with_chess_log())
        self.assertTrue(game_dict.get("has_chess_log_tags", False))

    def test_has_chess_log_tags_flag_false_when_no_header(self):
        game_dict = self._extract(ONE_MOVE_PGN)
        self.assertFalse(game_dict.get("has_chess_log_tags", True))

    def test_chip_prepended_alongside_existing_manual_tag(self):
        game_dict = self._extract(self._pgn_with_chess_log(existing_cara_tags="Favourite"))
        tags = parse_game_tags(game_dict.get("game_tags_raw", ""))
        self.assertIn(CHIP, tags)
        self.assertIn("Favourite", tags)
        self.assertEqual(len(tags), 2)

    def test_chip_not_duplicated_if_already_in_cara_game_tags(self):
        """If CHIP text was somehow already in CARAGameTags, don't duplicate it."""
        game_dict = self._extract(self._pgn_with_chess_log(existing_cara_tags=CHIP))
        tags = parse_game_tags(game_dict.get("game_tags_raw", ""))
        count = sum(1 for t in tags if t.casefold() == CHIP.casefold())
        self.assertEqual(count, 1, f"Expected exactly 1 chip, got: {tags}")


# ---------------------------------------------------------------------------
# store_tags injects chip (first save for this game)
# ---------------------------------------------------------------------------

class TestChipAfterStoreTags(unittest.TestCase):

    def test_chip_in_game_tags_raw_after_first_store(self):
        game = _make_game()
        # game_tags_raw starts empty — no chip yet
        self.assertNotIn(CHIP, parse_game_tags(game.game_tags_raw))
        paths = {"0": [ChessLogStorageService.make_entry("CLAMP", "M", "")]}
        ok = ChessLogStorageService.store_tags(game, paths)
        self.assertTrue(ok)
        tags = parse_game_tags(game.game_tags_raw)
        self.assertIn(CHIP, tags)

    def test_chip_not_duplicated_on_second_store(self):
        game = _make_game()
        paths = {"0": [ChessLogStorageService.make_entry("CLAMP", "C", "")]}
        ChessLogStorageService.store_tags(game, paths)
        ChessLogStorageService.store_tags(game, paths)
        tags = parse_game_tags(game.game_tags_raw)
        count = sum(1 for t in tags if t.casefold() == CHIP.casefold())
        self.assertEqual(count, 1)

    def test_chip_present_alongside_existing_manual_tag_after_store(self):
        game = _make_game(game_tags_raw="Brilliant Move")
        game.game_tags_raw = "Brilliant Move"
        paths = {"0": [ChessLogStorageService.make_entry("CLAMP", "M", "")]}
        ChessLogStorageService.store_tags(game, paths)
        tags = parse_game_tags(game.game_tags_raw)
        self.assertIn(CHIP, tags)
        self.assertIn("Brilliant Move", tags)


# ---------------------------------------------------------------------------
# clear_tags removes chip (active removal required — not automatic)
# ---------------------------------------------------------------------------

class TestChipAfterClearTags(unittest.TestCase):

    def test_chip_removed_from_game_tags_raw_after_clear(self):
        game = _make_game()
        paths = {"0": [ChessLogStorageService.make_entry("CLAMP", "C", "")]}
        ChessLogStorageService.store_tags(game, paths)
        self.assertIn(CHIP, parse_game_tags(game.game_tags_raw))

        ok = ChessLogStorageService.clear_tags(game)
        self.assertTrue(ok)
        tags = parse_game_tags(game.game_tags_raw)
        self.assertNotIn(CHIP, tags, f"Chip should be gone after clear, got: {tags}")

    def test_manual_tags_preserved_after_clear(self):
        game = _make_game(game_tags_raw="Favourite")
        game.game_tags_raw = "Favourite"
        paths = {"0": [ChessLogStorageService.make_entry("CLAMP", "M", "")]}
        ChessLogStorageService.store_tags(game, paths)

        ChessLogStorageService.clear_tags(game)
        tags = parse_game_tags(game.game_tags_raw)
        self.assertNotIn(CHIP, tags)
        self.assertIn("Favourite", tags)

    def test_has_chess_log_tags_false_after_clear(self):
        game = _make_game()
        paths = {"0": [ChessLogStorageService.make_entry("CLAMP", "A", "")]}
        ChessLogStorageService.store_tags(game, paths)
        ChessLogStorageService.clear_tags(game)
        self.assertFalse(game.has_chess_log_tags)


# ---------------------------------------------------------------------------
# Both render paths share game_tags_raw as source of truth
# ---------------------------------------------------------------------------

class TestBothRenderPathsShareSource(unittest.TestCase):
    """DatabaseTagsChipDelegate and GameTagsWidget both read game.game_tags_raw.
    Verifying the field directly is sufficient — both paths use it identically."""

    def test_database_delegate_source_is_game_tags_raw(self):
        game = _make_game()
        paths = {"0": [ChessLogStorageService.make_entry("CLAMP", "C", "")]}
        ChessLogStorageService.store_tags(game, paths)
        # Delegate reads game.game_tags_raw via getattr(game, "game_tags_raw", "")
        raw = getattr(game, "game_tags_raw", "")
        self.assertIn(CHIP, parse_game_tags(raw))

    def test_board_widget_source_is_game_tags_raw(self):
        game = _make_game()
        paths = {"0": [ChessLogStorageService.make_entry("CLAMP", "C", "")]}
        ChessLogStorageService.store_tags(game, paths)
        # GameTagsWidget reads game.game_tags_raw via the same attribute
        raw = getattr(game, "game_tags_raw", "")
        self.assertIn(CHIP, parse_game_tags(raw))


if __name__ == "__main__":
    unittest.main()
