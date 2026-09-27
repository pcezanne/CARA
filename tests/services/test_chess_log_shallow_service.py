"""Tests for chess_log_shallow_service.classify_notes().

Covers:
- Reply-parse hardening: prose preamble, markdown fences, trailing period,
  mixed case, missing indices, extra indices, duplicate indices.
- Index-decoration tolerance: period/paren/dash/bracket separators, leading
  bullet or word before the index.
- Verdict decoration: bold, backtick, underscore, comma; space-padded bold.
- Negative: prose line containing a digit does NOT parse.
- Empty reply: all indices unparsed, nothing marked shallow.
- Successful partial reply: parsed indices classified correctly, unparsed
  indices returned, no unparsed index ever marked shallow.
- API failure: success=False, all indices unparsed.
- Usage reporting: reported=True when provider includes usage block.
- Usage absent (local provider omits usage): reported=False.
"""

from __future__ import annotations

import unittest
from typing import List, Tuple
from unittest.mock import MagicMock, patch


def _make_notes(
    whys: List[str],
    game_number: int = 1,
    preset: str = "CLAMP",
) -> List[Tuple[int, int, str, str, str]]:
    return [
        (i, game_number, f"path/{i}", preset, why)
        for i, why in enumerate(whys)
    ]


def _mock_anthropic_response(text: str, include_usage: bool = True) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.content = b"x"
    body = {
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
    }
    if include_usage:
        body["usage"] = {"input_tokens": 100, "output_tokens": 50}
    mock.json.return_value = body
    return mock


def _mock_anthropic_error(status: int, message: str) -> MagicMock:
    mock = MagicMock()
    mock.status_code = status
    mock.content = b"x"
    mock.json.return_value = {"error": {"message": message}}
    return mock


