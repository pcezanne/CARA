"""Tests for AIService.send_message thinking parameter forwarding."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.services.ai_service import AIService


def _make_anthropic_response(text: str = "ok") -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.content = b"x"
    mock.json.return_value = {
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
    }
    return mock


def _captured_payload(mock_post) -> dict:
    """Extract the JSON body sent to requests.post."""
    args, kwargs = mock_post.call_args
    return kwargs.get("json") or (args[1] if len(args) > 1 else {})


class TestSendMessageThinkingForwarding(unittest.TestCase):
    """thinking parameter must reach the Anthropic payload when set."""

    @patch("app.services.ai_service.requests.post")
    def test_thinking_disabled_in_anthropic_payload(self, mock_post):
        mock_post.return_value = _make_anthropic_response()
        AIService().send_message(
            provider="anthropic",
            model="claude-sonnet-5",
            api_key="sk-test",
            messages=[{"role": "user", "content": "hello"}],
            thinking={"type": "disabled"},
        )
        self.assertEqual(_captured_payload(mock_post).get("thinking"), {"type": "disabled"})

    @patch("app.services.ai_service.requests.post")
    def test_thinking_none_absent_from_anthropic_payload(self, mock_post):
        mock_post.return_value = _make_anthropic_response()
        AIService().send_message(
            provider="anthropic",
            model="claude-sonnet-4-6",
            api_key="sk-test",
            messages=[{"role": "user", "content": "hello"}],
        )
        self.assertNotIn("thinking", _captured_payload(mock_post))

    @patch("app.services.ai_service.requests.post")
    def test_thinking_not_forwarded_to_openai(self, mock_post):
        mock_openai = MagicMock()
        mock_openai.status_code = 200
        mock_openai.content = b"x"
        mock_openai.json.return_value = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]
        }
        mock_post.return_value = mock_openai
        AIService().send_message(
            provider="openai",
            model="gpt-4",
            api_key="sk-test",
            messages=[{"role": "user", "content": "hello"}],
            thinking={"type": "disabled"},
        )
        self.assertNotIn("thinking", _captured_payload(mock_post))


class TestSendAnthropicMessageThinking(unittest.TestCase):
    """Direct _send_anthropic_message tests for thinking kwarg."""

    @patch("app.services.ai_service.requests.post")
    def test_thinking_in_payload_when_set(self, mock_post):
        mock_post.return_value = _make_anthropic_response()
        AIService()._send_anthropic_message(
            model="claude-opus-5",
            api_key="sk-test",
            messages=[{"role": "user", "content": "hello"}],
            thinking={"type": "disabled"},
        )
        self.assertEqual(_captured_payload(mock_post).get("thinking"), {"type": "disabled"})

    @patch("app.services.ai_service.requests.post")
    def test_thinking_absent_when_none(self, mock_post):
        mock_post.return_value = _make_anthropic_response()
        AIService()._send_anthropic_message(
            model="claude-sonnet-4-6",
            api_key="sk-test",
            messages=[{"role": "user", "content": "hello"}],
        )
        self.assertNotIn("thinking", _captured_payload(mock_post))


class TestDisableThinkingFor(unittest.TestCase):
    """disable_thinking_for — per-family probe results (2026-09-27).

    Empirically verified via real API calls:
    - sonnet-5 and opus-5: {"type": "disabled"} accepted silently.
    - fable-5-1: {"type": "disabled"} returns HTTP 400 — must return None.
    - opus-4-7 (control): {"type": "disabled"} accepted; returns None anyway
      (not in _THINKING_DISABLE_MODELS — thinking not on by default).
    No model triggered thinking without an explicit thinking parameter.
    """

    def test_sonnet_5_returns_disabled(self):
        self.assertEqual(AIService.disable_thinking_for("claude-sonnet-5-20251101"), {"type": "disabled"})

    def test_opus_5_returns_disabled(self):
        self.assertEqual(AIService.disable_thinking_for("claude-opus-5-20251101"), {"type": "disabled"})

    def test_fable_5_returns_none(self):
        self.assertIsNone(AIService.disable_thinking_for("claude-fable-5-1-20251101"))

    def test_opus_4_7_returns_none(self):
        self.assertIsNone(AIService.disable_thinking_for("claude-opus-4-7-20250514"))

    def test_sonnet_4_6_returns_none(self):
        self.assertIsNone(AIService.disable_thinking_for("claude-sonnet-4-6-20250514"))

    def test_empty_string_returns_none(self):
        self.assertIsNone(AIService.disable_thinking_for(""))

    def test_none_model_returns_none(self):
        self.assertIsNone(AIService.disable_thinking_for(None))


if __name__ == "__main__":
    unittest.main()
