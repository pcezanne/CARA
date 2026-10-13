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

import json as _json
import unittest
from typing import List, Tuple
from unittest.mock import MagicMock, patch

from app.services.chess_log_shallow_service import classify_notes
from app.utils.path_resolver import get_app_resource_path as _get_resource_path

with open(_get_resource_path("app/config/config.json"), "r", encoding="utf-8") as _f:
    _CONFIG = _json.load(_f)


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
    # Use side_effect so each call returns a fresh dict — the AIService debug path
    # does a shallow copy and then mutates item["text"] in place; a shared
    # return_value dict would be corrupted on the second json() call.
    def _make_body():
        body = {
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
        }
        if include_usage:
            body["usage"] = {"input_tokens": 100, "output_tokens": 50}
        return body
    mock.json.side_effect = _make_body
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
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP", ""), result.shallow_keys)
        self.assertIn((1, "path/2", "CLAMP", ""), result.shallow_keys)
        self.assertNotIn((1, "path/1", "CLAMP", ""), result.shallow_keys)

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
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP", ""), result.shallow_keys)
        self.assertNotIn((1, "path/1", "CLAMP", ""), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_markdown_fences_skipped(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        reply = "```\n0: DEEP\n1: SHALLOW\n```"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertNotIn((1, "path/0", "CLAMP", ""), result.shallow_keys)
        self.assertIn((1, "path/1", "CLAMP", ""), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_trailing_period_parsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        # "Shallow." — trailing period stripped before equality check
        reply = "0: Shallow.\n1: DEEP\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP", ""), result.shallow_keys)
        self.assertNotIn((1, "path/1", "CLAMP", ""), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_bold_markdown_parsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        # "**SHALLOW**" — asterisks stripped from both ends
        reply = "0: **SHALLOW**\n1: **DEEP**\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP", ""), result.shallow_keys)
        self.assertNotIn((1, "path/1", "CLAMP", ""), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_backtick_markdown_parsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        reply = "0: `SHALLOW`\n1: `DEEP`\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP", ""), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_underscore_markdown_parsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        reply = "0: _SHALLOW_\n1: _DEEP_\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP", ""), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_trailing_comma_parsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        reply = "0: SHALLOW,\n1: DEEP;\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP", ""), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_space_padded_bold_parsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        # "** SHALLOW **" — inner spaces between * and word; final .strip() in
        # _normalize_verdict handles the residual spaces after stripping *
        reply = "0: ** SHALLOW **\n1: ** DEEP **\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP", ""), result.shallow_keys)

    # Index decoration forms --------------------------------------------------

    @patch("app.services.ai_service.requests.post")
    def test_period_separator_parsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        # "1. SHALLOW" — numbered-list style
        reply = "0. DEEP\n1. SHALLOW\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertNotIn((1, "path/0", "CLAMP", ""), result.shallow_keys)
        self.assertIn((1, "path/1", "CLAMP", ""), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_paren_separator_parsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        reply = "0) SHALLOW\n1) DEEP\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP", ""), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_leading_dash_parsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        # "- 0: SHALLOW" — bullet list with dash
        reply = "- 0: SHALLOW\n- 1: DEEP\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP", ""), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_bracket_decoration_parsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        # "[0] SHALLOW" — bracket-wrapped index, ] is the separator
        reply = "[0] SHALLOW\n[1] DEEP\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP", ""), result.shallow_keys)

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
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, (0,))
        self.assertEqual(len(result.shallow_keys), 0)

    @patch("app.services.ai_service.requests.post")
    def test_mixed_case_verdict_accepted(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        reply = "0: shallow\n1: Deep\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP", ""), result.shallow_keys)
        self.assertNotIn((1, "path/1", "CLAMP", ""), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_missing_indices_reported_as_unparsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        # Three notes but reply only covers 0 and 2
        reply = "0: DEEP\n2: SHALLOW\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B", "note C"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, (1,))
        # Index 1 is NOT marked shallow despite being absent
        self.assertNotIn((1, "path/1", "CLAMP", ""), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_out_of_range_index_ignored(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        # Reply mentions index 99 which doesn't exist in the notes list
        reply = "0: SHALLOW\n99: SHALLOW\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP", ""), result.shallow_keys)
        # No key for index 99 added
        self.assertEqual(len(result.shallow_keys), 1)

    @patch("app.services.ai_service.requests.post")
    def test_duplicate_index_last_verdict_wins(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        # Index 0 appears twice — second verdict (DEEP) replaces first (SHALLOW)
        reply = "0: SHALLOW\n0: DEEP\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertNotIn((1, "path/0", "CLAMP", ""), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_extra_text_after_verdict_not_parsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        # "SHALLOW (because it lacks reasoning)" — the extra text after
        # the verdict word makes strip().upper() != "SHALLOW"
        reply = "0: SHALLOW (because it lacks reasoning)\n1: DEEP\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        # Index 0 is unparsed (extra text), index 1 is parsed as DEEP
        self.assertIn(0, result.unparsed_indices)
        self.assertNotIn((1, "path/0", "CLAMP", ""), result.shallow_keys)


class TestClassifyNotesEmptyReply(unittest.TestCase):
    """An empty or whitespace-only reply marks all indices as unparsed."""

    @patch("app.services.ai_service.requests.post")
    def test_empty_reply_all_unparsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        # AIService treats empty content as a failure — success=False, all unparsed
        mock_post.return_value = _mock_anthropic_response("")
        notes = _make_notes(["note A", "note B", "note C"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertFalse(result.success)
        self.assertEqual(result.unparsed_indices, (0, 1, 2))
        self.assertEqual(len(result.shallow_keys), 0)

    @patch("app.services.ai_service.requests.post")
    def test_whitespace_only_reply_all_unparsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        # anthropic_message_text strips whitespace-only to "" — treated as empty, same as test_empty_reply
        mock_post.return_value = _mock_anthropic_response("   \n\n  \n")
        notes = _make_notes(["note A"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertFalse(result.success)
        self.assertEqual(result.unparsed_indices, (0,))
        self.assertEqual(len(result.shallow_keys), 0)


class TestClassifyNotesApiFailure(unittest.TestCase):
    """API errors produce success=False and all indices in unparsed_indices."""

    @patch("app.services.ai_service.requests.post")
    def test_api_error_success_false(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        mock_post.return_value = _mock_anthropic_error(500, "Internal Server Error")
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
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
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
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
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
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
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertIsNotNone(result.usage)
        self.assertFalse(result.usage.reported)
        # unparsed count is still correct when usage is missing
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP", ""), result.shallow_keys)


class TestClassifyNotesThinkingDisabled(unittest.TestCase):
    """disable_thinking_for() is applied; Fable-family models get None."""

    @patch("app.services.ai_service.requests.post")
    def test_sonnet_5_sends_thinking_disabled(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        mock_post.return_value = _mock_anthropic_response("0: DEEP")
        notes = _make_notes(["note A"])
        classify_notes(notes, "anthropic", "claude-sonnet-5-20251101", "sk-test", None, _CONFIG, 30)
        _, kwargs = mock_post.call_args
        payload = kwargs.get("json") or {}
        self.assertEqual(payload.get("thinking"), {"type": "disabled"})

    @patch("app.services.ai_service.requests.post")
    def test_fable_5_no_thinking_param(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        mock_post.return_value = _mock_anthropic_response("0: DEEP")
        notes = _make_notes(["note A"])
        classify_notes(notes, "anthropic", "claude-fable-5-1", "sk-test", None, _CONFIG, 30)
        _, kwargs = mock_post.call_args
        payload = kwargs.get("json") or {}
        self.assertNotIn("thinking", payload)


class TestClassifyNotesMissingConfig(unittest.TestCase):

    def test_empty_config_returns_failure(self):
        from app.services.chess_log_shallow_service import classify_notes
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, {}, 30)
        self.assertFalse(result.success)
        self.assertIn("config.json", result.error)
        self.assertEqual(len(result.shallow_keys), 0)

    def test_none_config_returns_failure(self):
        from app.services.chess_log_shallow_service import classify_notes
        notes = _make_notes(["note A"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, None, 30)
        self.assertFalse(result.success)
        self.assertIn("config.json", result.error)
        self.assertEqual(len(result.shallow_keys), 0)


class TestClassifyNotesParserRobustness(unittest.TestCase):
    """Hardened parser handles glued blocks, markdown tables, prose rejection."""

    @patch("app.services.ai_service.requests.post")
    def test_parse_handles_text_blocks_glued_without_separator(self, mock_post):
        """Simulated ''.join of two text blocks produces no missing indices."""
        # "0: SHALLOW\n1: DEEP2: SHALLOW\n3: DEEP" — blocks glued at idx 2
        reply = "0: SHALLOW\n1: DEEP2: SHALLOW\n3: DEEP"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["a", "b", "c", "d"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        shallow_idxs = {n[1] for n in result.shallow_keys}
        self.assertIn("path/0", shallow_idxs)
        self.assertNotIn("path/1", shallow_idxs)
        self.assertIn("path/2", shallow_idxs)
        self.assertNotIn("path/3", shallow_idxs)

    @patch("app.services.ai_service.requests.post")
    def test_parse_tolerates_cut_off_trailer(self, mock_post):
        """The 'Response was cut off' trailer appended by ai_service doesn't create spurious indices."""
        trailer = "\n\n[Response was cut off — the model reached the output token limit. Try increasing the Tokens limit in the narrative controls.]"
        reply = "0: SHALLOW\n1: DEEP\n2: SHALLOW" + trailer
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["a", "b", "c"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())

    @patch("app.services.ai_service.requests.post")
    def test_parse_markdown_table_reply(self, mock_post):
        """Markdown-table verdicts (| 0 | SHALLOW |) parse correctly."""
        reply = "| 0 | SHALLOW |\n| 1 | DEEP |"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["a", "b"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn("path/0", {n[1] for n in result.shallow_keys})

    @patch("app.services.ai_service.requests.post")
    def test_parse_rejects_prose_with_matching_digit(self, mock_post):
        """Prose containing a digit and a separator but no SHALLOW/DEEP stays unparsed."""
        reply = "Here are 3 classifications:"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A"])
        # Note: index 3 is not in range anyway, but the key check is that the
        # SHALLOW/DEEP gate blocks the match.
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, (0,))
        self.assertEqual(len(result.shallow_keys), 0)

    @patch("app.services.ai_service.requests.post")
    def test_parse_rejects_verdict_mention_in_prose_sentence(self, mock_post):
        """A verdict embedded in mid-sentence prose is not guessed as an index verdict."""
        # "13. Re1: DEEP would have been better" — starts with digit+sep but
        # "Re1:" interrupts before SHALLOW/DEEP in the new anchored regex.
        # The real list at the bottom must win and index 13 must stay unparsed.
        reply = (
            "Looking at move 13. Re1: DEEP would have been better in this position.\n"
            "Here are the classifications:\n\n"
            "0: SHALLOW\n"
            "1: DEEP\n"
        )
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["a"] * 20)
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertNotIn(0, result.unparsed_indices)
        self.assertNotIn(1, result.unparsed_indices)
        self.assertIn(13, result.unparsed_indices)
        self.assertIn("path/0", {n[1] for n in result.shallow_keys})

    @patch("app.services.ai_service.requests.post")
    def test_parse_handles_markdown_decoration_around_verdict(self, mock_post):
        reply = "0: **SHALLOW**\n1: `DEEP`\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["a", "b"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())

    @patch("app.services.ai_service.requests.post")
    def test_parse_last_occurrence_wins_on_duplicate_index(self, mock_post):
        """When an index appears twice, the last verdict wins (model reconsidered)."""
        reply = "0: SHALLOW\n0: DEEP\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["a"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertNotIn((1, "path/0", "CLAMP", ""), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_parse_rejects_trailing_prose_after_verdict(self, mock_post):
        """Verdict followed by prose (not just decoration) stays unparsed."""
        reply = "0: DEEP play by White\n1: SHALLOW\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["a", "b"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertIn(0, result.unparsed_indices)
        self.assertNotIn(1, result.unparsed_indices)


class TestClassifyNotesDiagnosticLogging(unittest.TestCase):
    """Warning/debug logging fires on parse failure with full metadata."""

    @patch("app.services.ai_service.requests.post")
    def test_all_fail_logs_error_with_full_metadata(self, mock_post):
        """All notes unparsed → LoggingService.error called with reply, model, stop_reason,
        max_tokens, input/output token counts, block_count, block_types."""
        from app.services.chess_log_shallow_service import classify_notes
        mock_post.return_value = _mock_anthropic_response("no verdicts here at all")
        notes = _make_notes(["a", "b"])
        mock_logger = MagicMock()
        with patch(
            "app.services.chess_log_shallow_service.LoggingService.get_instance",
            return_value=mock_logger,
        ):
            result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertEqual(len(result.unparsed_indices), 2)
        mock_logger.error.assert_called_once()
        mock_logger.warning.assert_not_called()
        log_msg = mock_logger.error.call_args.args[0]
        self.assertIn("no verdicts here at all", log_msg)
        self.assertIn("claude-sonnet-4-6", log_msg)
        self.assertIn("stop_reason", log_msg)
        self.assertIn("max_tokens", log_msg)
        self.assertIn("input_tokens", log_msg)
        self.assertIn("output_tokens", log_msg)
        self.assertIn("block_count", log_msg)
        self.assertIn("block_types", log_msg)

    @patch("app.services.ai_service.requests.post")
    def test_log_message_contains_no_api_key_substring(self, mock_post):
        """The API key must never appear in the log message."""
        from app.services.chess_log_shallow_service import classify_notes
        sentinel_key = "sk-TESTKEY-SHOULDNOTAPPEAR"
        mock_post.return_value = _mock_anthropic_response("no verdicts here")
        notes = _make_notes(["a"])
        mock_logger = MagicMock()
        with patch(
            "app.services.chess_log_shallow_service.LoggingService.get_instance",
            return_value=mock_logger,
        ):
            classify_notes(notes, "anthropic", "claude-sonnet-4-6", sentinel_key, None, _CONFIG, 30)
        mock_logger.error.assert_called_once()
        log_msg = mock_logger.error.call_args.args[0]
        self.assertNotIn(sentinel_key, log_msg)

    @patch("app.services.ai_service.requests.post")
    def test_partial_fail_logs_debug_not_warning(self, mock_post):
        """Partial failure (some parsed) → .debug called, not .warning."""
        from app.services.chess_log_shallow_service import classify_notes
        # Index 0 parses, index 1 doesn't
        reply = "0: SHALLOW\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["a", "b"])
        mock_logger = MagicMock()
        with patch(
            "app.services.chess_log_shallow_service.LoggingService.get_instance",
            return_value=mock_logger,
        ):
            result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertEqual(result.unparsed_indices, (1,))
        # The dispatch DEBUG log fires first, then the parse-result DEBUG log
        self.assertGreaterEqual(mock_logger.debug.call_count, 1)
        mock_logger.warning.assert_not_called()
        # The parse-result debug message must mention the partial-fail context
        debug_calls = [str(c) for c in mock_logger.debug.call_args_list]
        self.assertTrue(any("parsed" in msg for msg in debug_calls))


class TestClassifyNotesTokenBudget(unittest.TestCase):
    """classify_notes passes a sized token_limit proportional to note count."""

    @patch("app.services.ai_service.requests.post")
    def test_classify_notes_sends_sized_token_limit(self, mock_post):
        """50 notes → token_limit = max(2000, 50*60+500) = 3500."""
        from app.services.chess_log_shallow_service import classify_notes
        replies = "\n".join(f"{i}: DEEP" for i in range(50))
        mock_post.return_value = _mock_anthropic_response(replies)
        notes = _make_notes(["note"] * 50)
        classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        _, kwargs = mock_post.call_args
        payload = kwargs.get("json") or {}
        self.assertEqual(payload.get("max_tokens"), 3500)

    @patch("app.services.ai_service.requests.post")
    def test_small_library_respects_floor(self, mock_post):
        """1 note → token_limit = max(2000, 1*60+500) = 2000 (floor)."""
        from app.services.chess_log_shallow_service import classify_notes
        mock_post.return_value = _mock_anthropic_response("0: DEEP")
        notes = _make_notes(["note"])
        classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        _, kwargs = mock_post.call_args
        payload = kwargs.get("json") or {}
        self.assertEqual(payload.get("max_tokens"), 2000)


# ---------------------------------------------------------------------------
# 3x3 classifier — helpers
# ---------------------------------------------------------------------------

def _make_notes_3x3(
    why_tuples: list,
    game_number: int = 1,
) -> list:
    """Build 3x3 note list: [(idx, gn, pk, "3x3", why1, why2, why3, why4), ...]."""
    return [
        (i, game_number, f"path/{i}", "3x3", w1, w2, w3, w4)
        for i, (w1, w2, w3, w4) in enumerate(why_tuples)
    ]


# ---------------------------------------------------------------------------
# 3x3 classifier — reply parsing (new 4-field WHY1/WHY2/WHY3/LESSON format)
# ---------------------------------------------------------------------------

class TestClassifyNotes3x3ReplyParsing(unittest.TestCase):
    """classify_notes_3x3() parses WHY1=X WHY2=X WHY3=X LESSON=Y lines correctly."""

    @patch("app.services.ai_service.requests.post")
    def test_clean_specific_real_no_flags(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = "0: WHY1=SPECIFIC WHY2=SPECIFIC WHY3=SPECIFIC LESSON=REAL"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("I wanted to activate my rook.", "Rook was hanging.", "Re1 defends.", "Check rook safety.")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        # SPECIFIC → not shallow; REAL → not vague
        self.assertNotIn((1, "path/0", "3x3", "Why1"), result.shallow_keys)
        self.assertNotIn((1, "path/0", "3x3", "Why2"), result.shallow_keys)
        self.assertNotIn((1, "path/0", "3x3", "Why3"), result.shallow_keys)
        self.assertNotIn((1, "path/0", "3x3", "Why4"), result.vague_keys)

    @patch("app.services.ai_service.requests.post")
    def test_clean_generic_filler_flags_all_whys_and_vague(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = "0: WHY1=GENERIC WHY2=GENERIC WHY3=GENERIC LESSON=FILLER"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("I thought it was a good move.", "My knight was attacked.", "Nd5 forks the queen.", "Be more careful.")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "3x3", "Why1"), result.shallow_keys)
        self.assertIn((1, "path/0", "3x3", "Why2"), result.shallow_keys)
        self.assertIn((1, "path/0", "3x3", "Why3"), result.shallow_keys)
        self.assertIn((1, "path/0", "3x3", "Why4"), result.vague_keys)

    @patch("app.services.ai_service.requests.post")
    def test_specific_filler_only_vague_no_shallow(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = "0: WHY1=SPECIFIC WHY2=SPECIFIC WHY3=SPECIFIC LESSON=FILLER"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("I wanted to trade queens.", "My queen was exposed.", "Qd1 retreats safely.", "Play better.")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        # SPECIFIC → no shallow keys
        self.assertNotIn((1, "path/0", "3x3", "Why1"), result.shallow_keys)
        self.assertNotIn((1, "path/0", "3x3", "Why2"), result.shallow_keys)
        self.assertNotIn((1, "path/0", "3x3", "Why3"), result.shallow_keys)
        # FILLER → vague
        self.assertIn((1, "path/0", "3x3", "Why4"), result.vague_keys)

    @patch("app.services.ai_service.requests.post")
    def test_prose_preamble_skipped(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = (
            "Here are the verdicts:\n\n"
            "0: WHY1=SPECIFIC WHY2=SPECIFIC WHY3=SPECIFIC LESSON=REAL\n"
            "1: WHY1=GENERIC WHY2=SPECIFIC WHY3=SPECIFIC LESSON=FILLER\n"
        )
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([
            ("Active rook.", "Hanging.", "Re1.", "Check safety."),
            ("Good move.", "Attacked.", "Nd5.", "Be careful."),
        ])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        # Note 0: all SPECIFIC+REAL → no flags
        self.assertNotIn((1, "path/0", "3x3", "Why1"), result.shallow_keys)
        self.assertNotIn((1, "path/0", "3x3", "Why4"), result.vague_keys)
        # Note 1: WHY1=GENERIC → shallow on Why1; LESSON=FILLER → vague on Why4
        self.assertIn((1, "path/1", "3x3", "Why1"), result.shallow_keys)
        self.assertNotIn((1, "path/1", "3x3", "Why2"), result.shallow_keys)
        self.assertIn((1, "path/1", "3x3", "Why4"), result.vague_keys)

    @patch("app.services.ai_service.requests.post")
    def test_malformed_why1_unparsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = "0: WHY1=WRONG WHY2=SPECIFIC WHY3=SPECIFIC LESSON=REAL"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, (0,))

    @patch("app.services.ai_service.requests.post")
    def test_malformed_lesson_unparsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = "0: WHY1=SPECIFIC WHY2=SPECIFIC WHY3=SPECIFIC LESSON=WRONG"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, (0,))

    @patch("app.services.ai_service.requests.post")
    def test_missing_lesson_part_unparsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = "0: WHY1=SPECIFIC WHY2=SPECIFIC WHY3=SPECIFIC"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, (0,))

    @patch("app.services.ai_service.requests.post")
    def test_old_two_field_format_unparsed(self, mock_post):
        """Old INTENT=X LESSON=Y format (3 fields) is rejected by the 4-field regex."""
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = "0: INTENT=SPECIFIC LESSON=REAL"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, (0,))

    @patch("app.services.ai_service.requests.post")
    def test_three_why_fields_without_lesson_unparsed(self, mock_post):
        """Three WHY fields but no LESSON= part → unparsed."""
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = "0: WHY1=SPECIFIC WHY2=SPECIFIC WHY3=SPECIFIC"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, (0,))

    @patch("app.services.ai_service.requests.post")
    def test_missing_why1_field_unparsed(self, mock_post):
        """WHY2/WHY3/LESSON present but WHY1 missing → unparsed."""
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = "0: WHY2=SPECIFIC WHY3=SPECIFIC LESSON=REAL"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, (0,))

    @patch("app.services.ai_service.requests.post")
    def test_out_of_order_fields_parsed(self, mock_post):
        """Fields in any order (LESSON before WHY3) → now parsed by tolerant parser."""
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = "0: WHY1=SPECIFIC LESSON=REAL WHY2=SPECIFIC WHY3=SPECIFIC"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertNotIn((1, "path/0", "3x3", "Why1"), result.shallow_keys)
        self.assertNotIn((1, "path/0", "3x3", "Why4"), result.vague_keys)

    # B1 — tolerant parser: additional failure shapes now accepted ------------

    @patch("app.services.ai_service.requests.post")
    def test_comma_separated_fields_parsed(self, mock_post):
        """Comma-separated fields are accepted by the tolerant parser."""
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = "0: WHY1=SPECIFIC, WHY2=GENERIC, WHY3=SPECIFIC, LESSON=REAL"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "3x3", "Why2"), result.shallow_keys)
        self.assertNotIn((1, "path/0", "3x3", "Why4"), result.vague_keys)

    @patch("app.services.ai_service.requests.post")
    def test_semicolon_separated_fields_parsed(self, mock_post):
        """Semicolon-separated fields are accepted by the tolerant parser."""
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = "0: WHY1=GENERIC; WHY2=SPECIFIC; WHY3=SPECIFIC; LESSON=FILLER"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "3x3", "Why1"), result.shallow_keys)
        self.assertIn((1, "path/0", "3x3", "Why4"), result.vague_keys)

    @patch("app.services.ai_service.requests.post")
    def test_pipe_separated_fields_parsed(self, mock_post):
        """Pipe-separated fields (markdown table shape) are accepted."""
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = "0: WHY1=SPECIFIC | WHY2=GENERIC | WHY3=SPECIFIC | LESSON=REAL"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "3x3", "Why2"), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_bold_wrapped_values_parsed(self, mock_post):
        """Bold-wrapped values (**SPECIFIC**) are accepted by the tolerant parser."""
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = "0: WHY1=**SPECIFIC** WHY2=**GENERIC** WHY3=**SPECIFIC** LESSON=**REAL**"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "3x3", "Why2"), result.shallow_keys)
        self.assertNotIn((1, "path/0", "3x3", "Why4"), result.vague_keys)

    @patch("app.services.ai_service.requests.post")
    def test_lesson_first_all_fields_present_parsed(self, mock_post):
        """LESSON appearing first (before WHY1) is now accepted."""
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = "0: LESSON=FILLER WHY1=GENERIC WHY2=SPECIFIC WHY3=SPECIFIC"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "3x3", "Why1"), result.shallow_keys)
        self.assertIn((1, "path/0", "3x3", "Why4"), result.vague_keys)

    # B1 — negative tests: missing field, duplicate field ----------------------

    @patch("app.services.ai_service.requests.post")
    def test_missing_why2_field_unparsed(self, mock_post):
        """WHY1, WHY3, LESSON present but WHY2 missing → unparsed (no guessing)."""
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = "0: WHY1=SPECIFIC WHY3=SPECIFIC LESSON=REAL"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, (0,))

    @patch("app.services.ai_service.requests.post")
    def test_duplicate_field_unparsed(self, mock_post):
        """WHY1 appearing twice → duplicate → unparsed (no guessing)."""
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = "0: WHY1=SPECIFIC WHY1=GENERIC WHY2=SPECIFIC WHY3=SPECIFIC LESSON=REAL"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, (0,))

    @patch("app.services.ai_service.requests.post")
    def test_mixed_case_accepted(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = "0: why1=specific why2=specific why3=specific lesson=real"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertNotIn((1, "path/0", "3x3", "Why1"), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_prose_mid_sentence_verdict_rejected(self, mock_post):
        """A verdict embedded in mid-sentence prose is not parsed as an index verdict."""
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = (
            "The WHY1=SPECIFIC choice was wrong and the LESSON=REAL is obvious.\n"
            "0: WHY1=SPECIFIC WHY2=SPECIFIC WHY3=SPECIFIC LESSON=REAL\n"
        )
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        # SPECIFIC → no shallow keys; REAL → no vague
        self.assertNotIn((1, "path/0", "3x3", "Why1"), result.shallow_keys)
        self.assertNotIn((1, "path/0", "3x3", "Why4"), result.vague_keys)

    @patch("app.services.ai_service.requests.post")
    def test_missing_config_returns_failure(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes_3x3
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, {}, 30)
        self.assertFalse(result.success)
        self.assertIn("config.json", result.error)

    @patch("app.services.ai_service.requests.post")
    def test_vague_keys_empty_for_clamp(self, mock_post):
        """CLAMP/CCT classify_notes never populates vague_keys."""
        mock_post.return_value = _mock_anthropic_response("0: SHALLOW")
        notes = _make_notes(["note A"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.vague_keys, frozenset())


# ---------------------------------------------------------------------------
# 3x3 classifier — combining rule: per-cat, no cross-answer rescue
# ---------------------------------------------------------------------------

class TestClassifyNotes3x3CombiningRule(unittest.TestCase):
    """Per-answer combining: GENERIC→shallow on that Why; FILLER→vague on Why4; no rescue."""

    # (why1, why2, why3, lesson, expect_shallow_cats, expect_vague)
    _CELLS = [
        ("SPECIFIC", "SPECIFIC", "SPECIFIC", "REAL",   [],                         False),
        ("GENERIC",  "SPECIFIC", "SPECIFIC", "REAL",   ["Why1"],                   False),
        ("SPECIFIC", "GENERIC",  "SPECIFIC", "REAL",   ["Why2"],                   False),
        ("SPECIFIC", "SPECIFIC", "GENERIC",  "REAL",   ["Why3"],                   False),
        ("SPECIFIC", "SPECIFIC", "SPECIFIC", "FILLER", [],                         True),
        ("GENERIC",  "GENERIC",  "GENERIC",  "FILLER", ["Why1", "Why2", "Why3"],   True),
        ("BLANK",    "BLANK",    "BLANK",    "BLANK",  [],                         False),
        ("GENERIC",  "BLANK",    "SPECIFIC", "REAL",   ["Why1"],                   False),
        ("SPECIFIC", "BLANK",    "GENERIC",  "FILLER", ["Why3"],                   True),
    ]

    @patch("app.services.ai_service.requests.post")
    def test_all_cells(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = "\n".join(
            f"{i}: WHY1={w1} WHY2={w2} WHY3={w3} LESSON={lsn}"
            for i, (w1, w2, w3, lsn, _sc, _sv) in enumerate(self._CELLS)
        )
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("w1", "w2", "w3", "w4")] * len(self._CELLS))
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        for i, (w1, w2, w3, lsn, exp_shallow_cats, exp_vague) in enumerate(self._CELLS):
            gn, pk = 1, f"path/{i}"
            label = f"idx {i} ({w1},{w2},{w3},{lsn})"
            for cat in ("Why1", "Why2", "Why3"):
                key = (gn, pk, "3x3", cat)
                if cat in exp_shallow_cats:
                    self.assertIn(key, result.shallow_keys, f"{label} {cat} should be shallow")
                else:
                    self.assertNotIn(key, result.shallow_keys, f"{label} {cat} should not be shallow")
            vague_key = (gn, pk, "3x3", "Why4")
            if exp_vague:
                self.assertIn(vague_key, result.vague_keys, f"{label} Why4 should be vague")
            else:
                self.assertNotIn(vague_key, result.vague_keys, f"{label} Why4 should not be vague")

    @patch("app.services.ai_service.requests.post")
    def test_generic_why1_real_lesson_no_rescue(self, mock_post):
        """REAL lesson does NOT rescue a GENERIC Why1 — per-answer, no cross-rescue."""
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = "0: WHY1=GENERIC WHY2=SPECIFIC WHY3=SPECIFIC LESSON=REAL"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertIn((1, "path/0", "3x3", "Why1"), result.shallow_keys,
                      "GENERIC Why1 is shallow even when lesson is REAL")
        self.assertNotIn((1, "path/0", "3x3", "Why4"), result.vague_keys)

    @patch("app.services.ai_service.requests.post")
    def test_specific_why1_filler_lesson_no_taint(self, mock_post):
        """FILLER lesson does NOT taint a SPECIFIC Why1 — per-answer, no cross-taint."""
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = "0: WHY1=SPECIFIC WHY2=SPECIFIC WHY3=SPECIFIC LESSON=FILLER"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertNotIn((1, "path/0", "3x3", "Why1"), result.shallow_keys,
                         "SPECIFIC Why1 is not shallow even when lesson is FILLER")
        self.assertIn((1, "path/0", "3x3", "Why4"), result.vague_keys)

    @patch("app.services.ai_service.requests.post")
    def test_blank_why_not_shallow(self, mock_post):
        """BLANK Why answer is NOT flagged as shallow (only GENERIC triggers shallow)."""
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = "0: WHY1=BLANK WHY2=BLANK WHY3=BLANK LESSON=BLANK"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("", "", "", "")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertNotIn((1, "path/0", "3x3", "Why1"), result.shallow_keys)
        self.assertNotIn((1, "path/0", "3x3", "Why2"), result.shallow_keys)
        self.assertNotIn((1, "path/0", "3x3", "Why3"), result.shallow_keys)
        self.assertNotIn((1, "path/0", "3x3", "Why4"), result.vague_keys)


# ---------------------------------------------------------------------------
# 3x3 classifier — partial reply, failure, token budget
# ---------------------------------------------------------------------------

class TestClassifyNotes3x3PartialReply(unittest.TestCase):
    """Some indices parsed, others missing → unparsed_indices correct."""

    @patch("app.services.ai_service.requests.post")
    def test_partial_reply_missing_index_reported(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes_3x3
        # Three notes but reply only covers indices 0 and 2
        reply = (
            "0: WHY1=SPECIFIC WHY2=SPECIFIC WHY3=SPECIFIC LESSON=REAL\n"
            "2: WHY1=GENERIC WHY2=SPECIFIC WHY3=SPECIFIC LESSON=REAL\n"
        )
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("a", "b", "c", "d")] * 3)
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, (1,))
        self.assertNotIn((1, "path/1", "3x3", "Why1"), result.shallow_keys)
        self.assertIn((1, "path/2", "3x3", "Why1"), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_partial_reply_out_of_range_index_ignored(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = (
            "0: WHY1=GENERIC WHY2=SPECIFIC WHY3=SPECIFIC LESSON=REAL\n"
            "99: WHY1=GENERIC WHY2=GENERIC WHY3=GENERIC LESSON=FILLER\n"
        )
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "3x3", "Why1"), result.shallow_keys)
        self.assertEqual(len(result.shallow_keys), 1)


