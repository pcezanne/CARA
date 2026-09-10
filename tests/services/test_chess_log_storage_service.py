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
    """3x3 moments use cat='Why1'/'Why2'/'Why3'; ordering must be preserved."""

    def test_all_three_whys_round_trip_in_order(self):
        game = make_game()
        entries = [
            ChessLogStorageService.make_entry("3x3", "Why1", "I wanted to attack"),
            ChessLogStorageService.make_entry("3x3", "Why2", "It lost a tempo"),
            ChessLogStorageService.make_entry("3x3", "Why3", "Engine moves centrally"),
        ]
        paths_data = {"0": entries}
        loaded = _store_and_reload(game, paths_data)
        self.assertIn("0", loaded)
        loaded_entries = loaded["0"]
        self.assertEqual(len(loaded_entries), 3)
        self.assertEqual([e["cat"] for e in loaded_entries], ["Why1", "Why2", "Why3"])
        self.assertEqual(loaded_entries[0]["why"], "I wanted to attack")
        self.assertEqual(loaded_entries[1]["why"], "It lost a tempo")
        self.assertEqual(loaded_entries[2]["why"], "Engine moves centrally")

    def test_partial_whys_preserve_order(self):
        """Why1 + Why3 only (Why2 skipped) — order must be Why1 then Why3."""
        game = make_game()
        entries = [
            ChessLogStorageService.make_entry("3x3", "Why1", "First answer"),
            ChessLogStorageService.make_entry("3x3", "Why3", "Third answer"),
        ]
        paths_data = {"0": entries}
        loaded = _store_and_reload(game, paths_data)
        loaded_entries = loaded["0"]
        self.assertEqual([e["cat"] for e in loaded_entries], ["Why1", "Why3"])

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


if __name__ == "__main__":
    unittest.main()
