"""Characterisation tests for AIRequestThread — baseline before AIResult refactor.

These tests capture the EXACT call signature that AIRequestThread.run() sends
to AIService.send_message and the exact (bool, str) semantics of response_received.

After commit 3 changes AIService.send_message to return AIResult instead of
Tuple[bool, str], AIRequestThread must unpack AIResult back to (bool, str) before
emitting response_received.emit(success, response).  These tests are the safety net:
they fail loudly if the unpack is missing or wrong.

All assertions here describe PRE-REFACTOR behavior, intentionally.  When the
refactor is correct they must still pass — if they don't, the regression is in
AIRequestThread, not in these tests.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch, call

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# AIRequestThread is defined in ai_chat_controller.py and uses QThread.
# A QApplication must exist before importing Qt classes.
from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

from app.controllers.ai_chat_controller import AIRequestThread


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_thread(
    provider: str = "openai",
    model: str = "gpt-4o",
    api_key: str = "sk-test",
    messages: list | None = None,
    system_prompt: str | None = "You are a chess coach.",
    token_limit: int | None = 2000,
    config: dict | None = None,
    base_url_override: str | None = None,
    timeout_seconds: int = 60,
) -> AIRequestThread:
    return AIRequestThread(
        provider=provider,
        model=model,
        api_key=api_key,
        messages=messages or [{"role": "user", "content": "What should I do?"}],
        system_prompt=system_prompt,
        token_limit=token_limit,
        config=config or {},
        base_url_override=base_url_override,
        timeout_seconds=timeout_seconds,
    )


# ---------------------------------------------------------------------------
# Call-signature characterisation
# ---------------------------------------------------------------------------

class TestAIRequestThreadCallSignature(unittest.TestCase):
    """Verify that run() passes the right keyword arguments to send_message.

    After the AIResult refactor, AIRequestThread unpacks AIResult into
    (bool, str).  The call SIGNATURE must remain identical — only the
    return type changes.  These tests fail if any argument is dropped,
    renamed, or reordered.
    """

    @patch("app.controllers.ai_chat_controller.AIService")
    def test_provider_passed_as_positional(self, MockAIService):
        mock_svc = MockAIService.return_value
        mock_svc.send_message.return_value = (True, "Great move!")
        thread = _make_thread(provider="anthropic")
        thread.run()
        args, kwargs = mock_svc.send_message.call_args
        self.assertEqual(args[0], "anthropic")

    @patch("app.controllers.ai_chat_controller.AIService")
    def test_model_passed_as_positional(self, MockAIService):
        mock_svc = MockAIService.return_value
        mock_svc.send_message.return_value = (True, "OK")
        thread = _make_thread(model="claude-3-5-sonnet-20241022")
        thread.run()
        args, kwargs = mock_svc.send_message.call_args
        self.assertEqual(args[1], "claude-3-5-sonnet-20241022")

    @patch("app.controllers.ai_chat_controller.AIService")
    def test_api_key_passed_as_positional(self, MockAIService):
        mock_svc = MockAIService.return_value
        mock_svc.send_message.return_value = (True, "OK")
        thread = _make_thread(api_key="sk-secret")
        thread.run()
        args, kwargs = mock_svc.send_message.call_args
        self.assertEqual(args[2], "sk-secret")

    @patch("app.controllers.ai_chat_controller.AIService")
    def test_messages_passed_as_positional(self, MockAIService):
        mock_svc = MockAIService.return_value
        mock_svc.send_message.return_value = (True, "OK")
        msgs = [{"role": "user", "content": "Is e4 good here?"}]
        thread = _make_thread(messages=msgs)
        thread.run()
        args, kwargs = mock_svc.send_message.call_args
        self.assertEqual(args[3], msgs)

    @patch("app.controllers.ai_chat_controller.AIService")
    def test_system_prompt_passed(self, MockAIService):
        mock_svc = MockAIService.return_value
        mock_svc.send_message.return_value = (True, "OK")
        sysp = "You are a grandmaster."
        thread = _make_thread(system_prompt=sysp)
        thread.run()
        args, kwargs = mock_svc.send_message.call_args
        # system_prompt is the 5th positional arg
        self.assertEqual(args[4], sysp)

    @patch("app.controllers.ai_chat_controller.AIService")
    def test_token_limit_passed_as_keyword(self, MockAIService):
        mock_svc = MockAIService.return_value
        mock_svc.send_message.return_value = (True, "OK")
        thread = _make_thread(token_limit=4096)
        thread.run()
        _args, kwargs = mock_svc.send_message.call_args
        self.assertEqual(kwargs["token_limit"], 4096)

    @patch("app.controllers.ai_chat_controller.AIService")
    def test_base_url_override_passed_as_keyword(self, MockAIService):
        mock_svc = MockAIService.return_value
        mock_svc.send_message.return_value = (True, "OK")
        thread = _make_thread(base_url_override="http://localhost:1234/v1")
        thread.run()
        _args, kwargs = mock_svc.send_message.call_args
        self.assertEqual(kwargs["base_url_override"], "http://localhost:1234/v1")

    @patch("app.controllers.ai_chat_controller.AIService")
    def test_timeout_seconds_passed_as_keyword(self, MockAIService):
        mock_svc = MockAIService.return_value
        mock_svc.send_message.return_value = (True, "OK")
        thread = _make_thread(timeout_seconds=90)
        thread.run()
        _args, kwargs = mock_svc.send_message.call_args
        self.assertEqual(kwargs["timeout_seconds"], 90)

    @patch("app.controllers.ai_chat_controller.AIService")
    def test_no_thinking_parameter(self, MockAIService):
        """AI Chat never passes thinking= — unlike the Chess Log narrative service."""
        mock_svc = MockAIService.return_value
        mock_svc.send_message.return_value = (True, "OK")
        thread = _make_thread()
        thread.run()
        _args, kwargs = mock_svc.send_message.call_args
        self.assertNotIn("thinking", kwargs)

    @patch("app.controllers.ai_chat_controller.AIService")
    def test_config_forwarded_to_ai_service_constructor(self, MockAIService):
        """AIService is constructed with self.config, not the default config."""
        mock_svc = MockAIService.return_value
        mock_svc.send_message.return_value = (True, "OK")
        cfg = {"version": "9.9"}
        thread = _make_thread(config=cfg)
        thread.run()
        MockAIService.assert_called_once_with(cfg)


# ---------------------------------------------------------------------------
# Response-semantics characterisation
# ---------------------------------------------------------------------------

class TestAIRequestThreadResponseSemantics(unittest.TestCase):
    """Verify that response_received always emits (bool, str) — never AIResult.

    After the refactor, AIRequestThread must unpack AIResult and emit
    response_received.emit(bool(result.success), str(result.text)).
    These tests assert the PRE-REFACTOR (bool, str) contract that the signal
    consumers expect.
    """

    def _run_and_collect_signal(self, mock_return_value):
        received = []

        with patch("app.controllers.ai_chat_controller.AIService") as MockAIService:
            mock_svc = MockAIService.return_value
            mock_svc.send_message.return_value = mock_return_value
            thread = _make_thread()
            thread.response_received.connect(lambda s, r: received.append((s, r)))
            thread.run()

        return received

    def test_success_emits_true_and_response_string(self):
        received = self._run_and_collect_signal((True, "Excellent positional play."))
        self.assertEqual(len(received), 1)
        success, response = received[0]
        self.assertIs(type(success), bool)
        self.assertIs(type(response), str)
        self.assertTrue(success)
        self.assertEqual(response, "Excellent positional play.")

    def test_failure_emits_false_and_error_string(self):
        received = self._run_and_collect_signal((False, "Connection refused."))
        self.assertEqual(len(received), 1)
        success, response = received[0]
        self.assertIs(type(success), bool)
        self.assertIs(type(response), str)
        self.assertFalse(success)
        self.assertEqual(response, "Connection refused.")

    def test_response_received_emitted_exactly_once(self):
        received = self._run_and_collect_signal((True, "Once only."))
        self.assertEqual(len(received), 1)

    def test_empty_response_string_forwarded(self):
        received = self._run_and_collect_signal((True, ""))
        self.assertEqual(len(received), 1)
        _success, response = received[0]
        self.assertEqual(response, "")