class TestClassifyNotes3x3Failure(unittest.TestCase):
    """API failure returns success=False with all indices in unparsed_indices."""

    @patch("app.services.ai_service.requests.post")
    def test_api_error_success_false_all_unparsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes_3x3
        mock_post.return_value = _mock_anthropic_error(500, "Internal Server Error")
        notes = _make_notes_3x3([("a", "b", "c", "d"), ("e", "f", "g", "h")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertFalse(result.success)
        self.assertEqual(result.unparsed_indices, (0, 1))
        self.assertEqual(len(result.shallow_keys), 0)
        self.assertEqual(len(result.vague_keys), 0)


class TestClassifyNotes3x3TokenBudget(unittest.TestCase):
    """classify_notes_3x3 uses per_note=90 for a larger token budget."""

    @patch("app.services.ai_service.requests.post")
    def test_3x3_token_budget_uses_90_per_note(self, mock_post):
        """50 notes → token_limit = max(2000, 50*90+500) = 5000."""
        from app.services.chess_log_shallow_service import classify_notes_3x3
        replies = "\n".join(
            f"{i}: WHY1=SPECIFIC WHY2=SPECIFIC WHY3=SPECIFIC LESSON=REAL"
            for i in range(50)
        )
        mock_post.return_value = _mock_anthropic_response(replies)
        notes = _make_notes_3x3([("a", "b", "c", "d")] * 50)
        classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        _, kwargs = mock_post.call_args
        payload = kwargs.get("json") or {}
        self.assertEqual(payload.get("max_tokens"), 5000)

    @patch("app.services.ai_service.requests.post")
    def test_3x3_small_library_respects_floor(self, mock_post):
        """1 note → token_limit = max(2000, 1*90+500) = 2000 (floor)."""
        from app.services.chess_log_shallow_service import classify_notes_3x3
        mock_post.return_value = _mock_anthropic_response(
            "0: WHY1=SPECIFIC WHY2=SPECIFIC WHY3=SPECIFIC LESSON=REAL"
        )
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        _, kwargs = mock_post.call_args
        payload = kwargs.get("json") or {}
        self.assertEqual(payload.get("max_tokens"), 2000)


# ---------------------------------------------------------------------------
# 3x3 classifier — glued reply blocks
# ---------------------------------------------------------------------------

class TestClassifyNotes3x3GluedReplies(unittest.TestCase):
    """Glued 3x3 reply blocks (no newline between verdicts) must be handled."""

    @patch("app.services.ai_service.requests.post")
    def test_glued_real_verdict_followed_by_next_index(self, mock_post):
        """'REAL1:' glued reply: both indices parsed after preprocessing."""
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = (
            "0: WHY1=SPECIFIC WHY2=SPECIFIC WHY3=SPECIFIC LESSON=REAL"
            "1: WHY1=GENERIC WHY2=SPECIFIC WHY3=SPECIFIC LESSON=FILLER"
        )
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("a", "b", "c", "d"), ("e", "f", "g", "h")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, (),
                         f"Unparsed: {result.unparsed_indices}; glued reply must be split")
        # Note 0: all SPECIFIC+REAL → no flags
        self.assertNotIn((1, "path/0", "3x3", "Why1"), result.shallow_keys)
        self.assertNotIn((1, "path/0", "3x3", "Why4"), result.vague_keys)
        # Note 1: WHY1=GENERIC → shallow on Why1; FILLER → vague on Why4
        self.assertIn((1, "path/1", "3x3", "Why1"), result.shallow_keys)
        self.assertIn((1, "path/1", "3x3", "Why4"), result.vague_keys)

    @patch("app.services.ai_service.requests.post")
    def test_glued_filler_verdict_followed_by_next_index(self, mock_post):
        """'FILLER1:' glued reply: both indices parsed."""
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = (
            "0: WHY1=GENERIC WHY2=SPECIFIC WHY3=SPECIFIC LESSON=FILLER"
            "1: WHY1=SPECIFIC WHY2=SPECIFIC WHY3=SPECIFIC LESSON=REAL"
        )
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("a", "b", "c", "d"), ("e", "f", "g", "h")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, (),
                         f"Unparsed: {result.unparsed_indices}")

    @patch("app.services.ai_service.requests.post")
    def test_glued_blank_verdict_followed_by_next_index(self, mock_post):
        """'BLANK1:' glued reply: both indices parsed."""
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = (
            "0: WHY1=BLANK WHY2=BLANK WHY3=BLANK LESSON=BLANK"
            "1: WHY1=GENERIC WHY2=SPECIFIC WHY3=SPECIFIC LESSON=FILLER"
        )
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("a", "b", "c", "d"), ("e", "f", "g", "h")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, (),
                         f"Unparsed: {result.unparsed_indices}")

    @patch("app.services.ai_service.requests.post")
    def test_glued_specific_verdict_followed_by_next_index(self, mock_post):
        """'SPECIFIC1:' glued reply: preprocessing splits on SPECIFIC too."""
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = (
            "0: WHY1=SPECIFIC WHY2=SPECIFIC WHY3=SPECIFIC LESSON=REAL"
            "1: WHY1=GENERIC WHY2=SPECIFIC WHY3=SPECIFIC LESSON=REAL"
        )
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("a", "b", "c", "d"), ("e", "f", "g", "h")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, (),
                         f"Unparsed: {result.unparsed_indices}")


