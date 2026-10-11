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
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
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
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
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
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
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
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
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
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP"), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_underscore_markdown_parsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        reply = "0: _SHALLOW_\n1: _DEEP_\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "CLAMP"), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_trailing_comma_parsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes
        reply = "0: SHALLOW,\n1: DEEP;\n"
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes(["note A", "note B"])
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
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
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
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
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
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
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
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
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
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
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
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
        self.assertIn((1, "path/0", "CLAMP"), result.shallow_keys)
        self.assertNotIn((1, "path/1", "CLAMP"), result.shallow_keys)

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
        self.assertNotIn((1, "path/1", "CLAMP"), result.shallow_keys)

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
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
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
        result = classify_notes(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
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
        self.assertIn((1, "path/0", "CLAMP"), result.shallow_keys)


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
        self.assertNotIn((1, "path/0", "CLAMP"), result.shallow_keys)

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
        mock_logger.debug.assert_called_once()
        mock_logger.warning.assert_not_called()


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
# 3x3 classifier — reply parsing
# ---------------------------------------------------------------------------

class TestClassifyNotes3x3ReplyParsing(unittest.TestCase):
    """classify_notes_3x3() parses INTENT=X LESSON=Y lines correctly."""

    @patch("app.services.ai_service.requests.post")
    def test_clean_specific_real_is_deep_not_vague(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes_3x3
        mock_post.return_value = _mock_anthropic_response("0: INTENT=SPECIFIC LESSON=REAL")
        notes = _make_notes_3x3([("I wanted to activate my rook.", "Rook was hanging.", "Re1 defends.", "Check rook safety.")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertNotIn((1, "path/0", "3x3"), result.shallow_keys)
        self.assertNotIn((1, "path/0", "3x3"), result.vague_keys)

    @patch("app.services.ai_service.requests.post")
    def test_clean_generic_filler_is_shallow_and_vague(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes_3x3
        mock_post.return_value = _mock_anthropic_response("0: INTENT=GENERIC LESSON=FILLER")
        notes = _make_notes_3x3([("I thought it was a good move.", "My knight was attacked.", "Nd5 forks the queen.", "Be more careful.")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertIn((1, "path/0", "3x3"), result.shallow_keys)
        self.assertIn((1, "path/0", "3x3"), result.vague_keys)

    @patch("app.services.ai_service.requests.post")
    def test_specific_filler_is_deep_and_vague(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes_3x3
        mock_post.return_value = _mock_anthropic_response("0: INTENT=SPECIFIC LESSON=FILLER")
        notes = _make_notes_3x3([("I wanted to trade queens.", "My queen was exposed.", "Qd1 retreats safely.", "Play better.")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertNotIn((1, "path/0", "3x3"), result.shallow_keys)
        self.assertIn((1, "path/0", "3x3"), result.vague_keys)

    @patch("app.services.ai_service.requests.post")
    def test_prose_preamble_skipped(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = (
            "Here are the verdicts:\n\n"
            "0: INTENT=SPECIFIC LESSON=REAL\n"
            "1: INTENT=GENERIC LESSON=FILLER\n"
        )
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([
            ("Active rook.", "Hanging.", "Re1.", "Check safety."),
            ("Good move.", "Attacked.", "Nd5.", "Be careful."),
        ])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertNotIn((1, "path/0", "3x3"), result.shallow_keys)
        self.assertIn((1, "path/1", "3x3"), result.shallow_keys)
        self.assertIn((1, "path/1", "3x3"), result.vague_keys)

    @patch("app.services.ai_service.requests.post")
    def test_malformed_intent_unparsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes_3x3
        mock_post.return_value = _mock_anthropic_response("0: INTENT=WRONG LESSON=REAL")
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, (0,))

    @patch("app.services.ai_service.requests.post")
    def test_malformed_lesson_unparsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes_3x3
        mock_post.return_value = _mock_anthropic_response("0: INTENT=SPECIFIC LESSON=WRONG")
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, (0,))

    @patch("app.services.ai_service.requests.post")
    def test_missing_lesson_part_unparsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes_3x3
        mock_post.return_value = _mock_anthropic_response("0: INTENT=SPECIFIC")
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, (0,))

    @patch("app.services.ai_service.requests.post")
    def test_missing_intent_part_unparsed(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes_3x3
        mock_post.return_value = _mock_anthropic_response("0: LESSON=FILLER")
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, (0,))

    @patch("app.services.ai_service.requests.post")
    def test_mixed_case_accepted(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes_3x3
        mock_post.return_value = _mock_anthropic_response("0: intent=specific lesson=real")
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertNotIn((1, "path/0", "3x3"), result.shallow_keys)

    @patch("app.services.ai_service.requests.post")
    def test_prose_mid_sentence_verdict_rejected(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = (
            "The INTENT=SPECIFIC choice was wrong and the LESSON=FILLER is obvious.\n"
            "0: INTENT=GENERIC LESSON=REAL\n"
        )
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("a", "b", "c", "d")])
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        self.assertNotIn((1, "path/0", "3x3"), result.shallow_keys)

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
# 3x3 classifier — combining rule (all 9 INTENT × LESSON cells)
# ---------------------------------------------------------------------------

class TestClassifyNotes3x3CombiningRule(unittest.TestCase):
    """Every INTENT × LESSON combination produces the correct shallow/vague flags."""

    # (intent, lesson, expect_shallow, expect_vague)
    _CELLS = [
        ("SPECIFIC", "REAL",   False, False),
        ("SPECIFIC", "FILLER", False, True),
        ("SPECIFIC", "BLANK",  False, False),
        ("GENERIC",  "REAL",   False, False),
        ("GENERIC",  "FILLER", True,  True),
        ("GENERIC",  "BLANK",  True,  False),
        ("BLANK",    "REAL",   False, False),
        ("BLANK",    "FILLER", True,  True),
        ("BLANK",    "BLANK",  True,  False),
    ]

    @patch("app.services.ai_service.requests.post")
    def test_all_nine_cells(self, mock_post):
        from app.services.chess_log_shallow_service import classify_notes_3x3
        reply = "\n".join(
            f"{i}: INTENT={intent} LESSON={lesson}"
            for i, (intent, lesson, _s, _v) in enumerate(self._CELLS)
        )
        mock_post.return_value = _mock_anthropic_response(reply)
        notes = _make_notes_3x3([("w1", "w2", "w3", "w4")] * len(self._CELLS))
        result = classify_notes_3x3(notes, "anthropic", "claude-sonnet-4-6", "sk-test", None, _CONFIG, 30)
        self.assertTrue(result.success)
        self.assertEqual(result.unparsed_indices, ())
        for i, (intent, lesson, exp_shallow, exp_vague) in enumerate(self._CELLS):
            key = (1, f"path/{i}", "3x3")
            label = f"idx {i} ({intent}+{lesson})"
            if exp_shallow:
                self.assertIn(key, result.shallow_keys, f"{label} should be shallow")
            else:
                self.assertNotIn(key, result.shallow_keys, f"{label} should be deep")
            if exp_vague:
                self.assertIn(key, result.vague_keys, f"{label} should be vague")
            else:
                self.assertNotIn(key, result.vague_keys, f"{label} should not be vague")


if __name__ == "__main__":
    unittest.main()
