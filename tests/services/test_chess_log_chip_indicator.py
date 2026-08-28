"""Tests for the 🏷 Chess Log game-level chip indicator.

Covers:
- Chip injected into game_tags_raw at load time when CARAChessLog header present (display-only)
- Chip absent when game has no Chess Log moments
- Chip coexists correctly with existing manual CARAGameTags
- Chip durably written into the real CARAGameTags PGN header by store_tags
- Chip durably removed from the real CARAGameTags PGN header by clear_tags
- "Switch away and back" regression: chip survives a fresh re-read of game.pgn
- Both render paths read game_tags_raw as source of truth
"""

from __future__ import annotations

import io
import unittest

import chess.pgn

from app.models.database_model import GameData
from app.services.chess_log_storage_service import ChessLogStorageService
from app.utils.game_tags_utils import format_game_tags, parse_game_tags


CHIP = ChessLogStorageService.CHIP_TEXT  # "🏷 Chess Log"

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


def _make_game(game_tags_raw: str = "") -> GameData:
    pgn = (
        '[Event "Test"]\n'
        '[Site "?"]\n'
        '[Date "2026.08.28"]\n'
        '[Round "?"]\n'
        '[White "White"]\n'
        '[Black "Black"]\n'
        '[Result "*"]\n'
        '\n1. e4 *\n'
    )
    game = GameData(game_number=1, pgn=pgn, game_tags_raw=game_tags_raw)
    game.game_tags_raw = game_tags_raw
    return game


def _read_tags_from_pgn_header(game: GameData):
    """Re-read game.pgn from scratch and return chip list from CARAGameTags header.

    This simulates what happens when the game is loaded fresh (game switch / reload),
    bypassing any in-memory game_tags_raw cache.
    """
    chess_game = chess.pgn.read_game(io.StringIO(game.pgn))
    raw = chess_game.headers.get("CARAGameTags", "") if chess_game else ""
    return parse_game_tags(raw)


# ---------------------------------------------------------------------------
# Chip injection at load time (pgn_service._extract_game_data — display-only)
# ---------------------------------------------------------------------------

class TestChipInjectionAtLoadTime(unittest.TestCase):
    """_extract_game_data injects chip into the returned dict at parse time.

    This is a display-only read: it reconstructs the chip from CARAChessLog
    header presence without modifying the PGN file. store_tags() is the
    authoritative write path.
    """

    def _extract(self, pgn_text: str) -> dict:
        from app.services.pgn_service import PgnService
        chess_game = chess.pgn.read_game(io.StringIO(pgn_text))
        result = PgnService._extract_game_data(chess_game, pgn_text)
        self.assertIsNotNone(result)
        return result

    def _pgn_with_chess_log(self, override_cara_tags: str = "") -> str:
        """Build a PGN that has CARAChessLog (and optionally an overridden CARAGameTags value)."""
        game = _make_game()
        paths = {"0": [ChessLogStorageService.make_entry("CLAMP", "C", "")]}
        ChessLogStorageService.store_tags(game, paths)
        if override_cara_tags is not None and override_cara_tags != "":
            # Overwrite CARAGameTags to test specific load-time scenarios
            chess_game = chess.pgn.read_game(io.StringIO(game.pgn))
            chess_game.headers["CARAGameTags"] = override_cara_tags
            from app.services.pgn_service import PgnService as PS
            game.pgn = PS.export_game_to_pgn(chess_game)
        return game.pgn

    def test_chip_in_game_tags_raw_when_chess_log_present(self):
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

    def test_chip_alongside_existing_manual_tag_when_cara_tags_overridden(self):
        """If CARAGameTags only has 'Favourite' (chip stripped), load-time injects chip back."""
        pgn = self._pgn_with_chess_log(override_cara_tags="Favourite")
        game_dict = self._extract(pgn)
        tags = parse_game_tags(game_dict.get("game_tags_raw", ""))
        self.assertIn(CHIP, tags)
        self.assertIn("Favourite", tags)
        self.assertEqual(len(tags), 2)

    def test_chip_not_duplicated_if_already_in_cara_game_tags(self):
        """If chip is already in CARAGameTags (normal post-fix case), don't duplicate."""
        pgn = self._pgn_with_chess_log()  # store_tags now writes chip into header
        game_dict = self._extract(pgn)
        tags = parse_game_tags(game_dict.get("game_tags_raw", ""))
        count = sum(1 for t in tags if t.casefold() == CHIP.casefold())
        self.assertEqual(count, 1, f"Expected exactly 1 chip, got: {tags}")


# ---------------------------------------------------------------------------
# Chip durably written into the real PGN header by store_tags
# ---------------------------------------------------------------------------