# ---------------------------------------------------------------------------
# 3x3 classifier — duplicate indices
# ---------------------------------------------------------------------------

class TestClassifyNotes3x3DuplicateIndices(unittest.TestCase):
    """Duplicate indices in 3x3 replies — last wins, same as CLAMP."""

    @patch("app.services.ai_service.requests.post")
    def test_duplicate_index_last_verdict_wins(self, mock_post):
        """Last verdict wins: first GENERIC+FILLER then SPECIFIC+REAL → no flags."""
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = (
            "0: WHY1=GENERIC WHY2=GENERIC WHY3=GENERIC LESSON=FILLER\n"
            "0: WHY1=SPECIFIC WHY2=SPECIFIC WHY3=SPECIFIC LESSON=REAL\n"
        )
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertNotIn((1, "path/0", "3x3", "Why1"), result.shallow_keys,
                         "last verdict SPECIFIC → not shallow")
        self.assertNotIn((1, "path/0", "3x3", "Why4"), result.vague_keys,
                         "last verdict REAL → not vague")

    @patch("app.services.ai_service.requests.post")
    def test_duplicate_index_last_verdict_wins_reversed(self, mock_post):
        """Reversed order: first SPECIFIC+REAL, second GENERIC+FILLER → flags on all."""
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = (
            "0: WHY1=SPECIFIC WHY2=SPECIFIC WHY3=SPECIFIC LESSON=REAL\n"
            "0: WHY1=GENERIC WHY2=GENERIC WHY3=GENERIC LESSON=FILLER\n"
        )
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "3x3", "Why1"), result.shallow_keys,
                      "last verdict GENERIC → shallow")
        self.assertIn((1, "path/0", "3x3", "Why4"), result.vague_keys,
                      "last verdict FILLER → vague")

    @patch("app.services.ai_service.requests.post")
    def test_clamp_duplicate_last_wins_matches_3x3_behavior(self, mock_post):
        """CLAMP and 3x3 must agree: last occurrence wins."""
        from app.services.chess_log_shallow_service import classify_notes
        reply = "0: SHALLOW\n0: DEEP\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertNotIn((1, "path/0", "CLAMP", ""), result.shallow_keys)


