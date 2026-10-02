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


def _make_anthropic_400(message: str) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 400
    mock.content = b"x"
    mock.json.return_value = {"error": {"message": message}}
    return mock


_THINKING_DISABLED_400_MESSAGE = (
    '"thinking.type.disabled" is not supported for this model. '
    'Use "thinking.type.adaptive" and "output_config.effort" to control thinking behavior.'
)


class TestAdaptiveThinkingFallback(unittest.TestCase):
    """When a model rejects thinking.type.disabled, retry once with adaptive + effort:low."""

    def setUp(self):
        AIService._models_requiring_adaptive_thinking.clear()

    def tearDown(self):
        AIService._models_requiring_adaptive_thinking.clear()

    @patch("app.services.ai_service.requests.post")
    def test_model_accepting_disabled_no_retry(self, mock_post):
        """Sonnet 5 / Opus 5: 200 on first try, no retry, payload keeps disabled."""
        mock_post.return_value = _make_anthropic_response()
        result = AIService().send_message(
            provider="anthropic",
            model="claude-sonnet-5-20251101",
            api_key="sk-test",
            messages=[{"role": "user", "content": "hi"}],
            thinking={"type": "disabled"},
        )
        self.assertEqual(mock_post.call_count, 1)
        payload = _captured_payload(mock_post)
        self.assertEqual(payload.get("thinking"), {"type": "disabled"})
        self.assertNotIn("output_config", payload)
        self.assertTrue(result.success)

    @patch("app.services.ai_service.requests.post")
    def test_model_rejecting_disabled_retries_with_adaptive(self, mock_post):
        """Opus 5.5: 400 on first try → retry with adaptive + low effort → success."""
        mock_post.side_effect = [
            _make_anthropic_400(_THINKING_DISABLED_400_MESSAGE),
            _make_anthropic_response("great answer"),
        ]
        result = AIService().send_message(
            provider="anthropic",
            model="claude-opus-5-5-20251101",
            api_key="sk-test",
            messages=[{"role": "user", "content": "hi"}],
            thinking={"type": "disabled"},
        )
        self.assertEqual(mock_post.call_count, 2)
        # First attempt sent disabled
        first_payload = mock_post.call_args_list[0][1].get("json") or mock_post.call_args_list[0][0][1]
        self.assertEqual(first_payload.get("thinking"), {"type": "disabled"})
        self.assertNotIn("output_config", first_payload)
        # Retry sent adaptive + effort:low
        retry_payload = mock_post.call_args_list[1][1].get("json") or mock_post.call_args_list[1][0][1]
        self.assertEqual(retry_payload.get("thinking"), {"type": "adaptive"})
        self.assertEqual(retry_payload.get("output_config"), {"effort": "low"})
        self.assertTrue(result.success)
        self.assertEqual(result.text, "great answer")

    @patch("app.services.ai_service.requests.post")
    def test_session_cache_skips_disabled_attempt(self, mock_post):
        """After a successful retry, subsequent calls go straight to adaptive (one request, no 400)."""
        # Seed the cache as if a prior call already discovered this model.
        AIService._models_requiring_adaptive_thinking.add("claude-opus-5-5-20251101")
        mock_post.return_value = _make_anthropic_response("cached path answer")
        result = AIService().send_message(
            provider="anthropic",
            model="claude-opus-5-5-20251101",
            api_key="sk-test",
            messages=[{"role": "user", "content": "hi"}],
            thinking={"type": "disabled"},
        )
        self.assertEqual(mock_post.call_count, 1)
        payload = _captured_payload(mock_post)
        self.assertEqual(payload.get("thinking"), {"type": "adaptive"})
        self.assertEqual(payload.get("output_config"), {"effort": "low"})
        self.assertTrue(result.success)

    @patch("app.services.ai_service.requests.post")
    def test_cache_is_per_model_id(self, mock_post):
        """Caching opus-5-5 does not affect the unversioned opus-5 model."""
        AIService._models_requiring_adaptive_thinking.add("claude-opus-5-5-20251101")
        mock_post.return_value = _make_anthropic_response()
        AIService().send_message(
            provider="anthropic",
            model="claude-opus-5-20251101",
            api_key="sk-test",
            messages=[{"role": "user", "content": "hi"}],
            thinking={"type": "disabled"},
        )
        payload = _captured_payload(mock_post)
        self.assertEqual(payload.get("thinking"), {"type": "disabled"})
        self.assertNotIn("output_config", payload)

    @patch("app.services.ai_service.requests.post")
    def test_other_400_not_retried(self, mock_post):
        """An unrelated 400 error is returned immediately with no retry."""
        mock_post.return_value = _make_anthropic_400("max_tokens exceeded")
        result = AIService().send_message(
            provider="anthropic",
            model="claude-opus-5-5-20251101",
            api_key="sk-test",
            messages=[{"role": "user", "content": "hi"}],
            thinking={"type": "disabled"},
        )
        self.assertEqual(mock_post.call_count, 1)
        self.assertFalse(result.success)
        self.assertIn("max_tokens exceeded", result.error)

    @patch("app.services.ai_service.requests.post")
    def test_retry_failure_propagates_api_message(self, mock_post):
        """When the retry also fails, the retry's API message is returned intact."""
        mock_post.side_effect = [
            _make_anthropic_400(_THINKING_DISABLED_400_MESSAGE),
            _make_anthropic_400("some other server error on retry"),
        ]
        result = AIService().send_message(
            provider="anthropic",
            model="claude-opus-5-5-20251101",
            api_key="sk-test",
            messages=[{"role": "user", "content": "hi"}],
            thinking={"type": "disabled"},
        )
        self.assertEqual(mock_post.call_count, 2)
        self.assertFalse(result.success)
        self.assertIn("some other server error on retry", result.error)

    @patch("app.services.ai_service.requests.post")
    def test_thinking_blocks_before_text_block_ignored(self, mock_post):
        """Response with a thinking block before the text block returns only the text."""
        mock = MagicMock()
        mock.status_code = 200
        mock.content = b"x"
        mock.json.return_value = {
            "content": [
                {"type": "thinking", "thinking": "internal reasoning here"},
                {"type": "text", "text": "final answer"},
            ],
            "stop_reason": "end_turn",
        }
        mock_post.return_value = mock
        result = AIService().send_message(
            provider="anthropic",
            model="claude-opus-5-5-20251101",
            api_key="sk-test",
            messages=[{"role": "user", "content": "hi"}],
        )
        self.assertTrue(result.success)
        self.assertEqual(result.text, "final answer")

    @patch("app.services.ai_service.requests.post")
    def test_openai_path_no_thinking_or_output_config(self, mock_post):
        """OpenAI path never sends thinking or output_config, even when thinking kwarg is passed."""
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
            messages=[{"role": "user", "content": "hi"}],
            thinking={"type": "disabled"},
        )
        payload = _captured_payload(mock_post)
        self.assertNotIn("thinking", payload)
        self.assertNotIn("output_config", payload)

    @patch("app.services.ai_service.requests.post")
    def test_custom_path_no_thinking_or_output_config(self, mock_post):
        """CUSTOM path (OpenAI-compatible) never sends thinking or output_config."""
        mock_custom = MagicMock()
        mock_custom.status_code = 200
        mock_custom.content = b"x"
        mock_custom.json.return_value = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]
        }
        mock_post.return_value = mock_custom
        AIService().send_message(
            provider="custom",
            model="llama3",
            api_key="",
            messages=[{"role": "user", "content": "hi"}],
            base_url_override="http://localhost:11434/v1",
            thinking={"type": "disabled"},
        )
        payload = _captured_payload(mock_post)
        self.assertNotIn("thinking", payload)
        self.assertNotIn("output_config", payload)


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