class TestChipPersistedByStoreTags(unittest.TestCase):
    """The chip must be in the actual CARAGameTags PGN header after store_tags,
    not only in the Python-side game.game_tags_raw attribute."""

    def test_chip_in_real_pgn_header_after_store(self):
        game = _make_game()
        paths = {"0": [ChessLogStorageService.make_entry("CLAMP", "M", "")]}
        ChessLogStorageService.store_tags(game, paths)
        tags = _read_tags_from_pgn_header(game)
        self.assertIn(CHIP, tags, f"Chip not in PGN header: {tags}")

    def test_chip_in_game_tags_raw_after_store(self):
        game = _make_game()
        paths = {"0": [ChessLogStorageService.make_entry("CLAMP", "M", "")]}
        ChessLogStorageService.store_tags(game, paths)
        self.assertIn(CHIP, parse_game_tags(game.game_tags_raw))

    def test_chip_survives_fresh_pgn_reread_switch_away_and_back(self):
        """Regression: chip must persist when game.pgn is re-read from scratch.

        Pre-fix: chip only existed in game.game_tags_raw (Python attr).
        Anything that re-derived tags from game.pgn made the chip disappear.
        """
        game = _make_game()
        paths = {"0": [ChessLogStorageService.make_entry("CLAMP", "M", "")]}
        ChessLogStorageService.store_tags(game, paths)

        # Simulate switching away and back: re-read PGN fresh, ignoring game_tags_raw
        tags_from_pgn = _read_tags_from_pgn_header(game)
        self.assertIn(CHIP, tags_from_pgn,
                      "Chip disappeared after fresh PGN re-read (switch-away-and-back regression)")

    def test_chip_not_duplicated_on_second_store(self):
        game = _make_game()
        paths = {"0": [ChessLogStorageService.make_entry("CLAMP", "C", "")]}
        ChessLogStorageService.store_tags(game, paths)
        ChessLogStorageService.store_tags(game, paths)
        tags = _read_tags_from_pgn_header(game)
        count = sum(1 for t in tags if t.casefold() == CHIP.casefold())
        self.assertEqual(count, 1, f"Chip duplicated in PGN header: {tags}")

    def test_manual_tag_preserved_alongside_chip_in_pgn_header(self):
        # Manual tags must be in the real PGN header to survive store_tags.
        from app.utils.game_tags_utils import apply_cara_game_tags_to_game_data
        game = _make_game()
        apply_cara_game_tags_to_game_data(game, ["Brilliant Move"])
        paths = {"0": [ChessLogStorageService.make_entry("CLAMP", "M", "")]}
        ChessLogStorageService.store_tags(game, paths)
        tags = _read_tags_from_pgn_header(game)
        self.assertIn(CHIP, tags)
        self.assertIn("Brilliant Move", tags)


# ---------------------------------------------------------------------------
# Chip durably removed from the real PGN header by clear_tags
# ---------------------------------------------------------------------------

class TestChipRemovedByClearTags(unittest.TestCase):
    """The chip must be absent from the real CARAGameTags PGN header after clear_tags."""

    def test_chip_absent_from_real_pgn_header_after_clear(self):
        game = _make_game()
        paths = {"0": [ChessLogStorageService.make_entry("CLAMP", "C", "")]}
        ChessLogStorageService.store_tags(game, paths)
        self.assertIn(CHIP, _read_tags_from_pgn_header(game))

        ChessLogStorageService.clear_tags(game)
        tags = _read_tags_from_pgn_header(game)
        self.assertNotIn(CHIP, tags, f"Chip still in PGN header after clear: {tags}")

    def test_chip_absent_from_game_tags_raw_after_clear(self):
        game = _make_game()
        paths = {"0": [ChessLogStorageService.make_entry("CLAMP", "C", "")]}
        ChessLogStorageService.store_tags(game, paths)
        ChessLogStorageService.clear_tags(game)
        self.assertNotIn(CHIP, parse_game_tags(game.game_tags_raw))

    def test_chip_gone_after_fresh_reread_following_clear(self):
        """Chip must not reappear on a fresh PGN re-read after clear."""
        game = _make_game()
        paths = {"0": [ChessLogStorageService.make_entry("CLAMP", "A", "")]}
        ChessLogStorageService.store_tags(game, paths)
        ChessLogStorageService.clear_tags(game)
        tags = _read_tags_from_pgn_header(game)
        self.assertNotIn(CHIP, tags)

    def test_manual_tags_preserved_in_pgn_header_after_clear(self):
        from app.utils.game_tags_utils import apply_cara_game_tags_to_game_data
        game = _make_game()
        apply_cara_game_tags_to_game_data(game, ["Favourite"])
        paths = {"0": [ChessLogStorageService.make_entry("CLAMP", "M", "")]}
        ChessLogStorageService.store_tags(game, paths)
        ChessLogStorageService.clear_tags(game)
        tags = _read_tags_from_pgn_header(game)
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
    After store_tags, that attribute is synced from the now-correct PGN header."""

    def test_delegate_source_game_tags_raw_has_chip_after_store(self):
        game = _make_game()
        paths = {"0": [ChessLogStorageService.make_entry("CLAMP", "C", "")]}
        ChessLogStorageService.store_tags(game, paths)
        raw = getattr(game, "game_tags_raw", "")
        self.assertIn(CHIP, parse_game_tags(raw))

    def test_widget_source_game_tags_raw_has_chip_after_store(self):
        game = _make_game()
        paths = {"0": [ChessLogStorageService.make_entry("CLAMP", "C", "")]}
        ChessLogStorageService.store_tags(game, paths)
        raw = getattr(game, "game_tags_raw", "")
        self.assertIn(CHIP, parse_game_tags(raw))


if __name__ == "__main__":
    unittest.main()