# ---------------------------------------------------------------------------
# temperature kwarg: AIService.send_message plumbing
# ---------------------------------------------------------------------------

class TestTemperatureDefaults(unittest.TestCase):
    """Without temperature kwarg: OpenAI sends 0.7; Anthropic sends no temperature key."""

    def setUp(self):
        from app.services.ai_service import AIService
        AIService._models_not_supporting_temperature.discard("gpt-4o")
        AIService._models_requiring_max_completion_tokens.discard("gpt-4o")

    @patch("app.services.ai_service.requests.post")
    def test_openai_default_temperature_0_7(self, mock_post):
        from app.services.ai_service import AIService
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"x"
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        mock_post.return_value = mock_response
        svc = AIService(config=_CONFIG)
        svc.send_message(
            provider="openai",
            model="gpt-4o",
            api_key="sk-test",
            messages=[{"role": "user", "content": "hi"}],
            token_limit=100,
        )
        _, kwargs = mock_post.call_args
        payload = kwargs.get("json") or {}
        self.assertEqual(payload.get("temperature"), 0.7)

    @patch("app.services.ai_service.requests.post")
    def test_anthropic_default_no_temperature_key(self, mock_post):
        from app.services.ai_service import AIService
        mock_post.return_value = _mock_anthropic_response("hi")
        svc = AIService(config=_CONFIG)
        svc.send_message(
            provider="anthropic",
            model="claude-sonnet-4-6",
            api_key="sk-test",
            messages=[{"role": "user", "content": "hi"}],
            token_limit=100,
        )
        _, kwargs = mock_post.call_args
        payload = kwargs.get("json") or {}
        self.assertNotIn("temperature", payload)


