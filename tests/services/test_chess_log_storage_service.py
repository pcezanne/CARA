"""Unit tests for ChessLogStorageService."""

from __future__ import annotations

import json
import unittest

from app.models.database_model import GameData
from app.services.chess_log_storage_service import ChessLogStorageService
from app.utils.pgn_tag_compression import compress_and_encode_from_str

MINIMAL_PGN = (
    '[Event "Test"]\n'
    '[Site "?"]\n'
    '[Date "2026.08.24"]\n'
    '[Round "?"]\n'
    '[White "White"]\n'
    '[Black "Black"]\n'
    '[Result "*"]\n'
    '\n*\n'
)


def make_game(pgn: str = MINIMAL_PGN) -> GameData:
    return GameData(game_number=1, pgn=pgn)


def _store_and_reload(game: GameData, paths_data: dict) -> dict:
    """Helper: store paths_data, then load back from the same game object."""
    assert ChessLogStorageService.store_tags(game, paths_data)
    return ChessLogStorageService.load_tags(game)


class TestCountTags(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(ChessLogStorageService.count_tags({}), 0)

    def test_three_paths_one_entry_each(self):
        data = {
            "0": [{"id": "a", "preset": "CLAMP", "cat": "M", "why": "", "created": "x"}],
            "0.0": [{"id": "b", "preset": "CLAMP", "cat": "L", "why": "", "created": "x"}],
            "0.0.0": [{"id": "c", "preset": "CLAMP", "cat": "A", "why": "", "created": "x"}],
        }
        self.assertEqual(ChessLogStorageService.count_tags(data), 3)

    def test_one_path_three_entries_counts_as_one(self):
        """CCT moment with three letters = 3 entries under one path = 1 moment."""
        data = {
            "0": [
                {"id": "a", "preset": "CCT", "cat": "C", "why": "", "created": "x"},
                {"id": "b", "preset": "CCT", "cat": "C2", "why": "", "created": "x"},
                {"id": "c", "preset": "CCT", "cat": "T", "why": "", "created": "x"},
            ]
        }
        self.assertEqual(ChessLogStorageService.count_tags(data), 1)

    def test_empty_list_path_not_counted(self):
        """A path key whose list was emptied (residue after deletion) should not count."""
        data = {
            "0": [],
            "0.0": [{"id": "a", "preset": "CLAMP", "cat": "M", "why": "", "created": "x"}],
        }
        self.assertEqual(ChessLogStorageService.count_tags(data), 1)


class TestRoundTrip(unittest.TestCase):
    def test_store_and_load(self):
        game = make_game()
        paths_data = {
            "0": [ChessLogStorageService.make_entry("CLAMP", "M", "test note")],
        }
        loaded = _store_and_reload(game, paths_data)
        self.assertIn("0", loaded)
        entry = loaded["0"][0]
        self.assertEqual(entry["preset"], "CLAMP")
        self.assertEqual(entry["cat"], "M")
        self.assertEqual(entry["why"], "test note")
        self.assertIn("id", entry)
        self.assertIn("created", entry)

    def test_has_flag_set_after_store(self):
        game = make_game()
        ChessLogStorageService.store_tags(game, {
            "0": [ChessLogStorageService.make_entry("CCT", "C")]
        })
        self.assertTrue(game.has_chess_log_tags)

    def test_cct_multiple_entries_same_path(self):
        """Two CCT entries on the same path survive round-trip."""
        game = make_game()
        paths_data = {
            "0.0": [
                ChessLogStorageService.make_entry("CCT", "C", "missed check"),
                ChessLogStorageService.make_entry("CCT", "T", "missed check"),
            ]
        }
        loaded = _store_and_reload(game, paths_data)
        self.assertEqual(len(loaded["0.0"]), 2)
        self.assertEqual(ChessLogStorageService.count_tags(loaded), 1)

    def test_unicode_why_survives(self):
        game = make_game()
        why = "Турнир — кастинг ферзя"
        paths_data = {"0": [ChessLogStorageService.make_entry("custom", "Тест", why)]}
        loaded = _store_and_reload(game, paths_data)
        self.assertEqual(loaded["0"][0]["why"], why)

    def test_empty_paths_round_trip(self):
        game = make_game()
        loaded = _store_and_reload(game, {})
        self.assertEqual(loaded, {})
        self.assertFalse(game.has_chess_log_tags)

    def test_pars_data_keyed_by_path(self):
        """Sideline path key survives round-trip."""
        game = make_game()
        paths_data = {
            "0.1.0": [ChessLogStorageService.make_entry("CLAMP", "C", "variation note")]
        }
        loaded = _store_and_reload(game, paths_data)
        self.assertIn("0.1.0", loaded)


class TestMissingTag(unittest.TestCase):
    def test_missing_tag_returns_empty(self):
        game = make_game()
        result = ChessLogStorageService.load_tags(game)
        self.assertEqual(result, {})
        self.assertFalse(game.has_chess_log_tags)

    def test_has_chess_log_tags_false_when_absent(self):
        game = make_game()
        self.assertFalse(ChessLogStorageService.has_chess_log_tags(game))

    def test_has_chess_log_tags_true_after_store(self):
        game = make_game()
        ChessLogStorageService.store_tags(game, {
            "0": [ChessLogStorageService.make_entry("CLAMP", "P")]
        })
        self.assertTrue(ChessLogStorageService.has_chess_log_tags(game))


class TestChecksumCorruptionRecovery(unittest.TestCase):
    def test_corrupt_checksum_strips_tags_returns_empty(self):
        game = make_game()
        paths_data = {"0": [ChessLogStorageService.make_entry("CLAMP", "L")]}
        ChessLogStorageService.store_tags(game, paths_data)
        # Corrupt the checksum in the PGN text
        game.pgn = game.pgn.replace(
            f'[{ChessLogStorageService.TAG_CHECKSUM} "',
            f'[{ChessLogStorageService.TAG_CHECKSUM} "BAD',
        )
        result = ChessLogStorageService.load_tags(game)
        self.assertEqual(result, {})
        self.assertFalse(game.has_chess_log_tags)
        # Tags should have been stripped
        self.assertFalse(ChessLogStorageService.has_chess_log_tags(game))

    def test_corrupt_payload_strips_tags_returns_empty(self):
        game = make_game()
        paths_data = {"0": [ChessLogStorageService.make_entry("CCT", "C")]}
        ChessLogStorageService.store_tags(game, paths_data)
        # Replace encoded payload with garbage (invalid base64)
        import re
        game.pgn = re.sub(
            rf'\[{ChessLogStorageService.TAG_NAME} "[^"]*"\]',
            f'[{ChessLogStorageService.TAG_NAME} "!!!notbase64!!!"]',
            game.pgn,
        )
        result = ChessLogStorageService.load_tags(game)
        self.assertEqual(result, {})


class TestClearTags(unittest.TestCase):
    def test_clear_removes_tags(self):
        game = make_game()
        ChessLogStorageService.store_tags(game, {
            "0": [ChessLogStorageService.make_entry("CLAMP", "A")]
        })
        self.assertTrue(ChessLogStorageService.has_chess_log_tags(game))
        ChessLogStorageService.clear_tags(game)
        self.assertFalse(ChessLogStorageService.has_chess_log_tags(game))
        self.assertFalse(game.has_chess_log_tags)
        result = ChessLogStorageService.load_tags(game)
        self.assertEqual(result, {})


class TestThreeByThreeRoundTrip(unittest.TestCase):
    """3x3 moments use cat='Why1'/'Why2'/'Why3'/'Why4'; ordering must be preserved."""

    def test_all_four_whys_round_trip_in_order(self):
        game = make_game()
        entries = [
            ChessLogStorageService.make_entry("3x3", "Why1", "I wanted to attack"),
            ChessLogStorageService.make_entry("3x3", "Why2", "It lost a tempo"),
            ChessLogStorageService.make_entry("3x3", "Why3", "Engine moves centrally"),
            ChessLogStorageService.make_entry("3x3", "Why4", "Slow down in future"),
        ]
        paths_data = {"0": entries}
        loaded = _store_and_reload(game, paths_data)
        self.assertIn("0", loaded)
        loaded_entries = loaded["0"]
        self.assertEqual(len(loaded_entries), 4)
        self.assertEqual([e["cat"] for e in loaded_entries], ["Why1", "Why2", "Why3", "Why4"])
        self.assertEqual(loaded_entries[0]["why"], "I wanted to attack")
        self.assertEqual(loaded_entries[1]["why"], "It lost a tempo")
        self.assertEqual(loaded_entries[2]["why"], "Engine moves centrally")
        self.assertEqual(loaded_entries[3]["why"], "Slow down in future")

    def test_partial_whys_preserve_order(self):
        """Why1 + Why3 only (Why2/Why4 skipped) — order must be Why1 then Why3."""
        game = make_game()
        entries = [
            ChessLogStorageService.make_entry("3x3", "Why1", "First answer"),
            ChessLogStorageService.make_entry("3x3", "Why3", "Third answer"),
        ]
        paths_data = {"0": entries}
        loaded = _store_and_reload(game, paths_data)
        loaded_entries = loaded["0"]
        self.assertEqual([e["cat"] for e in loaded_entries], ["Why1", "Why3"])

    def test_why4_only_round_trips(self):
        game = make_game()
        entries = [ChessLogStorageService.make_entry("3x3", "Why4", "Check for pins")]
        paths_data = {"0": entries}
        loaded = _store_and_reload(game, paths_data)
        loaded_entries = loaded["0"]
        self.assertEqual(len(loaded_entries), 1)
        self.assertEqual(loaded_entries[0]["cat"], "Why4")
        self.assertEqual(loaded_entries[0]["why"], "Check for pins")

    def test_threexthree_counts_as_one_moment(self):
        game = make_game()
        entries = [
            ChessLogStorageService.make_entry("3x3", "Why1", "a"),
            ChessLogStorageService.make_entry("3x3", "Why2", "b"),
            ChessLogStorageService.make_entry("3x3", "Why3", "c"),
        ]
        paths_data = {"0": entries}
        loaded = _store_and_reload(game, paths_data)
        self.assertEqual(ChessLogStorageService.count_tags(loaded), 1)

    def test_preset_field_preserved(self):
        game = make_game()
        paths_data = {"0": [ChessLogStorageService.make_entry("3x3", "Why1", "answer")]}
        loaded = _store_and_reload(game, paths_data)
        self.assertEqual(loaded["0"][0]["preset"], "3x3")


class TestMakeEntryIgnoreShallow(unittest.TestCase):
    def test_ignore_shallow_false_omits_field(self):
        entry = ChessLogStorageService.make_entry("CLAMP", "C")
        self.assertNotIn("ignore_shallow", entry)

    def test_ignore_shallow_true_includes_field(self):
        entry = ChessLogStorageService.make_entry("CLAMP", "C", ignore_shallow=True)
        self.assertIn("ignore_shallow", entry)
        self.assertTrue(entry["ignore_shallow"])

    def test_ignore_shallow_roundtrips_through_store_load(self):
        game = make_game()
        entries = [
            ChessLogStorageService.make_entry("CLAMP", "C", "note", ignore_shallow=True),
            ChessLogStorageService.make_entry("CLAMP", "L"),
        ]
        loaded = _store_and_reload(game, {"0": entries})
        shallow_entry = next(e for e in loaded["0"] if e.get("cat") == "C")
        normal_entry = next(e for e in loaded["0"] if e.get("cat") == "L")
        self.assertTrue(shallow_entry.get("ignore_shallow"))
        self.assertNotIn("ignore_shallow", normal_entry)


class TestNoneAndInvalidGame(unittest.TestCase):
    def test_none_game(self):
        self.assertFalse(ChessLogStorageService.has_chess_log_tags(None))
        self.assertEqual(ChessLogStorageService.load_tags(None), {})
        self.assertFalse(ChessLogStorageService.store_tags(None, {}))

    def test_game_with_none_pgn(self):
        game = make_game(pgn=None)
        self.assertFalse(ChessLogStorageService.has_chess_log_tags(game))
        self.assertEqual(ChessLogStorageService.load_tags(game), {})


class TestNagShown(unittest.TestCase):
    def test_store_tags_writes_nag_shown_true(self):
        game = make_game()
        paths_data = {"0": [ChessLogStorageService.make_entry("CLAMP", "M")]}
        ChessLogStorageService.store_tags(game, paths_data, nag_shown=True)
        self.assertTrue(ChessLogStorageService.load_nag_shown(game))

    def test_store_tags_omits_nag_shown_key_when_false(self):
        """nag_shown=False must not write the key at all (backward-compat)."""
        game = make_game()
        paths_data = {"0": [ChessLogStorageService.make_entry("CLAMP", "M")]}
        ChessLogStorageService.store_tags(game, paths_data, nag_shown=False)
        import re
        from app.utils.pgn_tag_compression import decode_and_decompress_to_str
        import chess.pgn
        from io import StringIO
        chess_game = chess.pgn.read_game(StringIO(game.pgn))
        encoded = chess_game.headers[ChessLogStorageService.TAG_NAME]
        payload = json.loads(decode_and_decompress_to_str(encoded))
        self.assertNotIn("nag_shown", payload)

    def test_load_nag_shown_defaults_false_for_missing_tag(self):
        game = make_game()
        self.assertFalse(ChessLogStorageService.load_nag_shown(game))

    def test_load_nag_shown_defaults_false_for_missing_key(self):
        """Payload with only 'paths' (no 'nag_shown') returns False."""
        game = make_game()
        ChessLogStorageService.store_tags(game, {}, nag_shown=False)
        self.assertFalse(ChessLogStorageService.load_nag_shown(game))

    def test_nag_shown_survives_round_trip_with_paths(self):
        """nag_shown=True must coexist with paths round-tripping correctly."""
        game = make_game()
        paths_data = {"0": [ChessLogStorageService.make_entry("CCT", "Threats", "fork")]}
        ChessLogStorageService.store_tags(game, paths_data, nag_shown=True)
        loaded = ChessLogStorageService.load_tags(game)
        self.assertIn("0", loaded)
        self.assertEqual(loaded["0"][0]["cat"], "Threats")
        self.assertTrue(ChessLogStorageService.load_nag_shown(game))

    def test_load_nag_shown_returns_false_for_none_game(self):
        self.assertFalse(ChessLogStorageService.load_nag_shown(None))

    def test_load_nag_shown_returns_false_for_none_pgn(self):
        game = make_game(pgn=None)
        self.assertFalse(ChessLogStorageService.load_nag_shown(game))


class TestRemoveChessLogTagsLogsOnFailure(unittest.TestCase):
    """Phase 7: _remove_chess_log_tags logs a warning on failure instead of silently swallowing."""

    def test_warning_logged_on_cleanup_failure(self):
        from unittest.mock import patch, MagicMock
        import chess.pgn as _pgn_mod
        game = make_game()
        mock_svc = MagicMock()
        with patch(
            "app.services.chess_log_storage_service.LoggingService.get_instance",
            return_value=mock_svc,
        ), patch.object(_pgn_mod, "read_game", side_effect=IOError("disk error")):
            ChessLogStorageService._remove_chess_log_tags(game)
        mock_svc.warning.assert_called_once()
        self.assertIn("Chess Log tag cleanup failed", mock_svc.warning.call_args.args[0])


class TestNoChipInCARAGameTags(unittest.TestCase):
    """After removing chip injection, Chess Log saves must never touch CARAGameTags."""

    def _cara_game_tags(self, game: GameData) -> str:
        import chess.pgn
        from io import StringIO
        g = chess.pgn.read_game(StringIO(game.pgn))
        return g.headers.get("CARAGameTags", "") if g else ""

    def test_store_tags_does_not_add_chip_to_cara_game_tags(self):
        game = make_game()
        paths = {"0": [{"id": "a", "preset": "CLAMP", "cat": "M", "why": "", "created": "x"}]}
        ChessLogStorageService.store_tags(game, paths)
        self.assertNotIn("🏷", self._cara_game_tags(game))

    def test_store_tags_preserves_existing_cara_game_tags_unchanged(self):
        pgn = (
            '[Event "Test"]\n[Site "?"]\n[Date "2026.01.01"]\n'
            '[Round "?"]\n[White "W"]\n[Black "B"]\n[Result "*"]\n'
            '[CARAGameTags "Rapid;London"]\n\n*\n'
        )
        game = make_game(pgn)
        paths = {"0": [{"id": "a", "preset": "CLAMP", "cat": "M", "why": "", "created": "x"}]}
        ChessLogStorageService.store_tags(game, paths)
        self.assertEqual(self._cara_game_tags(game), "Rapid;London")

    def test_load_tags_with_legacy_chip_in_pgn_returns_moments_unchanged(self):
        """Legacy PGN that has 🏷 in CARAGameTags still loads moments correctly."""
        import json, gzip, base64
        paths = {"0": [{"id": "a", "preset": "CLAMP", "cat": "M", "why": "test", "created": "x"}]}
        json_text = json.dumps({"_v": 1, "paths": paths})
        data_bytes = json_text.encode("utf-8")
        encoded = base64.b64encode(gzip.compress(data_bytes, compresslevel=9)).decode("ascii")
        from app.utils.pgn_tag_compression import compute_checksum
        checksum = compute_checksum(data_bytes)
        pgn = (
            '[Event "Test"]\n[Site "?"]\n[Date "2026.01.01"]\n'
            '[Round "?"]\n[White "W"]\n[Black "B"]\n[Result "*"]\n'
            f'[CARAGameTags "🏷;Rapid"]\n'
            f'[CARAChessLog "{encoded}"]\n'
            f'[CARAChessLogChecksum "{checksum}"]\n\n*\n'
        )
        game = make_game(pgn)
        loaded = ChessLogStorageService.load_tags(game)
        self.assertEqual(loaded, paths)


class TestClearTagsPreservesCARAGameTags(unittest.TestCase):
    """clear_tags must not touch CARAGameTags (re-serialises via chess.pgn but only removes the
    three CARAChessLog* headers)."""

    def _cara_game_tags_from_pgn(self, game: GameData) -> str:
        import chess.pgn
        from io import StringIO
        g = chess.pgn.read_game(StringIO(game.pgn))
        return g.headers.get("CARAGameTags", "") if g else ""

    def test_clear_tags_preserves_manual_game_tags(self):
        pgn = (
            '[Event "Test"]\n[Site "?"]\n[Date "2026.01.01"]\n'
            '[Round "?"]\n[White "W"]\n[Black "B"]\n[Result "*"]\n'
            '[CARAGameTags "Favourite;London"]\n\n*\n'
        )
        game = make_game(pgn)
        paths = {"0": [{"id": "a", "preset": "CLAMP", "cat": "M", "why": "", "created": "x"}]}
        ChessLogStorageService.store_tags(game, paths)
        ChessLogStorageService.clear_tags(game)
        self.assertEqual(self._cara_game_tags_from_pgn(game), "Favourite;London")

    def test_clear_tags_no_game_tags_stays_empty(self):
        game = make_game()
        paths = {"0": [{"id": "a", "preset": "CLAMP", "cat": "M", "why": "", "created": "x"}]}
        ChessLogStorageService.store_tags(game, paths)
        ChessLogStorageService.clear_tags(game)
        self.assertEqual(self._cara_game_tags_from_pgn(game), "")


class TestHasChessLogTagsFlag(unittest.TestCase):
    """has_chess_log_tags is True/False at load, after store, and after clear.
    Does not bleed between sibling games.

    _extract_game_data filters out 0-move games, so load-time tests must use a
    PGN that has at least one move.
    """

    # Minimal one-move PGN without any CARA headers.
    ONE_MOVE_PGN = (
        '[Event "Test"]\n[Site "?"]\n[Date "2026.01.01"]\n'
        '[Round "?"]\n[White "W"]\n[Black "B"]\n[Result "*"]\n'
        '\n1. e4 *\n'
    )

    def _extract(self, pgn_text: str) -> dict:
        import chess.pgn
        from io import StringIO
        from app.services.pgn_service import PgnService
        chess_game = chess.pgn.read_game(StringIO(pgn_text))
        result = PgnService._extract_game_data(chess_game, pgn_text)
        self.assertIsNotNone(result, "PGN was filtered out by _extract_game_data (needs at least one move)")
        return result

    def _pgn_with_chess_log(self) -> str:
        """Build a one-move PGN that has a CARAChessLog header."""
        game = make_game(self.ONE_MOVE_PGN)
        paths = {"0": [ChessLogStorageService.make_entry("CLAMP", "C", "")]}
        ChessLogStorageService.store_tags(game, paths)
        return game.pgn

    def test_true_at_load_when_chess_log_header_present(self):
        game_dict = self._extract(self._pgn_with_chess_log())
        self.assertTrue(game_dict.get("has_chess_log_tags", False))

    def test_false_at_load_when_no_chess_log_header(self):
        game_dict = self._extract(self.ONE_MOVE_PGN)
        self.assertFalse(game_dict.get("has_chess_log_tags", False))

    def test_true_after_store_with_moments(self):
        game = make_game()
        paths = {"0": [ChessLogStorageService.make_entry("CLAMP", "M", "")]}
        ChessLogStorageService.store_tags(game, paths)
        self.assertTrue(game.has_chess_log_tags)

    def test_false_after_store_with_empty_paths(self):
        game = make_game()
        ChessLogStorageService.store_tags(game, {})
        self.assertFalse(game.has_chess_log_tags)

    def test_false_after_clear(self):
        game = make_game()
        paths = {"0": [ChessLogStorageService.make_entry("CLAMP", "A", "")]}
        ChessLogStorageService.store_tags(game, paths)
        self.assertTrue(game.has_chess_log_tags)
        ChessLogStorageService.clear_tags(game)
        self.assertFalse(game.has_chess_log_tags)

    def test_no_bleed_between_sibling_games(self):
        """Extracting an untagged game does not affect a tagged game's flag."""
        tagged_dict = self._extract(self._pgn_with_chess_log())
        untagged_dict = self._extract(self.ONE_MOVE_PGN)
        self.assertTrue(tagged_dict.get("has_chess_log_tags", False))
        self.assertFalse(untagged_dict.get("has_chess_log_tags", False))


if __name__ == "__main__":
    unittest.main()
