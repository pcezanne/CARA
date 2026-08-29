"""Tests for ai_provider_config helpers.

Exhaustive truth table across provider configurations:
- none configured
- openai only (fully configured)
- anthropic only (fully configured)
- custom only (enabled, base_url, model)
- all three toggle flags active → falls back to OpenAI (exclusivity rule)
- none toggle flags active   → falls back to OpenAI (exclusivity rule)
- key present but model missing
- model present but key missing
- custom disabled (enabled=False)
- custom missing base_url
"""

import unittest

from app.services.ai_service import AIProvider
from app.utils.ai_provider_config import is_ai_configured, resolve_default_provider


def _settings(**ai_models_overrides):
    """Build a minimal user_settings dict with the given ai_models sub-keys."""
    return {"ai_models": ai_models_overrides}


def _settings_with_summary(summary_overrides, **ai_models_overrides):
    s = _settings(**ai_models_overrides)
    s["ai_summary"] = summary_overrides
    return s


class TestIsAiConfigured(unittest.TestCase):

    def test_empty_settings_returns_false(self):
        self.assertFalse(is_ai_configured({}))

    def test_openai_fully_configured_returns_true(self):
        s = _settings(openai={"api_key": "sk-abc", "model": "gpt-4o"})
        self.assertTrue(is_ai_configured(s))

    def test_anthropic_active_fully_configured_returns_true(self):
        s = _settings_with_summary(
            {"use_openai_models": False, "use_anthropic_models": True, "use_custom_models": False},
            anthropic={"api_key": "ant-key", "model": "claude-3-5-sonnet-20241022"},
        )
        self.assertTrue(is_ai_configured(s))

    def test_custom_active_fully_configured_returns_true(self):
        s = _settings_with_summary(
            {"use_openai_models": False, "use_anthropic_models": False, "use_custom_models": True},
            custom={"enabled": True, "base_url": "http://localhost:11434", "model": "llama3", "api_key": ""},
        )
        self.assertTrue(is_ai_configured(s))

    def test_openai_key_only_no_model_returns_false(self):
        s = _settings(openai={"api_key": "sk-abc", "model": ""})
        self.assertFalse(is_ai_configured(s))

    def test_openai_model_only_no_key_returns_false(self):
        s = _settings(openai={"api_key": "", "model": "gpt-4o"})
        self.assertFalse(is_ai_configured(s))

    def test_custom_disabled_returns_false(self):
        s = _settings_with_summary(
            {"use_openai_models": False, "use_anthropic_models": False, "use_custom_models": True},
            custom={"enabled": False, "base_url": "http://localhost", "model": "llama3", "api_key": ""},
        )
        self.assertFalse(is_ai_configured(s))

    def test_custom_missing_base_url_returns_false(self):
        s = _settings_with_summary(
            {"use_openai_models": False, "use_anthropic_models": False, "use_custom_models": True},
            custom={"enabled": True, "base_url": "", "model": "llama3", "api_key": ""},
        )
        self.assertFalse(is_ai_configured(s))

    def test_all_toggles_true_falls_back_to_openai(self):
        # Multiple active → fallback to OpenAI; OpenAI has valid key+model
        s = _settings_with_summary(
            {"use_openai_models": True, "use_anthropic_models": True, "use_custom_models": True},
            openai={"api_key": "sk-abc", "model": "gpt-4o"},
        )
        self.assertTrue(is_ai_configured(s))

    def test_all_toggles_false_falls_back_to_openai(self):
        # None active → fallback to OpenAI; OpenAI has valid key+model
        s = _settings_with_summary(
            {"use_openai_models": False, "use_anthropic_models": False, "use_custom_models": False},
            openai={"api_key": "sk-abc", "model": "gpt-4o"},
        )
        self.assertTrue(is_ai_configured(s))

    def test_all_toggles_false_no_openai_configured_returns_false(self):
        # None active → fallback to OpenAI; OpenAI has no key → False
        s = _settings_with_summary(
            {"use_openai_models": False, "use_anthropic_models": False, "use_custom_models": False},
            openai={"api_key": "", "model": "gpt-4o"},
        )
        self.assertFalse(is_ai_configured(s))


class TestResolveDefaultProvider(unittest.TestCase):

    def test_openai_returns_correct_tuple(self):
        s = _settings(openai={"api_key": "sk-abc", "model": "gpt-4o"})
        result = resolve_default_provider(s)
        self.assertIsNotNone(result)
        provider, model, api_key, base_url = result
        self.assertEqual(provider, AIProvider.OPENAI)
        self.assertEqual(model, "gpt-4o")
        self.assertEqual(api_key, "sk-abc")
        self.assertIsNone(base_url)

    def test_anthropic_returns_correct_tuple(self):
        s = _settings_with_summary(
            {"use_openai_models": False, "use_anthropic_models": True, "use_custom_models": False},
            anthropic={"api_key": "ant-key", "model": "claude-opus-4-7"},
        )
        result = resolve_default_provider(s)
        self.assertIsNotNone(result)
        provider, model, api_key, base_url = result
        self.assertEqual(provider, AIProvider.ANTHROPIC)
        self.assertEqual(model, "claude-opus-4-7")
        self.assertIsNone(base_url)

    def test_custom_returns_correct_tuple_with_base_url(self):
        s = _settings_with_summary(
            {"use_openai_models": False, "use_anthropic_models": False, "use_custom_models": True},
            custom={"enabled": True, "base_url": "http://localhost:11434", "model": "llama3", "api_key": "tok"},
        )
        result = resolve_default_provider(s)
        self.assertIsNotNone(result)
        provider, model, api_key, base_url = result
        self.assertEqual(provider, AIProvider.CUSTOM)
        self.assertEqual(base_url, "http://localhost:11434")
        self.assertEqual(api_key, "tok")

    def test_unconfigured_returns_none(self):
        self.assertIsNone(resolve_default_provider({}))

    def test_partial_openai_returns_none(self):
        s = _settings(openai={"api_key": "sk-abc"})  # no model key at all
        self.assertIsNone(resolve_default_provider(s))

    def test_fallback_exclusivity_openai_chosen(self):
        # Three toggles active → OpenAI wins; Anthropic also configured but ignored
        s = _settings_with_summary(
            {"use_openai_models": True, "use_anthropic_models": True, "use_custom_models": True},
            openai={"api_key": "sk-openai", "model": "gpt-4o"},
            anthropic={"api_key": "ant-key", "model": "claude-opus-4-7"},
        )
        result = resolve_default_provider(s)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], AIProvider.OPENAI)
        self.assertEqual(result[2], "sk-openai")


if __name__ == "__main__":
    unittest.main()