class TestTemperatureZeroExplicit(unittest.TestCase):
    """temperature=0 is forwarded to both providers."""

    def setUp(self):
        from app.services.ai_service import AIService
        AIService._models_not_supporting_temperature.discard("gpt-4o")
        AIService._models_requiring_max_completion_tokens.discard("gpt-4o")

    @patch("app.services.ai_service.requests.post")
    def test_openai_explicit_temperature_zero(self, mock_post):
        from app.services.ai_service import AIService
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"x"
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        mock_post.return_value = mock_response
        svc = AIService(config=_CONFIG)
        svc.send_message(
            provider="openai",
            model="gpt-4o",
            api_key="sk-test",
            messages=[{"role": "user", "content": "hi"}],
            token_limit=100,
            temperature=0,
        )
        _, kwargs = mock_post.call_args
        payload = kwargs.get("json") or {}
        self.assertEqual(payload.get("temperature"), 0)

    @patch("app.services.ai_service.requests.post")
    def test_anthropic_explicit_temperature_zero(self, mock_post):
        from app.services.ai_service import AIService
        mock_post.return_value = _mock_anthropic_response("hi")
        svc = AIService(config=_CONFIG)
        svc.send_message(
            provider="anthropic",
            model="claude-sonnet-4-6",
            api_key="sk-test",
            messages=[{"role": "user", "content": "hi"}],
            token_limit=100,
            temperature=0,
        )
        _, kwargs = mock_post.call_args
        payload = kwargs.get("json") or {}
        self.assertEqual(payload.get("temperature"), 0)


