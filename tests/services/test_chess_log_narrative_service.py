"""Tests for chess_log_narrative_service.

Monkeypatches AIService.send_message to capture the prompt that was assembled
and to return controlled responses without making live API calls.

Assertions focus on prompt *content* — that the required pieces are present —
and on response *parsing* — that narrative / shallow-flag splitting is correct.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.models.database_model import GameData
from app.services.chess_log_storage_service import ChessLogStorageService
from app.services.chess_log_narrative_service import (
    build_prompt,
    generate_narrative,
    _parse_response,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_game(
    white: str = "Alice",
    black: str = "Bob",
    date: str = "2025.06.01",
    entries_per_path: dict | None = None,
    notes: str = "",
) -> GameData:
    pgn = (
        f'[Event "Test"]\n'
        f'[Site "?"]\n'
        f'[Date "{date}"]\n'
        f'[Round "?"]\n'
        f'[White "{white}"]\n'
        f'[Black "{black}"]\n'
        f'[Result "*"]\n'
        f'\n1. e4 *\n'
    )
    game = GameData(game_number=1, pgn=pgn, white=white, black=black, date=date)
    if entries_per_path:
        ChessLogStorageService.store_tags(game, entries_per_path)
    if notes:
        from app.services.notes_storage_service import NotesStorageService
        NotesStorageService.store_notes(game, notes)
    return game


def _clamp(cat: str, why: str = "") -> dict:
    return ChessLogStorageService.make_entry("CLAMP", cat, why)


def _cct(cat: str, why: str = "") -> dict:
    return ChessLogStorageService.make_entry("CCT", cat, why)


# ---------------------------------------------------------------------------
# build_prompt
# ---------------------------------------------------------------------------

class TestBuildPromptCategoryCounts(unittest.TestCase):

    def test_category_count_in_prompt(self):
        game = _make_game(entries_per_path={
            "0": [_clamp("C"), _clamp("L"), _clamp("C")],
        })
        prompt = build_prompt([game])
        self.assertIn("CLAMP", prompt)
        self.assertIn("C:", prompt)
        self.assertIn("L:", prompt)

    def test_uncategorized_labelled_in_prompt(self):
        game = _make_game(entries_per_path={"0": [_clamp("")]})
        prompt = build_prompt([game])
        self.assertIn("uncategorized", prompt.lower())

    def test_multiple_presets_both_in_prompt(self):
        game = _make_game(entries_per_path={
            "0": [_clamp("M")],
            "0.0": [_cct("Checks")],
        })
        prompt = build_prompt([game])
        self.assertIn("CLAMP", prompt)
        self.assertIn("CCT", prompt)

    def test_no_moments_produces_no_moments_placeholder(self):
        game = _make_game()  # no tags
        prompt = build_prompt([game])
        self.assertIn("no moments tagged", prompt)


class TestBuildPromptWhyNotes(unittest.TestCase):

    def test_why_note_present_in_prompt(self):
        game = _make_game(entries_per_path={
            "0": [_clamp("C", "I rushed without checking the whole board")],
        })
        prompt = build_prompt([game])
        self.assertIn("rushed without checking", prompt)

    def test_empty_why_not_in_prompt(self):
        game = _make_game(entries_per_path={"0": [_clamp("C", "")]})
        prompt = build_prompt([game])
        self.assertNotIn("C/uncategorized", prompt)
        # No why-notes section body (only the placeholder)
        self.assertIn("no notes written", prompt)

    def test_why_note_label_includes_preset_and_cat(self):
        game = _make_game(entries_per_path={
            "0": [_clamp("L", "I miscounted the tempo")],
        })
        prompt = build_prompt([game])
        self.assertIn("CLAMP/L", prompt)


class TestBuildPromptGameNotes(unittest.TestCase):

    def test_game_note_present_in_prompt(self):
        game = _make_game(notes="Played aggressively but missed the counterplay.")
        prompt = build_prompt([game])
        self.assertIn("aggressively", prompt)

    def test_no_game_notes_shows_placeholder(self):
        game = _make_game()
        prompt = build_prompt([game])
        self.assertIn("no whole-game notes", prompt)


class TestBuildPromptPlayerFilter(unittest.TestCase):

    def test_player_filter_excludes_unrelated_games(self):
        g1 = _make_game(white="Alice", black="Bob",
                        entries_per_path={"0": [_clamp("C", "note from alice")]})
        g2 = _make_game(white="Carlos", black="Dave",
                        entries_per_path={"0": [_clamp("L", "note from carlos")]})
        prompt = build_prompt([g1, g2], player="Alice")
        self.assertIn("note from alice", prompt)
        self.assertNotIn("note from carlos", prompt)

    def test_empty_player_includes_all(self):
        g1 = _make_game(white="Alice", black="Bob",
                        entries_per_path={"0": [_clamp("C", "alice note")]})
        g2 = _make_game(white="Carlos", black="Dave",
                        entries_per_path={"0": [_clamp("L", "carlos note")]})
        prompt = build_prompt([g1, g2], player="")
        self.assertIn("alice note", prompt)
        self.assertIn("carlos note", prompt)


class TestBuildPromptShallowFlagInstruction(unittest.TestCase):

    def test_shallow_flag_instruction_present(self):
        game = _make_game(entries_per_path={"0": [_clamp("C")]})
        prompt = build_prompt([game])
        self.assertIn("shallow", prompt.lower())
        self.assertIn("Also flagged", prompt)

    def test_include_also_flagged_false_omits_step2(self):
        game = _make_game(entries_per_path={"0": [_clamp("C")]})
        prompt = build_prompt([game], include_also_flagged=False)
        self.assertNotIn("Also flagged", prompt)
        self.assertNotIn("shallow", prompt.lower())

    def test_include_also_flagged_false_still_has_narrative_step(self):
        game = _make_game(entries_per_path={"0": [_clamp("C")]})
        prompt = build_prompt([game], include_also_flagged=False)
        self.assertIn("Narrative summary", prompt)

    def test_include_also_flagged_true_is_default(self):
        game = _make_game(entries_per_path={"0": [_clamp("C")]})
        prompt_default = build_prompt([game])
        prompt_explicit = build_prompt([game], include_also_flagged=True)
        self.assertEqual(prompt_default, prompt_explicit)


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------

class TestParseResponse(unittest.TestCase):

    def test_no_sentinel_returns_full_response_and_empty_flags(self):
        narrative, flags = _parse_response("Great reflection on your games.")
        self.assertEqual(narrative, "Great reflection on your games.")
        self.assertEqual(flags, [])

    def test_sentinel_splits_narrative_and_flags(self):
        response = (
            "You show progress in calculation.\n\n"
            "## Also flagged\n"
            "- 'I blundered' under Blunder: restates the category\n"
            "- 'Made a mistake' under Mistake: same\n"
        )
        narrative, flags = _parse_response(response)
        self.assertIn("progress in calculation", narrative)
        self.assertEqual(len(flags), 2)
        self.assertIn("restates the category", flags[0])

    def test_sentinel_case_insensitive(self):
        response = "Good work.\n\n## ALSO FLAGGED\n- shallow note here\n"
        narrative, flags = _parse_response(response)
        self.assertIn("Good work", narrative)
        self.assertEqual(len(flags), 1)

    def test_empty_flagged_section_returns_no_flags(self):
        response = "Solid work.\n\n## Also flagged\n"
        _, flags = _parse_response(response)
        self.assertEqual(flags, [])

    def test_bullet_styles_star_and_dash(self):
        response = "Narrative.\n\n## Also flagged\n- dash item\n* star item\n"
        _, flags = _parse_response(response)
        self.assertEqual(len(flags), 2)


# ---------------------------------------------------------------------------
# generate_narrative (integration through monkeypatch)
# ---------------------------------------------------------------------------

class TestGenerateNarrative(unittest.TestCase):

    def _game_with_clamp(self) -> GameData:
        return _make_game(entries_per_path={
            "0": [_clamp("C", "I blundered a piece because I stopped calculating")],
            "0.0": [_clamp("L", "I rushed a pawn push")],
        })

    @patch("app.services.chess_log_narrative_service.AIService")
    def test_success_returns_narrative_and_flags(self, MockAIService):
        response_text = (
            "You have been logging Calculation mistakes frequently.\n\n"
            "## Also flagged\n"
            "- 'I blundered a piece': partially restates the category\n"
        )
        mock_service = MagicMock()
        mock_service.send_message.return_value = (True, response_text)
        MockAIService.return_value = mock_service

        success, narrative, flags = generate_narrative(
            games=[self._game_with_clamp()],
            provider="openai",
            model="gpt-4o",
            api_key="sk-test",
            base_url_override=None,
        )

        self.assertTrue(success)
        self.assertIn("Calculation", narrative)
        self.assertEqual(len(flags), 1)

    @patch("app.services.chess_log_narrative_service.AIService")
    def test_api_failure_returns_false(self, MockAIService):
        mock_service = MagicMock()
        mock_service.send_message.return_value = (False, "Connection error")
        MockAIService.return_value = mock_service

        success, message, flags = generate_narrative(
            games=[self._game_with_clamp()],
            provider="openai",
            model="gpt-4o",
            api_key="sk-test",
            base_url_override=None,
        )

        self.assertFalse(success)
        self.assertIn("Connection error", message)
        self.assertEqual(flags, [])

    @patch("app.services.chess_log_narrative_service.AIService")
    def test_prompt_sent_contains_why_note(self, MockAIService):
        mock_service = MagicMock()
        mock_service.send_message.return_value = (True, "Solid work.")
        MockAIService.return_value = mock_service

        generate_narrative(
            games=[self._game_with_clamp()],
            provider="openai",
            model="gpt-4o",
            api_key="sk-test",
            base_url_override=None,
        )

        call_args = mock_service.send_message.call_args
        messages = call_args[1].get("messages") or call_args[0][3]
        user_message = next(m["content"] for m in messages if m["role"] == "user")
        self.assertIn("stopped calculating", user_message)

    @patch("app.services.chess_log_narrative_service.AIService")
    def test_system_prompt_included(self, MockAIService):
        mock_service = MagicMock()
        mock_service.send_message.return_value = (True, "Good.")
        MockAIService.return_value = mock_service

        generate_narrative(
            games=[self._game_with_clamp()],
            provider="openai",
            model="gpt-4o",
            api_key="sk-test",
            base_url_override=None,
        )

        call_args = mock_service.send_message.call_args
        system_prompt = call_args[1].get("system_prompt")
        self.assertIsNotNone(system_prompt)
        self.assertTrue(len(system_prompt) > 0)

    @patch("app.services.chess_log_narrative_service.AIService")
    def test_custom_provider_passes_base_url(self, MockAIService):
        mock_service = MagicMock()
        mock_service.send_message.return_value = (True, "OK.")
        MockAIService.return_value = mock_service

        generate_narrative(
            games=[self._game_with_clamp()],
            provider="custom",
            model="llama3",
            api_key="",
            base_url_override="http://localhost:11434",
        )

        call_args = mock_service.send_message.call_args
        base_url = call_args[1].get("base_url_override")
        self.assertEqual(base_url, "http://localhost:11434")

    def test_no_games_returns_false(self):
        success, message, flags = generate_narrative(
            games=[],
            provider="openai",
            model="gpt-4o",
            api_key="sk-test",
            base_url_override=None,
        )
        self.assertFalse(success)
        self.assertIn("No Chess Log data", message)
        self.assertEqual(flags, [])

    @patch("app.services.chess_log_narrative_service.AIService")
    def test_timeout_passed_to_send_message(self, MockAIService):
        mock_service = MagicMock()
        mock_service.send_message.return_value = (True, "Good work.")
        MockAIService.return_value = mock_service

        generate_narrative(
            games=[self._game_with_clamp()],
            provider="openai",
            model="gpt-4o",
            api_key="sk-test",
            base_url_override=None,
            timeout_seconds=120,
        )

        call_kwargs = mock_service.send_message.call_args[1]
        self.assertEqual(call_kwargs.get("timeout_seconds"), 120)

    @patch("app.services.chess_log_narrative_service.AIService")
    def test_token_limit_passed_to_send_message(self, MockAIService):
        mock_service = MagicMock()
        mock_service.send_message.return_value = (True, "Good work.")
        MockAIService.return_value = mock_service

        generate_narrative(
            games=[self._game_with_clamp()],
            provider="openai",
            model="gpt-4o",
            api_key="sk-test",
            base_url_override=None,
            token_limit=4000,
        )

        call_kwargs = mock_service.send_message.call_args[1]
        self.assertEqual(call_kwargs.get("token_limit"), 4000)

    @patch("app.services.chess_log_narrative_service.AIService")
    def test_include_also_flagged_false_omits_step2_in_sent_prompt(self, MockAIService):
        mock_service = MagicMock()
        mock_service.send_message.return_value = (True, "Solid work.")
        MockAIService.return_value = mock_service

        generate_narrative(
            games=[self._game_with_clamp()],
            provider="openai",
            model="gpt-4o",
            api_key="sk-test",
            base_url_override=None,
            include_also_flagged=False,
        )

        call_args = mock_service.send_message.call_args
        messages = call_args[1].get("messages") or call_args[0][3]
        user_message = next(m["content"] for m in messages if m["role"] == "user")
        self.assertNotIn("Also flagged", user_message)
        self.assertNotIn("shallow", user_message.lower())


if __name__ == "__main__":
    unittest.main()