class TestClassifyNotesReplyParsing(unittest.TestCase):
    """classify_notes() parses a variety of reply formats correctly."""

    @patch("app.services.ai_service.requests.post")
    def test_clean_reply_classifies_correctly(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        mock_post.return_value = _mock_anthropic_response("0: SHALLOW\n1: DEEP\n2: SHALLOW")
        notes = _make_notes(["note A", "note B", "note C"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, None, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP"), result.shallow_keys)
        self.assertIn((1, "path/2", "CLAMP"), result.shallow_keys)
        self.assertNotIn((1, "path/1", "CLAMP"), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_prose_preamble_skipped(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        reply = (
            "Sure! Here are the classifications:\n\n"
            "0: SHALLOW\n"
            "1: DEEP\n"
        )
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, None, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP"), result.shallow_keys)
        self.assertNotIn((1, "path/1", "CLAMP"), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_markdown_fences_skipped(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        reply = "```\n0: DEEP\n1: SHALLOW\n```"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, None, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertNotIn((1, "path/0", "CLAMP"), result.shallow_keys)
        self.assertIn((1, "path/1", "CLAMP"), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_trailing_period_parsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        # "Shallow." — trailing period stripped before equality check
        reply = "0: Shallow.\n1: DEEP\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, None, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP"), result.shallow_keys)
        self.assertNotIn((1, "path/1", "CLAMP"), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_bold_markdown_parsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        # "**SHALLOW**" — asterisks stripped from both ends
        reply = "0: **SHALLOW**\n1: **DEEP**\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, None, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP"), result.shallow_keys)
        self.assertNotIn((1, "path/1", "CLAMP"), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_backtick_markdown_parsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        reply = "0: `SHALLOW`\n1: `DEEP`\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, None, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP"), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_underscore_markdown_parsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        reply = "0: _SHALLOW_\n1: _DEEP_\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, None, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP"), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_trailing_comma_parsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        reply = "0: SHALLOW,\n1: DEEP;\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, None, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP"), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_space_padded_bold_parsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        # "** SHALLOW **" — inner spaces between * and word; final .strip() in
        # _normalize_verdict handles the residual spaces after stripping *
        reply = "0: ** SHALLOW **\n1: ** DEEP **\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, None, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP"), result.shallow_keys)

    # Index decoration forms --------------------------------------------------

    @patch("app.services.ai_service.requests.post")
    def test_period_separator_parsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        # "1. SHALLOW" — numbered-list style
        reply = "0. DEEP\n1. SHALLOW\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, None, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertNotIn((1, "path/0", "CLAMP"), result.shallow_keys)
        self.assertIn((1, "path/1", "CLAMP"), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_paren_separator_parsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        reply = "0) SHALLOW\n1) DEEP\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, None, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP"), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_leading_dash_parsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        # "- 0: SHALLOW" — bullet list with dash
        reply = "- 0: SHALLOW\n- 1: DEEP\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, None, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP"), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_bracket_decoration_parsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        # "[0] SHALLOW" — bracket-wrapped index, ] is the separator
        reply = "[0] SHALLOW\n[1] DEEP\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, None, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP"), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_prose_digit_not_parsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        # "Here are 3 classifications:" — "3" has a space then "classifications"
        # before the separator ":"; the regex requires the separator to come
        # right after the number (with optional whitespace only), so this line
        # does not match → index 0 stays unparsed.
        reply = "Here are 3 classifications:"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, None, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, (0,))
        self.assertEqual(len(result.shallow_keys), 0)

    @patch("app.services.ai_service.requests.post")
    def test_mixed_case_verdict_accepted(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        reply = "0: shallow\n1: Deep\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, None, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP"), result.shallow_keys)
        self.assertNotIn((1, "path/1", "CLAMP"), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_missing_indices_reported_as_unparsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        # Three notes but reply only covers 0 and 2
        reply = "0: DEEP\n2: SHALLOW\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B", "note C"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, None, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, (1,))
        # Index 1 is NOT marked shallow despite being absent
        self.assertNotIn((1, "path/1", "CLAMP"), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_out_of_range_index_ignored(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        # Reply mentions index 99 which doesn't exist in the notes list
        reply = "0: SHALLOW\n99: SHALLOW\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, None, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP"), result.shallow_keys)
        # No key for index 99 added
        self.assertEqual(len(result.shallow_keys), 1)

    @patch("app.services.ai_service.requests.post")
    def test_duplicate_index_last_verdict_wins(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        # Index 0 appears twice — second verdict (DEEP) replaces first (SHALLOW)
        reply = "0: SHALLOW\n0: DEEP\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, None, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertNotIn((1, "path/0", "CLAMP"), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_extra_text_after_verdict_not_parsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        # "SHALLOW (because it lacks reasoning)" — the extra text after
        # the verdict word makes strip().upper() != "SHALLOW"
        reply = "0: SHALLOW (because it lacks reasoning)\n1: DEEP\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, None, 30)
        self.assertTrue(result.success)
        # Index 0 is unparsed (extra text), index 1 is parsed as DEEP
        self.assertIn(0, result.unparsed_indices)
        self.assertNotIn((1, "path/0", "CLAMP"), result.shallow_keys)


class TestClassifyNotesEmptyReply(unittest.TestCase):
    """An empty or whitespace-only reply marks all indices as unparsed."""

    @patch("app.services.ai_service.requests.post")
    def test_empty_reply_all_unparsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        # AIService treats empty content as a failure — success=False, all unparsed
        mock_post.return_value = _mock_anthropic_response("")
        notes = _make_notes(["note A", "note B", "note C"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, None, 30)
        self.assertFalse(result.success)
        self.assertEqual(result.unparsed_indices, (0, 1, 2))
        self.assertEqual(len(result.shallow_keys), 0)

    @patch("app.services.ai_service.requests.post")
    def test_whitespace_only_reply_all_unparsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        mock_post.return_value = _mock_anthropic_response("   \n\n  \n")
        notes = _make_notes(["note A"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, None, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, (0,))
        self.assertEqual(len(result.shallow_keys), 0)


class TestClassifyNotesApiFailure(unittest.TestCase):
    """API errors produce success=False and all indices in unparsed_indices."""

    @patch("app.services.ai_service.requests.post")
    def test_api_error_success_false(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        mock_post.return_value = _mock_anthropic_error(500, "Internal Server Error")
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, None, 30)
        self.assertFalse(result.success)
        self.assertEqual(len(result.shallow_keys), 0)
        self.assertEqual(result.unparsed_indices, (0, 1))
        self.assertIsNotNone(result.error)

    @patch("app.services.ai_service.requests.post")
    def test_network_error_success_false(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        import requests as req_lib
        mock_post.side_effect = req_lib.exceptions.ConnectionError("connection refused")
        notes = _make_notes(["note A"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, None, 30)
        self.assertFalse(result.success)
        self.assertEqual(result.unparsed_indices, (0,))
        self.assertEqual(len(result.shallow_keys), 0)


class TestClassifyNotesUsageReporting(unittest.TestCase):
    """Usage is extracted when present and marked not-reported when absent."""

    @patch("app.services.ai_service.requests.post")
    def test_usage_reported_true_when_present(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        mock_post.return_value = _mock_anthropic_response("0: DEEP", include_usage=True)
        notes = _make_notes(["note A"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, None, 30)
        self.assertTrue(result.success)
        self.assertIsNotNone(result.usage)
        self.assertTrue(result.usage.reported)
        self.assertEqual(result.usage.input_tokens, 100)
        self.assertEqual(result.usage.output_tokens, 50)

    @patch("app.services.ai_service.requests.post")
    def test_usage_reported_false_when_absent(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        mock_post.return_value = _mock_anthropic_response("0: SHALLOW", include_usage=False)
        notes = _make_notes(["note A"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, None, 30)
        self.assertTrue(result.success)
        self.assertIsNotNone(result.usage)
        self.assertFalse(result.usage.reported)
        # unparsed count is still correct when usage is missing
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP"), result.shallow_keys)


class TestClassifyNotesThinkingDisabled(unittest.TestCase):
    """disable_thinking_for() is applied; Fable-family models get None."""

    @patch("app.services.ai_service.requests.post")
    def test_sonnet_5_sends_thinking_disabled(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        mock_post.return_value = _mock_anthropic_response("0: DEEP")
        notes = _make_notes(["note A"])
        classify_notes(notes, "anthropic", "claude-sonnet-5-20251101", "sk-test", None, None, 30)
        _, kwargs = mock_post.call_args
        payload = kwargs.get("json") or {}
        self.assertEqual(payload.get("thinking"), {"type": "disabled"})

    @patch("app.services.ai_service.requests.post")
    def test_fable_5_no_thinking_param(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        mock_post.return_value = _mock_anthropic_response("0: DEEP")
        notes = _make_notes(["note A"])
        classify_notes(notes, "anthropic", "claude-fable-5-1", "sk-test", None, None, 30)
        _, kwargs = mock_post.call_args
        payload = kwargs.get("json") or {}
        self.assertNotIn("thinking", payload)


if __name__ == "__main__":
    unittest.main()