class TestTemperatureSentWhenThinkingDisabled(unittest.TestCase):
    """temperature=0 is sent even when thinking={type:disabled} — disabled is not live."""

    @patch("app.services.ai_service.requests.post")
    def test_sonnet5_thinking_disabled_temperature_sent(self, mock_post):
        from app.services.ai_service import AIService
        mock_post.return_value = _mock_anthropic_response("hi")
        svc = AIService(config=_CONFIG)
        svc.send_message(
            provider="anthropic",
            model="claude-sonnet-5-20251101",
            api_key="sk-test",
            messages=[{"role": "user", "content": "hi"}],
            token_limit=100,
            temperature=0,
            thinking={"type": "disabled"},
        )
        _, kwargs = mock_post.call_args
        payload = kwargs.get("json") or {}
        # thinking=disabled is NOT a live thinking mode → temperature must be present
        self.assertEqual(payload.get("thinking"), {"type": "disabled"})
        self.assertEqual(payload.get("temperature"), 0)


class TestTemperatureDroppedOnThinkingLive(unittest.TestCase):
    """temperature is dropped when a live thinking mode is active."""

    @patch("app.services.ai_service.requests.post")
    def test_temperature_dropped_on_between_tools_retry(self, mock_post):
        """Sonnet-5.5 retry uses between_tools → temperature must be absent."""
        from app.services.ai_service import AIService

        # First call: return 400 with "between_tools … instead of" to trigger between_tools retry
        error_resp = MagicMock()
        error_resp.status_code = 400
        error_resp.content = b"x"
        error_resp.json.return_value = {
            "error": {"message": "Use thinking.type.between_tools instead of disabled for this model"}
        }

        # Second call (retry): succeed
        retry_resp = _mock_anthropic_response("hi")

        mock_post.side_effect = [error_resp, retry_resp]
        svc = AIService(config=_CONFIG)
        svc.send_message(
            provider="anthropic",
            model="claude-sonnet-5-5-20260101",
            api_key="sk-test",
            messages=[{"role": "user", "content": "hi"}],
            token_limit=100,
            temperature=0,
            thinking={"type": "disabled"},
        )
        self.assertEqual(mock_post.call_count, 2)
        # Second call is the retry
        _, kwargs = mock_post.call_args_list[1]
        payload = kwargs.get("json") or {}
        # between_tools is live → temperature must be absent
        thinking = payload.get("thinking", {})
        self.assertEqual(thinking.get("type"), "between_tools")
        self.assertNotIn("temperature", payload)

    @patch("app.services.ai_service.requests.post")
    def test_temperature_dropped_on_adaptive_retry(self, mock_post):
        """Opus-5.5 retry uses adaptive+low → temperature must be absent."""
        from app.services.ai_service import AIService

        error_resp = MagicMock()
        error_resp.status_code = 400
        error_resp.content = b"x"
        error_resp.json.return_value = {
            "error": {"message": "thinking.type.disabled is not supported for this model; use adaptive instead"}
        }

        retry_resp = _mock_anthropic_response("hi")
        mock_post.side_effect = [error_resp, retry_resp]
        svc = AIService(config=_CONFIG)
        svc.send_message(
            provider="anthropic",
            model="claude-opus-5-5-20260101",
            api_key="sk-test",
            messages=[{"role": "user", "content": "hi"}],
            token_limit=100,
            temperature=0,
            thinking={"type": "disabled"},
        )
        self.assertEqual(mock_post.call_count, 2)
        _, kwargs = mock_post.call_args_list[1]
        payload = kwargs.get("json") or {}
        # adaptive is live (or output_config present) → temperature must be absent
        has_adaptive = payload.get("thinking", {}).get("type") == "adaptive"
        has_output_config = "output_config" in payload
        self.assertTrue(has_adaptive or has_output_config,
                        "Opus-5.5 retry should use adaptive thinking or output_config")
        self.assertNotIn("temperature", payload)


class TestTemperatureFallbackRetry(unittest.TestCase):
    """If Anthropic rejects temperature on an unexpected 400, one retry without it is made."""

    @patch("app.services.ai_service.requests.post")
    def test_temperature_retry_on_unexpected_400(self, mock_post):
        from app.services.ai_service import AIService

        # First response: 400 mentioning "temperature"
        error_resp = MagicMock()
        error_resp.status_code = 400
        error_resp.content = b"x"
        error_resp.json.return_value = {
            "error": {"message": "temperature is not supported for this model configuration"}
        }
        # Second response: success after dropping temperature
        ok_resp = _mock_anthropic_response("hi")
        mock_post.side_effect = [error_resp, ok_resp]

        mock_logger = MagicMock()
        svc = AIService(config=_CONFIG)
        with patch(
            "app.services.ai_service.LoggingService.get_instance",
            return_value=mock_logger,
        ):
            result = svc.send_message(
                provider="anthropic",
                model="claude-sonnet-4-6",
                api_key="sk-test",
                messages=[{"role": "user", "content": "hi"}],
                token_limit=100,
                temperature=0,
            )
        # Exactly one retry — two total calls
        self.assertEqual(mock_post.call_count, 2)
        # WARNING logged via LoggingService with model id
        mock_logger.warning.assert_called_once()
        warning_text = mock_logger.warning.call_args.args[0]
        self.assertIn("claude-sonnet-4-6", warning_text)
        # Second call must have no temperature key
        _, kwargs = mock_post.call_args_list[1]
        payload = kwargs.get("json") or {}
        self.assertNotIn("temperature", payload)
        # Result should succeed
        self.assertTrue(result.success)


class TestTemperatureZeroPassed(unittest.TestCase):
    """Classifier call sites pass temperature=0 to send_message."""

    @patch("app.services.chess_log_shallow_service.AIService")
    def test_classify_notes_passes_temperature_zero(self, MockAIService):
        """classify_notes calls send_message with temperature=0."""
        from app.services.chess_log_shallow_service import classify_notes
        mock_instance = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.text = "0: DEEP"
        mock_result.stop_reason = "end_turn"
        mock_result.content_block_count = 1
        mock_result.content_block_types = ["text"]
        mock_result.usage = None
        mock_instance.send_message.return_value = mock_result
        MockAIService.return_value = mock_instance

        notes = _make_notes(["note A"])
        classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        mock_instance.send_message.assert_called_once()
        _, kwargs = mock_instance.send_message.call_args
        self.assertEqual(kwargs.get("temperature"), 0)

    @patch("app.services.chess_log_shallow_service.AIService")
    def test_classify_notes_3x3_passes_temperature_zero(self, MockAIService):
        """classify_notes_3x3 calls send_message with temperature=0."""
        from app.services.chess_log_shallow_service import classify_notes_3x3
        mock_instance = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.text = "0: WHY1=SPECIFIC WHY2=SPECIFIC WHY3=SPECIFIC LESSON=REAL"
        mock_result.stop_reason = "end_turn"
        mock_result.content_block_count = 1
        mock_result.content_block_types = ["text"]
        mock_result.usage = None
        mock_instance.send_message.return_value = mock_result
        MockAIService.return_value = mock_instance

        notes = _make_notes_3x3([("a", "b", "c", "d")])
        classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        mock_instance.send_message.assert_called_once()
        _, kwargs = mock_instance.send_message.call_args
        self.assertEqual(kwargs.get("temperature"), 0)


if __name__ == "__main__":
    unittest.main()
